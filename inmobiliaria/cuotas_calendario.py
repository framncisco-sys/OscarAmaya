"""Generación del calendario de cuotas programadas (fechas y montos)."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .models import Contrato, CuotaProgramada


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
