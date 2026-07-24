"""Requisitos para emitir recibo de comisión de venta al vendedor."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Prefetch

from inmobiliaria.models import Contrato, Pago


@dataclass(frozen=True)
class EstadoConceptoAbono:
    registrado: bool
    validado: bool
    monto: object | None
    detalle: str


@dataclass(frozen=True)
class RequisitosComisionVenta:
    vendedor_ok: bool
    vendedor_nombre: str
    comision_ok: bool
    comision_monto: object | None
    reserva: EstadoConceptoAbono
    prima: EstadoConceptoAbono
    puede_emitir: bool
    motivos: tuple[str, ...]


def _estado_abono(contrato: Contrato, concepto: str) -> EstadoConceptoAbono:
    pref = getattr(contrato, "_pagos_comision_pref", None)
    if pref is not None:
        pagos = [p for p in pref if p.concepto == concepto]
    else:
        pagos = list(
            contrato.pagos.filter(concepto=concepto).order_by("-fecha", "-id")
        )
    if not pagos:
        label = "Reserva" if concepto == Pago.Concepto.RESERVA else "Prima"
        return EstadoConceptoAbono(
            registrado=False,
            validado=False,
            monto=None,
            detalle=f"{label}: aún no registrada.",
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
    label = "Reserva" if concepto == Pago.Concepto.RESERVA else "Prima"
    if validados:
        p = validados[0]
        return EstadoConceptoAbono(
            registrado=True,
            validado=True,
            monto=p.monto,
            detalle=f"{label}: pagada y confirmada en cuenta (${p.monto}).",
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
            detalle=f"{label}: registrada (${p.monto}) pero pendiente de validación de gerencia.",
        )

    p = pagos[0]
    return EstadoConceptoAbono(
        registrado=True,
        validado=False,
        monto=p.monto,
        detalle=f"{label}: registrada pero no válida para comisión (${p.monto}).",
    )


def requisitos_comision_venta(contrato: Contrato) -> RequisitosComisionVenta:
    """
    Para generar el recibo de comisión de venta hace falta:
    1) Vendedor en el contrato
    2) Comisión definida (% o monto)
    3) Reserva pagada y validada
    4) Prima pagada y validada
    """
    nombre = (contrato.nombre_vendedor_documentos() or "").strip()
    vendedor_ok = bool(nombre)
    comision_monto = contrato.monto_comision_efectivo()
    comision_ok = comision_monto is not None and comision_monto > 0

    reserva = _estado_abono(contrato, Pago.Concepto.RESERVA)
    prima = _estado_abono(contrato, Pago.Concepto.PRIMA)

    motivos: list[str] = []
    if not vendedor_ok:
        motivos.append(
            "Asigne el vendedor en el contrato (catálogo Vendedores) y defina su comisión."
        )
    if not comision_ok:
        motivos.append(
            "Defina en el contrato el % de comisión o el monto fijo de comisión del vendedor."
        )
    if not reserva.validado:
        motivos.append(reserva.detalle)
    if not prima.validado:
        motivos.append(prima.detalle)

    puede = vendedor_ok and comision_ok and reserva.validado and prima.validado
    return RequisitosComisionVenta(
        vendedor_ok=vendedor_ok,
        vendedor_nombre=nombre,
        comision_ok=comision_ok,
        comision_monto=comision_monto,
        reserva=reserva,
        prima=prima,
        puede_emitir=puede,
        motivos=tuple(motivos),
    )


def prefetch_pagos_para_comision(qs):
    """Optimiza listados que evalúan reserva/prima por contrato."""
    return qs.prefetch_related(
        Prefetch(
            "pagos",
            queryset=Pago.objects.filter(
                concepto__in=[Pago.Concepto.RESERVA, Pago.Concepto.PRIMA]
            ).order_by("-fecha", "-id"),
            to_attr="_pagos_comision_pref",
        )
    )
