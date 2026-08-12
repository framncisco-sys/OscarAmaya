"""Generación del calendario de cuotas programadas (fechas y montos)."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .models import Contrato, CuotaProgramada, FormatoAceptacion


def _parse_fecha_texto_formato(raw: str) -> date | None:
    """Interpreta «Fecha de pago mensual» del formato (texto o fecha ISO desde el formulario web)."""
    s = (raw or "").strip()
    if not s:
        return None
    for pat in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        for candidate in (s[:10], s):
            try:
                return datetime.strptime(candidate, pat).date()
            except ValueError:
                continue
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def fecha_primera_cuota_desde_formato_contrato(contrato: Contrato | None) -> date | None:
    """
    Primera fecha de vencimiento sugerida para el calendario de cuotas, según el formato
    de aceptación vinculado al contrato: «Fecha pago primera cuota» o, si falta, «Fecha de pago mensual».
    Las cuotas generadas con construir_cuotas_programadas repiten el mismo día de cada mes.
    """
    if not contrato or not getattr(contrato, "pk", None):
        return None
    fmt = (
        FormatoAceptacion.objects.filter(contrato_id=contrato.pk)
        .defer("promesa_venta_escaneada", "contrato_compraventa_escaneado")
        .first()
    )
    if not fmt:
        return None
    if fmt.fecha_primera_cuota:
        return fmt.fecha_primera_cuota
    return _parse_fecha_texto_formato(fmt.fecha_pago_mensual or "")


def add_months(d: date, months: int) -> date:
    """Suma meses calendario (ajusta el día si el mes destino es más corto)."""
    total_m = d.month - 1 + months
    y = d.year + total_m // 12
    m = total_m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    day = min(d.day, last)
    return date(y, m, day)


def monto_uniforme_por_cuota(
    precio_final: Decimal,
    n_cuotas: int,
    monto_propuesto: Decimal | None,
) -> Decimal:
    """Monto a repetir en cada cuota; si no hay propuesta, precio ÷ n."""
    if n_cuotas < 1:
        raise ValueError("n_cuotas debe ser >= 1")
    if monto_propuesto is not None and monto_propuesto > 0:
        return monto_propuesto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (precio_final / Decimal(n_cuotas)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def construir_cuotas_programadas(
    contrato: Contrato,
    *,
    fecha_primera: date,
    n_cuotas: int,
    monto_cuota: Decimal,
) -> list[CuotaProgramada]:
    """Instancias nuevas (sin guardar) numeradas 1..n, una por mes."""
    out: list[CuotaProgramada] = []
    for i in range(n_cuotas):
        out.append(
            CuotaProgramada(
                contrato=contrato,
                numero=i + 1,
                vence_en=add_months(fecha_primera, i),
                monto=monto_cuota,
                estado=CuotaProgramada.Estado.PENDIENTE,
            )
        )
    return out


def construir_cuotas_desde_listado_credito(
    contrato: Contrato,
    *,
    fecha_primera: date,
    listado_cuotas: list[dict[str, Any]],
) -> list[CuotaProgramada]:
    """
    Genera cuotas con montos por fase (1–12 sin interés; desde 13 con interés)
    a partir del listado de credito_contrato.
    """
    out: list[CuotaProgramada] = []
    for row in listado_cuotas:
        try:
            num = int(row.get("numero") or 0)
            monto = Decimal(str(row.get("monto") or "0"))
        except Exception:
            continue
        if num < 1 or monto <= 0:
            continue
        out.append(
            CuotaProgramada(
                contrato=contrato,
                numero=num,
                vence_en=add_months(fecha_primera, num - 1),
                monto=monto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                estado=CuotaProgramada.Estado.PENDIENTE,
            )
        )
    return out


def aplicar_calendario_desde_formato_cliente(
    contrato: Contrato,
    *,
    descuento: Decimal | None = None,
    prima: Decimal | None = None,
    forzar: bool = False,
) -> int:
    """
    Vincula formato al contrato y crea el calendario de cuotas a plazos.
    Devuelve cantidad de cuotas creadas (0 si no aplica).
    """
    from inmobiliaria.credito_contrato import (
        buscar_formato_plazos_del_cliente,
        credito_plazos_para_cliente,
        es_plan_mes13,
    )

    if not contrato.cliente_id:
        return 0
    if (
        not forzar
        and contrato.cuotas_programadas.filter(estado=CuotaProgramada.Estado.PAGADA).exists()
    ):
        return 0

    data = credito_plazos_para_cliente(
        contrato.cliente, descuento=descuento, prima=prima
    )
    if not data.get("ok"):
        return 0

    fmt = buscar_formato_plazos_del_cliente(contrato.cliente)
    if fmt is not None and not fmt.contrato_id:
        FormatoAceptacion.objects.filter(pk=fmt.pk, contrato__isnull=True).update(
            contrato_id=contrato.pk
        )

    fecha_primera = None
    if fmt is not None:
        if fmt.fecha_primera_cuota:
            fecha_primera = fmt.fecha_primera_cuota
        else:
            fecha_primera = _parse_fecha_texto_formato(fmt.fecha_pago_mensual or "")
    if fecha_primera is None:
        from django.utils import timezone

        fecha_primera = getattr(contrato, "fecha_firma", None) or timezone.localdate()

    listado = data.get("listado_cuotas") or []
    if es_plan_mes13(contrato):
        # Plan PP-: solo cuotas con interés (mes 13 en adelante), misma numeración del formato.
        listado = [row for row in listado if int(row.get("numero") or 0) >= 13]
    nuevas = construir_cuotas_desde_listado_credito(
        contrato, fecha_primera=fecha_primera, listado_cuotas=listado
    )
    if not nuevas:
        return 0

    contrato.cuotas_programadas.all().delete()
    CuotaProgramada.objects.bulk_create(nuevas)
    return len(nuevas)


def _n_cuotas_desde_formato(fmt: FormatoAceptacion) -> int | None:
    raw = (fmt.num_cuota_txt or "").strip()
    if raw.isdigit():
        n = int(raw)
        return n if n > 0 else None
    plazo = (fmt.plazo_txt or "").strip()
    if plazo.isdigit():
        y = int(plazo)
        if 1 <= y <= 6:
            return y * 12
    return None


def _interes_anual_desde_formato(fmt: FormatoAceptacion) -> Decimal:
    raw = (fmt.interes_txt or "").strip()
    if not raw:
        return Decimal("0")
    m = re.search(r"(\d+(?:[.,]\d+)?)", raw)
    if not m:
        return Decimal("0")
    try:
        return Decimal(m.group(1).replace(",", ".")).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def cuota_minima_y_con_interes(
    *,
    valor_financiamiento: Decimal | None,
    letra_mensual: Decimal | None,
    n_cuotas: int,
    interes_anual_pct: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """
    Retorna (cuota_vendedor_sin_interes, cuota_desde_mes_13, saldo_tras_12).

    Meses 1–12: cuota del asesor sin interés.
    Desde el mes 13: PMT sobre el saldo restante (valor a financiar − 12 cuotas)
    repartido en los meses que faltan, con interés anual.
    """
    if n_cuotas < 1:
        return None, None, None
    if letra_mensual is None or letra_mensual <= 0:
        return None, None, None
    letra = letra_mensual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    vf = valor_financiamiento if valor_financiamiento is not None else Decimal("0")
    if vf < 0:
        vf = Decimal("0")

    if n_cuotas <= 12:
        return letra, None, None

    tasa = interes_anual_pct if interes_anual_pct is not None else Decimal("0")
    if tasa < 0:
        tasa = Decimal("0")
    pagos_sin_int = min(12, n_cuotas)
    saldo = vf - (letra * Decimal(pagos_sin_int))
    if saldo < 0:
        saldo = Decimal("0")
    saldo = saldo.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    from inmobiliaria.credito_contrato import pmt_cuota

    meses_restantes = n_cuotas - pagos_sin_int
    cuota_13 = pmt_cuota(saldo, meses_restantes, tasa)
    if cuota_13 is None:
        cuota_13 = letra
    return letra, cuota_13, saldo


def texto_plan_financiamiento_a_plazos(fmt: FormatoAceptacion) -> str:
    """Resumen automático del plan (para observaciones / PDF)."""
    if getattr(fmt, "tipo_financiamiento", None) == FormatoAceptacion.TipoFinanciamiento.CONTADO:
        return "Tipo de financiamiento: Contado."
    n = _n_cuotas_desde_formato(fmt)
    if not n:
        return ""
    interes = _interes_anual_desde_formato(fmt)
    letra, cuota_13, saldo = cuota_minima_y_con_interes(
        valor_financiamiento=fmt.valor_financiamiento,
        letra_mensual=fmt.letra_mensual,
        n_cuotas=n,
        interes_anual_pct=interes,
    )
    if letra is None:
        return ""
    años = n // 12
    from .money_fmt import format_monto_us

    lm = format_monto_us(letra, con_simbolo=True)
    if n <= 12:
        return (
            f"Plan a plazos ({años} año{'s' if años != 1 else ''}, {n} cuotas): "
            f"cuota escrita por el asesor de ventas {lm} sin interés en todas las cuotas."
        )
    c13 = format_monto_us(cuota_13 or letra, con_simbolo=True)
    return (
        f"Plan a plazos ({años} años, {n} cuotas): meses 1–12 sin interés "
        f"(cuota del asesor de ventas {lm}). Desde el mes 13: cuota fija {c13} "
        f"sobre saldo restante ({format_monto_us(saldo or 0, con_simbolo=True)}) "
        f"con interés {interes:g}% anual en {n - 12} cuotas."
    )


def filas_listado_cuotas_formato_aceptacion(fmt: FormatoAceptacion) -> list[dict[str, Any]]:
    """
    Filas para «listado de cuotas a pagar»: primas y plan mensual.
    Misma lógica que el plan de pagos (mes 13): saldo tras reserva, prima y
    12 cuotas sin interés, repartido con PMT en los meses restantes.
    """
    rows: list[dict[str, Any]] = []
    linea = 0

    def append_row(concepto: str, fecha: date | None, monto: Decimal | None) -> None:
        nonlocal linea
        linea += 1
        rows.append({"linea": linea, "concepto": concepto, "fecha": fecha, "monto": monto})

    p1 = fmt.prima_1
    if (p1 is not None and p1 > 0) or fmt.prima_1_fecha is not None:
        m1 = p1 if p1 is not None and p1 > 0 else None
        append_row("Reserva", fmt.prima_1_fecha, m1)
    p2 = fmt.prima_2
    if (p2 is not None and p2 > 0) or fmt.prima_2_fecha is not None:
        m2 = p2 if p2 is not None and p2 > 0 else None
        append_row("Prima a pagar", fmt.prima_2_fecha, m2)

    if getattr(fmt, "tipo_financiamiento", None) == FormatoAceptacion.TipoFinanciamiento.CONTADO:
        return rows

    n = _n_cuotas_desde_formato(fmt)
    if not n:
        return rows

    fecha0 = fmt.fecha_primera_cuota or _parse_fecha_texto_formato(
        fmt.fecha_pago_mensual or ""
    )

    from inmobiliaria.credito_contrato import calcular_nueva_deuda_mes13

    data = calcular_nueva_deuda_mes13(fmt)
    listado = data.get("listado_cuotas") or []

    if not listado:
        letra = fmt.letra_mensual
        vf = fmt.valor_financiamiento
        if (letra is None or letra <= 0) and vf is not None and vf > 0:
            letra = (vf / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if letra is not None and letra > 0:
            interes = _interes_anual_desde_formato(fmt)
            _, cuota_13, _ = cuota_minima_y_con_interes(
                valor_financiamiento=vf,
                letra_mensual=letra,
                n_cuotas=n,
                interes_anual_pct=interes,
            )
            for i in range(1, n + 1):
                if i <= 12:
                    monto = letra
                    concepto = f"Cuota {i} (sin interés — cuota del asesor de ventas)"
                else:
                    monto = cuota_13 if cuota_13 is not None else letra
                    concepto = f"Cuota {i} (con interés {interes:g}%)"
                append_row(
                    concepto,
                    add_months(fecha0, i - 1) if fecha0 else None,
                    monto,
                )
        return rows

    interes = _interes_anual_desde_formato(fmt)
    for row in listado:
        try:
            num = int(row.get("numero") or 0)
            monto = Decimal(str(row.get("monto") or "0"))
        except Exception:
            continue
        if num < 1 or monto <= 0:
            continue
        if num <= 12:
            concepto = f"Cuota {num} (sin interés — cuota del asesor de ventas)"
        else:
            concepto = f"Cuota {num} (con interés {interes:g}%)"
        append_row(
            concepto,
            add_months(fecha0, num - 1) if fecha0 else None,
            monto,
        )

    return rows
