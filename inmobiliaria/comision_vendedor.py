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
            detalle="Sin vendedor del catálogo asignado al contrato.",
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
                f"Vendedor «{nombre or '—'}» incompleto o no al día: faltan "
                + ", ".join(faltan)
                + ". Complete su ficha en Vendedores (registro)."
            ),
        )
    return EstadoVendedorCompleto(
        ok=True,
        nombre=nombre,
        faltantes=(),
        detalle=f"Vendedor «{nombre}» con ficha completa (comisión {vendedor.porcentaje_comision_default}%).",
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
            "Asigne el vendedor (catálogo Vendedores o «Elaborado por» del formato)."
        )
    if not comision_ok:
        motivos.append(
            "Defina la comisión % en el registro del vendedor (o el monto en el contrato)."
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
    """Resuelve el catálogo Vendedores desde el texto «Elaborado por»."""
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
