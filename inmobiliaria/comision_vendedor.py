"""Requisitos para emitir recibo de comisión de venta al vendedor."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Prefetch

from inmobiliaria.models import Contrato, Pago, Vendedor


@dataclass(frozen=True)
class EstadoConceptoAbono:
    registrado: bool
    validado: bool
    monto: object | None
    detalle: str


@dataclass(frozen=True)
class EstadoVendedorCompleto:
    ok: bool
    nombre: str
    faltantes: tuple[str, ...]
    detalle: str


@dataclass(frozen=True)
class RequisitosComisionVenta:
    vendedor_ok: bool
    vendedor_nombre: str
    vendedor_completo: EstadoVendedorCompleto
    comision_ok: bool
    comision_monto: object | None
    reserva: EstadoConceptoAbono
    prima: EstadoConceptoAbono
    contado: EstadoConceptoAbono
    es_venta_contado: bool
    puede_emitir: bool
    motivos: tuple[str, ...]


def vendedor_datos_completos(vendedor: Vendedor | None) -> EstadoVendedorCompleto:
    """El vendedor debe tener ficha completa (como en el registro) y estar activo."""
    if vendedor is None:
        return EstadoVendedorCompleto(
            ok=False,
            nombre="",
            faltantes=("vendedor",),
            detalle="Sin asesor de ventas del catálogo asignado al contrato.",
        )
    nombre = (vendedor.nombre_completo or "").strip()
    faltan: list[str] = []
    if not (vendedor.nombres or "").strip():
        faltan.append("nombres")
    if not (vendedor.apellidos or "").strip():
        faltan.append("apellidos")
    if not (vendedor.dui or "").strip():
        faltan.append("DUI")
    if not (vendedor.telefono or "").strip():
        faltan.append("teléfono")
    if not (vendedor.email or "").strip():
        faltan.append("correo")
    if vendedor.porcentaje_comision_default is None:
        faltan.append("comisión %")
    if not vendedor.activo:
        faltan.append("activo")
    if faltan:
        return EstadoVendedorCompleto(
            ok=False,
            nombre=nombre,
            faltantes=tuple(faltan),
            detalle=(
                f"Asesor de ventas «{nombre or '—'}» incompleto o no al día: faltan "
                + ", ".join(faltan)
                + ". Complete su ficha en Asesores de ventas (registro)."
            ),
        )
    return EstadoVendedorCompleto(
        ok=True,
        nombre=nombre,
        faltantes=(),
        detalle=f"Asesor de ventas «{nombre}» con ficha completa (comisión {vendedor.porcentaje_comision_default}%).",
    )


def _label_concepto(concepto: str) -> str:
    if concepto == Pago.Concepto.RESERVA:
        return "Reserva"
    if concepto == Pago.Concepto.PRIMA:
        return "Prima"
    if concepto == Pago.Concepto.CONTADO:
        return "Pago de contado (total del lote)"
    return concepto


def _estado_abono(contrato: Contrato, concepto: str) -> EstadoConceptoAbono:
    pref = getattr(contrato, "_pagos_comision_pref", None)
    if pref is not None:
        pagos = [p for p in pref if p.concepto == concepto]
    else:
        pagos = list(
            contrato.pagos.filter(concepto=concepto).order_by("-fecha", "-id")
        )
    label = _label_concepto(concepto)
    if not pagos:
        return EstadoConceptoAbono(
            registrado=False,
            validado=False,
            monto=None,
            detalle=f"{label}: aún no registrado.",
        )

    validados = [
        p
        for p in pagos
        if p.validacion_abono == Pago.ValidacionAbono.VALIDADO
        or (
            p.validacion_abono == Pago.ValidacionAbono.NO_APLICA
            and p.puede_emitir_recibo_cliente
        )
    ]
    if validados:
        p = validados[0]
        return EstadoConceptoAbono(
            registrado=True,
            validado=True,
            monto=p.monto,
            detalle=f"{label}: pagado y confirmado en cuenta (${p.monto}).",
        )

    pendientes = [
        p for p in pagos if p.validacion_abono == Pago.ValidacionAbono.PENDIENTE
    ]
    if pendientes:
        p = pendientes[0]
        return EstadoConceptoAbono(
            registrado=True,
            validado=False,
            monto=p.monto,
            detalle=f"{label}: registrado (${p.monto}) pero pendiente de validación de gerencia.",
        )

    p = pagos[0]
    return EstadoConceptoAbono(
        registrado=True,
        validado=False,
        monto=p.monto,
        detalle=f"{label}: registrado pero no válido para comisión (${p.monto}).",
    )


def _es_venta_contado(contrato: Contrato, contado: EstadoConceptoAbono) -> bool:
    """True si hay pago CONTADO o el contrato es sin financiamiento."""
    if contado.registrado:
        return True
    mod = getattr(contrato, "modalidad_financiamiento", "") or ""
    return mod == Contrato.ModalidadFinanciamiento.SIN_FINANCIAMIENTO


def requisitos_comision_venta(contrato: Contrato) -> RequisitosComisionVenta:
    """
    Comisión al vendedor cuando:
    - Plazos: reserva + prima validadas, o
    - Contado: pago de contado (total del lote) validado,
    y el vendedor tiene ficha completa con su % de comisión.
    """
    vp = getattr(contrato, "vendedor_perfil", None)
    if vp is None and getattr(contrato, "vendedor_perfil_id", None):
        vp = Vendedor.objects.filter(pk=contrato.vendedor_perfil_id).first()
    completo = vendedor_datos_completos(vp)
    nombre = completo.nombre or (contrato.nombre_vendedor_documentos() or "").strip()
    vendedor_ok = bool(nombre) and completo.ok

    comision_monto = contrato.monto_comision_efectivo()
    if (comision_monto is None or comision_monto <= 0) and vp is not None:
        pct = vp.porcentaje_comision_default
        if pct is not None and contrato.precio_final is not None:
            from decimal import Decimal

            comision_monto = (
                contrato.precio_final * pct / Decimal("100")
            ).quantize(Decimal("0.01"))
    comision_ok = comision_monto is not None and comision_monto > 0

    reserva = _estado_abono(contrato, Pago.Concepto.RESERVA)
    prima = _estado_abono(contrato, Pago.Concepto.PRIMA)
    contado = _estado_abono(contrato, Pago.Concepto.CONTADO)
    es_contado = _es_venta_contado(contrato, contado)

    motivos: list[str] = []
    if not completo.ok:
        motivos.append(completo.detalle)
    elif not nombre:
        motivos.append(
            "Asigne el asesor de ventas (catálogo Asesores de ventas o «Elaborado por» del formato)."
        )
    if not comision_ok:
        motivos.append(
            "Defina la comisión % en el registro del asesor de ventas (o el monto en el contrato)."
        )

    if es_contado:
        if not contado.validado:
            motivos.append(contado.detalle)
        pagos_ok = contado.validado
    else:
        if not reserva.validado:
            motivos.append(reserva.detalle)
        if not prima.validado:
            motivos.append(prima.detalle)
        pagos_ok = reserva.validado and prima.validado

    puede = vendedor_ok and completo.ok and comision_ok and pagos_ok
    return RequisitosComisionVenta(
        vendedor_ok=vendedor_ok,
        vendedor_nombre=nombre,
        vendedor_completo=completo,
        comision_ok=comision_ok,
        comision_monto=comision_monto,
        reserva=reserva,
        prima=prima,
        contado=contado,
        es_venta_contado=es_contado,
        puede_emitir=puede,
        motivos=tuple(motivos),
    )


def ya_existe_recibo_comision(contrato_id: int) -> bool:
    from docs.models import DocumentoEmitido, DocumentoTipo

    return DocumentoEmitido.objects.filter(
        contrato_id=contrato_id,
        tipo=DocumentoTipo.RECIBO_COMISION_VENDEDOR,
    ).exists()


def intentar_emitir_comision_automatica(contrato_id: int, *, emitido_por=None):
    """
    Genera el recibo de comisión al vendedor si:
    - plazos: reserva + prima validadas, o
    - contado: pago total del lote validado,
    y el vendedor está completo.
    """
    if not contrato_id:
        return None
    if ya_existe_recibo_comision(contrato_id):
        return None
    contrato = (
        Contrato.objects.select_related("vendedor_perfil", "cliente", "inmueble")
        .filter(pk=contrato_id)
        .first()
    )
    if contrato is None:
        return None
    req = requisitos_comision_venta(contrato)
    if not req.puede_emitir:
        return None
    from docs.services import emitir_recibo_comision_vendedor

    if contrato.comision_porcentaje is None and contrato.vendedor_perfil_id:
        vp = contrato.vendedor_perfil
        if vp and vp.porcentaje_comision_default is not None:
            Contrato.objects.filter(pk=contrato.pk).update(
                comision_porcentaje=vp.porcentaje_comision_default
            )
            contrato.refresh_from_db(fields=["comision_porcentaje"])

    concepto = (
        "Comisión de venta (pago de contado validado)"
        if req.es_venta_contado
        else "Comisión de venta (reserva y prima pagadas)"
    )
    return emitir_recibo_comision_vendedor(
        contrato=contrato,
        emitido_por=emitido_por,
        monto_comision=req.comision_monto,
        comision_porcentaje=contrato.comision_porcentaje
        or (
            contrato.vendedor_perfil.porcentaje_comision_default
            if contrato.vendedor_perfil_id
            else None
        ),
        concepto=concepto,
    )


def prefetch_pagos_para_comision(qs):
    """Optimiza listados que evalúan reserva/prima/contado por contrato."""
    return qs.prefetch_related(
        Prefetch(
            "pagos",
            queryset=Pago.objects.filter(
                concepto__in=[
                    Pago.Concepto.RESERVA,
                    Pago.Concepto.PRIMA,
                    Pago.Concepto.CONTADO,
                ]
            ).order_by("-fecha", "-id"),
            to_attr="_pagos_comision_pref",
        )
    )


def vendedor_por_nombre_elaborado(nombre: str) -> Vendedor | None:
    """Resuelve el catálogo Asesores de ventas desde el texto «Elaborado por»."""
    n = (nombre or "").strip().casefold()
    if not n:
        return None
    if " — " in n:
        n = n.split(" — ", 1)[0].strip()
    for v in Vendedor.objects.all().only(
        "id", "nombres", "apellidos", "porcentaje_comision_default", "usuario_vinculo_id"
    ):
        if v.nombre_completo.strip().casefold() == n:
            return v
    return None


def _siguiente_paso_comision(req: RequisitosComisionVenta) -> str:
    """Texto corto: qué falta para ganar la comisión."""
    if req.puede_emitir:
        return "Listo: ya puede generarse su comisión (reserva/prima o contado validados)."
    if req.motivos:
        return req.motivos[0]
    return "Complete el flujo de venta para ganar la comisión."


def _accion_sugerida(req: RequisitosComisionVenta) -> dict:
    """Enlace útil dentro del flujo del vendedor."""
    if req.puede_emitir:
        return {
            "label": "Ver mis documentos",
            "url_name": "docs_list",
            "query": "",
        }
    if req.es_venta_contado:
        if not req.contado.registrado:
            return {
                "label": "Registrar pago de contado",
                "url_name": "pago_create",
                "query": "?concepto=CONTADO",
            }
        if not req.contado.validado:
            return {
                "label": "Ver estado del recibo (pendiente gerencia)",
                "url_name": "pago_list",
                "query": "",
            }
    else:
        if not req.reserva.registrado:
            return {
                "label": "Registrar reserva",
                "url_name": "pago_create",
                "query": "?concepto=RESERVA",
            }
        if not req.reserva.validado:
            return {
                "label": "Reserva pendiente de validar",
                "url_name": "pago_list",
                "query": "",
            }
        if not req.prima.registrado:
            return {
                "label": "Registrar prima",
                "url_name": "pago_create",
                "query": "?concepto=PRIMA",
            }
        if not req.prima.validado:
            return {
                "label": "Prima pendiente de validar",
                "url_name": "pago_list",
                "query": "",
            }
    return {
        "label": "Ver mis recibos",
        "url_name": "pago_list",
        "query": "",
    }


def resumen_progreso_comision_vendedor(user) -> dict:
    """
    Resumen para el portal del vendedor:
    lotes en cartera, comisiones ganadas y qué falta en cada venta.
    """
    from django.urls import reverse

    from inmobiliaria.contratos_acceso import filtrar_contratos_queryset_por_vendedor
    from inmobiliaria.models import Inmueble

    qs = filtrar_contratos_queryset_por_vendedor(
        Contrato.objects.exclude(estado=Contrato.Estado.CANCELADO)
        .select_related(
            "cliente",
            "inmueble",
            "inmueble__proyecto",
            "vendedor_perfil",
        )
        .order_by("-fecha_firma", "-id"),
        user,
    )
    qs = prefetch_pagos_para_comision(qs)

    items: list[dict] = []
    lotes_vendidos = 0
    lotes_reservados = 0
    comisiones_emitidas = 0
    comisiones_listas = 0
    comisiones_pendientes = 0
    monto_comision_estimada = None
    from decimal import Decimal

    monto_acum = Decimal("0.00")
    con_monto = 0

    for c in qs[:40]:
        req = requisitos_comision_venta(c)
        emitido = ya_existe_recibo_comision(c.pk)
        inv = c.inmueble
        estado_lote = inv.estado if inv is not None else ""
        if estado_lote == Inmueble.Estado.VENDIDO:
            lotes_vendidos += 1
        elif estado_lote == Inmueble.Estado.RESERVADO:
            lotes_reservados += 1

        if emitido:
            comisiones_emitidas += 1
            estado = "ganada"
            siguiente = "Comisión ya emitida (revise Mis documentos PDF)."
        elif req.puede_emitir:
            comisiones_listas += 1
            estado = "lista"
            siguiente = _siguiente_paso_comision(req)
        else:
            comisiones_pendientes += 1
            estado = "pendiente"
            siguiente = _siguiente_paso_comision(req)

        if req.comision_monto is not None and req.comision_monto > 0:
            monto_acum += Decimal(req.comision_monto)
            con_monto += 1

        accion = _accion_sugerida(req)
        try:
            href = reverse(f"app:{accion['url_name']}") + (accion.get("query") or "")
        except Exception:
            href = reverse("app:pago_list")

        cliente = ""
        if c.cliente_id:
            cliente = f"{(c.cliente.nombres or '').strip()} {(c.cliente.apellidos or '').strip()}".strip()
        lote = inv.codigo_display if inv is not None else "—"
        proy = inv.proyecto.nombre if inv is not None and inv.proyecto_id else ""

        items.append(
            {
                "contrato_id": c.pk,
                "lote": lote,
                "proyecto": proy,
                "cliente": cliente or "—",
                "estado_lote": estado_lote,
                "estado_lote_label": inv.get_estado_display() if inv else "—",
                "comision_monto": req.comision_monto,
                "es_contado": req.es_venta_contado,
                "estado": estado,
                "siguiente": siguiente,
                "accion_label": accion["label"],
                "accion_url": href,
                "reserva_ok": req.reserva.validado,
                "prima_ok": req.prima.validado,
                "contado_ok": req.contado.validado,
                "emitido": emitido,
            }
        )

    total = qs.count()
    return {
        "total_contratos": total,
        "lotes_vendidos": lotes_vendidos,
        "lotes_reservados": lotes_reservados,
        "comisiones_emitidas": comisiones_emitidas,
        "comisiones_listas": comisiones_listas,
        "comisiones_pendientes": comisiones_pendientes,
        "monto_comision_estimada": monto_acum if con_monto else None,
        "items": items,
    }
