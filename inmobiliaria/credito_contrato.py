"""Crédito a plazos: cargar formato del cliente y calcular deuda desde el mes 13."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .models import Cliente, FormatoAceptacion
from .formato_aceptacion_db import formato_aceptacion_defer_missing_columns


def _d(val) -> Decimal:
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def _interes_pct(raw: str | None) -> Decimal:
    s = (raw or "").strip()
    if not s:
        return Decimal("0")
    m = re.search(r"(\d+(?:[.,]\d+)?)", s)
    if not m:
        return Decimal("0")
    try:
        return Decimal(m.group(1).replace(",", ".")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def _plazo_anos(fmt: FormatoAceptacion) -> int | None:
    raw = (fmt.plazo_txt or "").strip()
    if raw.isdigit():
        y = int(raw)
        if 1 <= y <= 6:
            return y
    nraw = (fmt.num_cuota_txt or "").strip()
    if nraw.isdigit():
        n = int(nraw)
        if n > 0 and n % 12 == 0:
            y = n // 12
            if 1 <= y <= 6:
                return y
    return None


def _n_cuotas(fmt: FormatoAceptacion) -> int | None:
    y = _plazo_anos(fmt)
    if y:
        return y * 12
    raw = (fmt.num_cuota_txt or "").strip()
    if raw.isdigit():
        n = int(raw)
        return n if n > 0 else None
    return None


def _norm_dui(raw: str | None) -> str:
    return re.sub(r"[^0-9]", "", (raw or "").strip())


def _norm_nombre(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().casefold())


def buscar_formato_plazos_del_cliente(cliente: Cliente) -> FormatoAceptacion | None:
    """Último formato a plazos del cliente (por contrato, DUI o nombre)."""
    qs = formato_aceptacion_defer_missing_columns(
        FormatoAceptacion.objects.select_related("contrato", "contrato__cliente")
    ).order_by("-numero_formulario", "-id")

    def _es_plazos(f: FormatoAceptacion) -> bool:
        tipo = getattr(f, "tipo_financiamiento", "") or ""
        if tipo == FormatoAceptacion.TipoFinanciamiento.A_PLAZOS:
            return True
        if tipo == FormatoAceptacion.TipoFinanciamiento.CONTADO:
            return False
        # Sin tipo o legado: plazo + letra
        return bool(_n_cuotas(f) and f.letra_mensual)

    # 1) Formatos ligados a contratos de este cliente
    for f in qs.filter(contrato__cliente_id=cliente.pk)[:20]:
        if _es_plazos(f):
            return f

    # 2) Por DUI (con o sin guiones)
    dui_cli = _norm_dui(cliente.dui)
    if dui_cli:
        for f in qs[:80]:
            if _norm_dui(f.dui_numero) == dui_cli and _es_plazos(f):
                return f

    # 3) Por nombre completo o partes (nombres + apellidos)
    nombre = _norm_nombre(f"{(cliente.nombres or '')} {(cliente.apellidos or '')}")
    if nombre:
        for f in qs[:80]:
            fn = _norm_nombre(f.nombre_cliente)
            if not fn:
                continue
            if fn == nombre and _es_plazos(f):
                return f
        # Contiene ambos apellidos/nombres (orden flexible)
        partes = [p for p in nombre.split(" ") if len(p) > 1]
        if len(partes) >= 2:
            for f in qs[:80]:
                fn = _norm_nombre(f.nombre_cliente)
                if fn and all(p in fn for p in partes) and _es_plazos(f):
                    return f

    return None


def pmt_cuota(principal: Decimal, n_meses: int, tasa_anual_pct: Decimal) -> Decimal | None:
    if n_meses < 1 or principal <= 0:
        return None
    tasa = tasa_anual_pct if tasa_anual_pct is not None else Decimal("0")
    if tasa <= 0:
        return (principal / Decimal(n_meses)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    r = (tasa / Decimal("100")) / Decimal("12")
    rf = float(r)
    nf = int(n_meses)
    pf = float(principal)
    factor = (1 + rf) ** nf
    if factor <= 1:
        return (principal / Decimal(n_meses)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    pay = pf * rf * factor / (factor - 1)
    return Decimal(str(round(pay, 2)))


def resolver_inmueble_desde_formato(fmt: FormatoAceptacion):
    """Localiza el lote del inventario por No. de lote (+ proyecto) del formato."""
    from .models import Inmueble

    codigo = (fmt.num_lote or "").strip()
    if not codigo:
        return None
    qs = Inmueble.objects.select_related("proyecto", "poligono").exclude(
        estado=Inmueble.Estado.VENDIDO
    )
    # Exacto
    inv = qs.filter(codigo__iexact=codigo).first()
    if inv:
        return inv
    # Contiene código
    proy = (fmt.nombre_proyecto or "").strip()
    if proy:
        inv = qs.filter(codigo__icontains=codigo, proyecto__nombre__icontains=proy).first()
        if inv:
            return inv
    inv = qs.filter(codigo__icontains=codigo).first()
    if inv:
        return inv
    # A veces el formato guarda solo el número y el código es "Lote 1"
    return qs.filter(codigo__icontains=f"lote {codigo}").first() or qs.filter(
        codigo__icontains=f"Lote {codigo}"
    ).first()


def montos_reserva_prima_pagados(cliente: Cliente, fmt: FormatoAceptacion | None = None) -> dict[str, Decimal]:
    """Suma de pagos validados (o pendientes) de reserva y prima del cliente."""
    from django.db.models import Q, Sum

    from .models import Pago

    base = Pago.objects.filter(
        validacion_abono__in=[
            Pago.ValidacionAbono.VALIDADO,
            Pago.ValidacionAbono.PENDIENTE,
        ]
    ).filter(
        Q(contrato__cliente_id=cliente.pk)
        | (Q(formato_aceptacion_id=fmt.pk) if fmt is not None else Q(pk__in=[]))
    )
    reserva = base.filter(concepto=Pago.Concepto.RESERVA).aggregate(t=Sum("monto"))["t"]
    prima = base.filter(concepto=Pago.Concepto.PRIMA).aggregate(t=Sum("monto"))["t"]
    return {
        "reserva": _d(reserva).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "prima": _d(prima).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }


def calcular_nueva_deuda_mes13(
    fmt: FormatoAceptacion,
    *,
    descuento: Decimal | None = None,
    prima: Decimal | None = None,
    reserva: Decimal | None = None,
    cliente: Cliente | None = None,
) -> dict[str, Any]:
    """
    Monto inicial − descuento − reserva pagada − prima − cuotas 1–12
    → nueva deuda; cuotas restantes desde el mes 13 con interés.
    """
    anos = _plazo_anos(fmt)
    n_total = _n_cuotas(fmt)
    interes = _interes_pct(fmt.interes_txt)
    letra = fmt.letra_mensual

    inv = resolver_inmueble_desde_formato(fmt)
    monto_inicial = fmt.valor_inmueble if fmt.valor_inmueble is not None else fmt.valor_financiamiento
    if monto_inicial is None and inv is not None:
        monto_inicial = inv.precio_lista
    monto_inicial = _d(monto_inicial)

    desc = _d(descuento)
    if desc < 0:
        desc = Decimal("0")

    pagos = {"reserva": Decimal("0.00"), "prima": Decimal("0.00")}
    if cliente is not None:
        pagos = montos_reserva_prima_pagados(cliente, fmt)

    # Reserva del formato (campo prima_1) y prima a pagar (campo prima_2)
    reserva_formato = _d(fmt.prima_1).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    prima_formato = _d(fmt.prima_2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Reserva: pago real si existe; si no, la del formato
    if reserva is not None:
        reserva_total = _d(reserva)
    elif pagos["reserva"] > 0:
        reserva_total = pagos["reserva"]
    else:
        reserva_total = reserva_formato
    if reserva_total < 0:
        reserva_total = Decimal("0")
    reserva_total = reserva_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Prima: pago real si existe; si no, la del formato; override del form gana
    if prima is not None:
        prima_total = _d(prima)
    elif pagos["prima"] > 0:
        prima_total = pagos["prima"]
    else:
        prima_total = prima_formato
    if prima_total < 0:
        prima_total = Decimal("0")
    prima_total = prima_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    meses_sin_int = 12
    if n_total is not None:
        meses_sin_int = min(12, n_total)
    abono_cuotas = Decimal("0")
    if letra is not None and letra > 0:
        abono_cuotas = (letra * Decimal(meses_sin_int)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    abonado = (reserva_total + prima_total + abono_cuotas).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    nueva_deuda = (
        monto_inicial - desc - reserva_total - prima_total - abono_cuotas
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if nueva_deuda < 0:
        nueva_deuda = Decimal("0.00")

    meses_restantes = 0
    if n_total and n_total > 12:
        meses_restantes = n_total - 12
    elif n_total and n_total <= 12:
        meses_restantes = 0

    cuota_con_interes = None
    if meses_restantes > 0 and nueva_deuda > 0:
        cuota_con_interes = pmt_cuota(nueva_deuda, meses_restantes, interes)

    listado_cuotas: list[dict[str, Any]] = []
    if n_total and letra is not None and letra > 0:
        for i in range(1, n_total + 1):
            if i <= meses_sin_int:
                listado_cuotas.append(
                    {
                        "numero": i,
                        "concepto": f"Cuota {i} (sin interes)",
                        "monto": str(letra.quantize(Decimal("0.01"))),
                        "fase": "sin_interes",
                    }
                )
            else:
                monto_i = cuota_con_interes if cuota_con_interes is not None else letra
                listado_cuotas.append(
                    {
                        "numero": i,
                        "concepto": f"Cuota {i} (con interes {interes:g}%)",
                        "monto": str(monto_i.quantize(Decimal("0.01"))),
                        "fase": "con_interes",
                    }
                )

    lote_label = ""
    if inv is not None:
        lote_label = getattr(inv, "label_venta", None) or str(inv)

    return {
        "ok": True,
        "formato_id": fmt.pk,
        "formato_numero": fmt.numero_formulario,
        "tipo": getattr(fmt, "tipo_financiamiento", "") or "",
        "es_plazos": True,
        "nombre_cliente": (fmt.nombre_cliente or "").strip(),
        "monto_inicial": str(monto_inicial),
        "descuento": str(desc),
        "reserva_pagada": str(reserva_total),
        "reserva_formato": str(reserva_formato),
        "reserva_tiene_pago": bool(pagos["reserva"] > 0),
        "primas": str(prima_total),
        "prima_formato": str(prima_formato),
        "prima_pagada": str(pagos["prima"]),
        "prima_tiene_pago": bool(pagos["prima"] > 0),
        "abono_cuotas_1_a_12": str(abono_cuotas),
        "cuota_sin_interes": str(letra.quantize(Decimal("0.01"))) if letra else "",
        "meses_sin_interes": meses_sin_int,
        "abonado_0_a_12": str(abonado),
        "nueva_deuda": str(nueva_deuda),
        "plazo_anos": anos,
        "n_cuotas_total": n_total,
        "n_cuotas_restantes": meses_restantes,
        "interes_anual_pct": str(interes),
        "cuota_mensual_con_interes": str(cuota_con_interes) if cuota_con_interes is not None else "",
        "valor_financiamiento": str(_d(fmt.valor_financiamiento)),
        "num_lote": (fmt.num_lote or "").strip(),
        "nombre_proyecto": (fmt.nombre_proyecto or "").strip(),
        "poligono_txt": (fmt.poligono_txt or "").strip(),
        "inmueble_id": inv.pk if inv is not None else None,
        "inmueble_label": lote_label,
        "listado_cuotas": listado_cuotas,
        "autofill": True,
        "resumen": (
            f"Lote {(fmt.num_lote or '—')} · valor ${_fmt(monto_inicial)} "
            f"- desc. ${_fmt(desc)} - reserva ${_fmt(reserva_total)} "
            f"- prima ${_fmt(prima_total)} - cuotas 1-{meses_sin_int} (${_fmt(abono_cuotas)}) "
            f"= nueva deuda ${_fmt(nueva_deuda)}. "
            + (
                f"Desde mes 13: {meses_restantes} cuotas de ${_fmt(cuota_con_interes)} "
                f"({interes:g}% anual)."
                if cuota_con_interes is not None and meses_restantes > 0
                else "Plazo ≤ 12 meses: sin fase con interés desde el mes 13."
            )
        ),
    }


def _fmt(v: Decimal | None) -> str:
    if v is None:
        return "0.00"
    return f"{Decimal(v).quantize(Decimal('0.01')):,.2f}"


def credito_plazos_para_cliente(
    cliente: Cliente,
    *,
    descuento: Decimal | None = None,
    prima: Decimal | None = None,
    reserva: Decimal | None = None,
) -> dict[str, Any]:
    fmt = buscar_formato_plazos_del_cliente(cliente)
    if not fmt:
        return {
            "ok": False,
            "es_plazos": False,
            "mensaje": (
                "Este cliente no tiene un formato de aceptación a plazos guardado. "
                "Primero cree y guarde el formato (paso 1) con lote, valor, primas, "
                "cuota 1–12 y plazo; luego vuelva aquí y solo elija el cliente."
            ),
            "necesita_formato": True,
            "cliente_id": cliente.pk,
            **{k: v for k, v in elegibilidad_nuevo_plan_mes13(cliente).items()},
        }
    tipo = getattr(fmt, "tipo_financiamiento", "") or ""
    if tipo and tipo != FormatoAceptacion.TipoFinanciamiento.A_PLAZOS:
        return {
            "ok": False,
            "es_plazos": False,
            "mensaje": "El formato del cliente no es «Con Financiamiento (A Plazos)».",
            "tipo": tipo,
            "formato_id": fmt.pk,
            **{k: v for k, v in elegibilidad_nuevo_plan_mes13(cliente).items()},
        }
    if not fmt.letra_mensual or not _n_cuotas(fmt):
        return {
            "ok": False,
            "es_plazos": True,
            "mensaje": (
                "El formato a plazos está incompleto: faltan la cuota de los meses 1–12 "
                "o el plazo/número de cuotas."
            ),
            "formato_id": fmt.pk,
            **{k: v for k, v in elegibilidad_nuevo_plan_mes13(cliente).items()},
        }
    data = calcular_nueva_deuda_mes13(
        fmt,
        descuento=descuento,
        prima=prima,
        reserva=reserva,
        cliente=cliente,
    )
    data["necesita_formato"] = False
    data.update(elegibilidad_nuevo_plan_mes13(cliente))
    return data


def es_plan_mes13(contrato) -> bool:
    """Planes generados con «Nuevo plan de pagos» (deuda desde el mes 13)."""
    num = (getattr(contrato, "numero", None) or "").strip()
    return num.upper().startswith("PP-")


def contratos_base_cliente(cliente: Cliente):
    """Contratos del cliente que NO son el plan post–mes 13 (PP-…)."""
    from .models import Contrato

    return (
        Contrato.objects.filter(cliente_id=cliente.pk)
        .exclude(numero__istartswith="PP-")
        .order_by("-fecha_firma", "-id")
    )


def plan_mes13_del_cliente(cliente: Cliente, *, exclude_pk: int | None = None):
    """Si ya existe un plan PP- para el cliente (solo debe haber uno)."""
    from .models import Contrato

    qs = Contrato.objects.filter(cliente_id=cliente.pk, numero__istartswith="PP-").order_by(
        "-id"
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


def elegibilidad_nuevo_plan_mes13(
    cliente: Cliente,
    *,
    exclude_pk: int | None = None,
) -> dict[str, Any]:
    """
    El «Nuevo plan de pagos» (deuda con interés desde el mes 13) solo se crea:
    - después de tener pagadas las cuotas 1–12 del plan base, y
    - una sola vez por cliente.
    """
    from .models import CuotaProgramada

    existente = plan_mes13_del_cliente(cliente, exclude_pk=exclude_pk)
    if existente is not None:
        return {
            "puede_crear_plan_mes13": False,
            "motivo_plan_mes13": (
                f"Este cliente ya tiene el plan de pagos #{existente.numero}. "
                "Solo se permite uno por cliente (después de los 12 meses sin interés). "
                "Ábralo en Editar / Cuotas; no cree otro."
            ),
            "cuotas_1_12_pagadas": 0,
            "cuotas_1_12_requeridas": 12,
            "contrato_base_numero": "",
            "plan_mes13_numero": existente.numero,
            "plan_mes13_id": existente.pk,
        }

    base = contratos_base_cliente(cliente).first()
    if base is None:
        return {
            "puede_crear_plan_mes13": False,
            "motivo_plan_mes13": (
                "Aún no hay un plan base del cliente (formato → reserva → prima → cuotas 1–12). "
                "El plan nuevo con interés solo se crea cuando esas 12 cuotas ya estén pagadas."
            ),
            "cuotas_1_12_pagadas": 0,
            "cuotas_1_12_requeridas": 12,
            "contrato_base_numero": "",
            "plan_mes13_numero": "",
            "plan_mes13_id": None,
        }

    nums_pagadas = set(
        CuotaProgramada.objects.filter(
            contrato_id=base.pk,
            numero__gte=1,
            numero__lte=12,
            estado=CuotaProgramada.Estado.PAGADA,
        ).values_list("numero", flat=True)
    )
    n_pagadas = len(nums_pagadas)
    completas = all(i in nums_pagadas for i in range(1, 13))
    if not completas:
        return {
            "puede_crear_plan_mes13": False,
            "motivo_plan_mes13": (
                f"Faltan cuotas del primer año sin interés en el plan #{base.numero}: "
                f"van {n_pagadas} de 12 pagadas. "
                "Cuando estén las 12, podrá crear aquí el plan único con interés (mes 13 en adelante)."
            ),
            "cuotas_1_12_pagadas": n_pagadas,
            "cuotas_1_12_requeridas": 12,
            "contrato_base_numero": base.numero,
            "plan_mes13_numero": "",
            "plan_mes13_id": None,
        }

    return {
        "puede_crear_plan_mes13": True,
        "motivo_plan_mes13": (
            f"Listo: las 12 cuotas sin interés del plan #{base.numero} están pagadas. "
            "Puede crear un solo plan de pagos con la nueva deuda e interés desde el mes 13."
        ),
        "cuotas_1_12_pagadas": 12,
        "cuotas_1_12_requeridas": 12,
        "contrato_base_numero": base.numero,
        "plan_mes13_numero": "",
        "plan_mes13_id": None,
    }


def cliente_desde_formato_aceptacion(fmt: FormatoAceptacion) -> Cliente:
    """Localiza o crea el cliente a partir del formato (DUI / nombre)."""
    from .models import Cliente

    dui = _norm_dui(fmt.dui_numero)
    if dui:
        for c in Cliente.objects.all().only("id", "dui", "nombres", "apellidos")[:500]:
            if _norm_dui(c.dui) == dui:
                return c
    nombre = _norm_nombre(fmt.nombre_cliente)
    if nombre:
        for c in Cliente.objects.all().only("id", "dui", "nombres", "apellidos")[:500]:
            cn = _norm_nombre(f"{c.nombres or ''} {c.apellidos or ''}")
            if cn == nombre:
                return c
    raw_nombre = (fmt.nombre_cliente or "").strip() or "Cliente contado"
    partes = raw_nombre.split(None, 1)
    nombres = partes[0][:120]
    apellidos = (partes[1] if len(partes) > 1 else "—")[:120]
    tel = (
        (fmt.telefono_domicilio or "").strip()
        or (fmt.telefono_notificacion or "").strip()
        or (fmt.telefono_trabajo or "").strip()
    )[:40]
    return Cliente.objects.create(
        nombres=nombres,
        apellidos=apellidos,
        dui=(fmt.dui_numero or "").strip()[:20],
        telefono=tel,
        direccion=(fmt.direccion_domicilio or "").strip()[:255],
    )


def asegurar_contrato_contado_desde_formato(fmt: FormatoAceptacion):
    """
    Para venta de contado: usa el contrato del formato o crea uno
    (sin financiamiento) con el valor del lote.
    """
    from datetime import date

    from django.utils import timezone

    from .models import Contrato, FormatoAceptacion as FA, Inmueble

    if fmt.contrato_id:
        return fmt.contrato

    # Buscar contrato existente por lote + proyecto (mismo criterio que el formulario de pago).
    num_lote = (fmt.num_lote or "").strip()
    nom_proy = (fmt.nombre_proyecto or "").strip()
    existente = None
    if num_lote and nom_proy:
        inv_qs = (
            Inmueble.objects.filter(codigo__iexact=num_lote)
            .select_related("proyecto")
            .order_by("id")
        )
        inv = None
        nom_lower = nom_proy.lower()
        for candidate in inv_qs:
            pn = (candidate.proyecto.nombre or "").strip() if candidate.proyecto_id else ""
            if pn.lower() == nom_lower:
                inv = candidate
                break
        if inv is None and inv_qs.count() == 1:
            inv = inv_qs.first()
        if inv is not None:
            existente = (
                Contrato.objects.filter(inmueble_id=inv.pk)
                .order_by("-fecha_firma", "-id")
                .first()
            )
    if existente is not None:
        FA.objects.filter(pk=fmt.pk).update(contrato_id=existente.pk)
        fmt.contrato_id = existente.pk
        return existente

    inv = resolver_inmueble_desde_formato(fmt)
    if inv is None:
        return None

    cliente = cliente_desde_formato_aceptacion(fmt)
    precio = fmt.valor_inmueble if fmt.valor_inmueble is not None else inv.precio_lista
    precio = _d(precio)
    stamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    base = f"VC-{stamp}"
    numero = base
    n = 1
    while Contrato.objects.filter(numero=numero).exists():
        n += 1
        numero = f"{base}-{n}"

    contrato = Contrato.objects.create(
        cliente=cliente,
        inmueble=inv,
        numero=numero,
        fecha_firma=date.today(),
        estado=Contrato.Estado.ACTIVO,
        etapa_comercial=Contrato.EtapaComercial.DOCUMENTOS,
        precio_lista_referencia=precio,
        precio_final=precio,
        modalidad_financiamiento=Contrato.ModalidadFinanciamiento.SIN_FINANCIAMIENTO,
        meses_sin_interes=0,
        notas=f"Venta de contado desde formato Nº {fmt.numero_formulario:04d}.",
    )
    # Vendedor + comisión desde «Elaborado por» del formato.
    from inmobiliaria.comision_vendedor import vendedor_por_nombre_elaborado

    vp = vendedor_por_nombre_elaborado(getattr(fmt, "elaborado_por", "") or "")
    if vp is not None:
        Contrato.objects.filter(pk=contrato.pk).update(
            vendedor_perfil_id=vp.pk,
            vendedor_nombre=vp.nombre_completo[:120],
            vendedor_id=vp.usuario_vinculo_id,
            comision_porcentaje=vp.porcentaje_comision_default,
        )
        contrato.refresh_from_db()
    FA.objects.filter(pk=fmt.pk).update(contrato_id=contrato.pk)
    fmt.contrato_id = contrato.pk
    return contrato
