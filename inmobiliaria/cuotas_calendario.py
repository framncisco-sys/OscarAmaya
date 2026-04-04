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


def _n_cuotas_desde_formato(fmt: FormatoAceptacion) -> int | None:
    raw = (fmt.num_cuota_txt or "").strip()
    if raw.isdigit():
        n = int(raw)
        return n if n > 0 else None
    plazo = (fmt.plazo_txt or "").strip()
    if plazo.isdigit():
        y = int(plazo)
        if 0 < y <= 50:
            return y * 12
    return None


def _letra_mensual_listado(fmt: FormatoAceptacion, n_cuotas: int) -> Decimal | None:
    letra = fmt.letra_mensual
    if letra is not None and letra > 0:
        return letra.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    vf = fmt.valor_financiamiento
    if vf is not None and vf > 0 and n_cuotas > 0:
        return (vf / Decimal(n_cuotas)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return None


def filas_listado_cuotas_formato_aceptacion(fmt: FormatoAceptacion) -> list[dict[str, Any]]:
    """
    Filas para «listado de cuotas a pagar»: primas (con fecha) y luego cuotas mensuales
    (mismo día de cada mes desde fecha primera cuota).
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
        append_row("Prima 1", fmt.prima_1_fecha, m1)
    p2 = fmt.prima_2
    if (p2 is not None and p2 > 0) or fmt.prima_2_fecha is not None:
        m2 = p2 if p2 is not None and p2 > 0 else None
        append_row("Prima 2", fmt.prima_2_fecha, m2)

    n_cuotas = _n_cuotas_desde_formato(fmt)
    if not n_cuotas:
        return rows

    fecha0 = fmt.fecha_primera_cuota or _parse_fecha_texto_formato(
        fmt.fecha_pago_mensual or ""
    )
    if not fecha0:
        return rows

    letra = _letra_mensual_listado(fmt, n_cuotas)
    for i in range(n_cuotas):
        append_row(f"Cuota {i + 1}", add_months(fecha0, i), letra)

    return rows
