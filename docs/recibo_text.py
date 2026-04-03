"""Texto auxiliar para recibos PDF (formato monetario SV y monto en letras)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from num2words import num2words


def format_monto_sv(monto) -> str:
    """Ej. 333.82 -> $333,82 · 1234567.5 -> $1.234.567,50"""
    try:
        d = Decimal(str(monto)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return str(monto)
    neg = d < 0
    d = abs(d)
    ent = int(d)
    dec = int((d * 100) % 100)
    ent_s = f"{ent:,}".replace(",", ".")
    sign = "-" if neg else ""
    return f"{sign}${ent_s},{dec:02d}"


def monto_usd_letras_es(monto) -> str:
    """Leyenda tipo recibo: «Trescientos treinta y tres dólares con 82/100»."""
    try:
        d = Decimal(str(monto)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    ent = int(abs(d))
    dec = int((abs(d) * 100) % 100)
    try:
        palabras = num2words(ent, lang="es")
    except Exception:
        palabras = str(ent)
    if palabras:
        palabras = palabras[0].upper() + palabras[1:]
    else:
        palabras = "Cero"
    return f"{palabras} dólares con {dec:02d}/100"
