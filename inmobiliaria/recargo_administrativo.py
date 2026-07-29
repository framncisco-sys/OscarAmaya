"""Recargo administrativo (no «mora» diaria): monto fijo + días de gracia.

Si una cuota no se paga y pasan los días de gracia, en el mes siguiente
el cobro esperado es: cuota del mes + recargo(s) pendientes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from inmobiliaria.models import CuotaProgramada, ParametroMora, Pago


def parametro_recargo_activo() -> ParametroMora | None:
    return (
        ParametroMora.objects.filter(activo=True)
        .order_by("-id")
        .first()
    )


def fecha_limite_gracia(vence_en: date, dias_gracia: int) -> date:
    return vence_en + timedelta(days=max(0, int(dias_gracia or 0)))


def cuota_impaga(cuota: CuotaProgramada) -> bool:
    if cuota.pago_id is not None:
        return False
    return cuota.estado in (
        CuotaProgramada.Estado.PENDIENTE,
        CuotaProgramada.Estado.VENCIDA,
    )


def cuota_genera_recargo(
    cuota: CuotaProgramada,
    *,
    hoy: date | None = None,
    dias_gracia: int = 0,
) -> bool:
    """True si la cuota sigue sin pagar y ya pasó el vencimiento + gracia."""
    if not cuota_impaga(cuota):
        return False
    corte = hoy or timezone.localdate()
    return corte > fecha_limite_gracia(cuota.vence_en, dias_gracia)


def monto_recargos_pagados(contrato_id: int) -> Decimal:
    """Suma de recargos cubiertos: pagos MORA + recargo incluido en pagos de cuota."""
    qs_mora = Pago.objects.filter(
        contrato_id=contrato_id,
        concepto=Pago.Concepto.MORA,
    ).exclude(validacion_abono=Pago.ValidacionAbono.RECHAZADO)
    mora = qs_mora.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    qs_inc = Pago.objects.filter(
        contrato_id=contrato_id,
        concepto=Pago.Concepto.CUOTA,
    ).exclude(validacion_abono=Pago.ValidacionAbono.RECHAZADO)
    incluido = qs_inc.aggregate(t=Sum("monto_recargo_incluido"))["t"] or Decimal("0")
    return (mora + incluido).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class CobroMes:
    """Qué debe verse al cobrar el mes (cuota actual + recargos)."""

    cuota: CuotaProgramada | None
    monto_cuota: Decimal
    monto_recargo: Decimal
    cantidad_recargos: int
    monto_total: Decimal
    dias_gracia: int
    monto_unitario_recargo: Decimal
    cuotas_que_generan_recargo: tuple[CuotaProgramada, ...]
    nota: str


def resumen_cobro_contrato(
    contrato,
    *,
    hoy: date | None = None,
) -> CobroMes:
    """
    Próxima cuota pendiente/vencida + recargos por cuotas anteriores
    (o la misma) que ya superaron la gracia y aún no están cubiertos
    con pagos de recargo administrativo.
    """
    corte = hoy or timezone.localdate()
    param = parametro_recargo_activo()
    dias_gracia = int(param.dias_gracia) if param else 0
    unitario = (
        (param.monto_recargo or Decimal("0"))
        if param
        else Decimal("0")
    )

    cuotas = list(
        CuotaProgramada.objects.filter(contrato_id=contrato.pk).order_by(
            "numero", "id"
        )
    )
    generadoras = [
        c
        for c in cuotas
        if cuota_genera_recargo(c, hoy=corte, dias_gracia=dias_gracia)
    ]

    pagado_recargos = monto_recargos_pagados(contrato.pk)
    if unitario > 0:
        cubiertos = int(pagado_recargos // unitario)
        pendientes = max(0, len(generadoras) - cubiertos)
        monto_recargo = (unitario * pendientes).quantize(Decimal("0.01"))
    else:
        pendientes = 0
        monto_recargo = Decimal("0.00")

    proxima = next((c for c in cuotas if cuota_impaga(c)), None)
    monto_cuota = proxima.monto if proxima else Decimal("0.00")
    total = (monto_cuota + monto_recargo).quantize(Decimal("0.01"))

    if pendientes and proxima:
        nota = (
            f"Cuota #{proxima.numero} (${monto_cuota}) + "
            f"{pendientes} recargo(s) administrativo(s) (${monto_recargo}). "
            f"Gracia: {dias_gracia} día(s) tras el vencimiento."
        )
    elif proxima:
        nota = f"Cuota #{proxima.numero}: ${monto_cuota} (sin recargo administrativo pendiente)."
    else:
        nota = "No hay cuotas pendientes."

    return CobroMes(
        cuota=proxima,
        monto_cuota=monto_cuota,
        monto_recargo=monto_recargo,
        cantidad_recargos=pendientes,
        monto_total=total,
        dias_gracia=dias_gracia,
        monto_unitario_recargo=unitario,
        cuotas_que_generan_recargo=tuple(generadoras),
        nota=nota,
    )


def detalle_recargo_por_cuota(
    cuota: CuotaProgramada,
    *,
    hoy: date | None = None,
    dias_gracia: int = 0,
    monto_unitario: Decimal = Decimal("0"),
) -> dict:
    """Datos de fila para estado de cuenta."""
    corte = hoy or timezone.localdate()
    genera = cuota_genera_recargo(
        cuota, hoy=corte, dias_gracia=dias_gracia
    )
    limite = fecha_limite_gracia(cuota.vence_en, dias_gracia)
    return {
        "genera_recargo": genera,
        "fecha_limite_gracia": limite,
        "monto_recargo_unitario": monto_unitario if genera else Decimal("0"),
    }
