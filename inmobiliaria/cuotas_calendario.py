"""Generación del calendario de cuotas programadas (fechas y montos)."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

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
        .defer("promesa_venta_escaneada")
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
