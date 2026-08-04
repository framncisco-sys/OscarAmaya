"""Formato monetario: miles con coma, decimales con punto (ej. 22,500.00)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalizar_monto_a_decimal_str(value: str) -> str:
    """
    Convierte entrada de usuario a cadena decimal con punto.
    Acepta 22,500.00 · 22500.00 · 22.500,00 · 22500,50
    """
    s = (value or "").strip().replace(" ", "").replace("\u00a0", "").replace("$", "")
    if not s:
        return s
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # Europeo: 22.500,00
            s = s.replace(".", "").replace(",", ".")
        else:
            # US / solicitado: 22,500.00
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) <= 2:
            # Decimal con coma: 22500,50
            s = parts[0].replace(".", "") + "." + parts[1]
        else:
            # Miles con coma: 22,500
            s = s.replace(",", "")
    return s


def format_monto_us(monto, *, con_simbolo: bool = False) -> str:
    """22,500.00 o $22,500.00"""
    if monto is None:
        return ""
    if isinstance(monto, str) and not monto.strip():
        return ""
    try:
        d = Decimal(str(monto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return str(monto)
    formatted = f"{d:,.2f}"
    return f"${formatted}" if con_simbolo else formatted


def format_numero_us(monto, *, decimales: int = 2) -> str:
    """Número con miles en coma y decimales en punto (sin $)."""
    if monto is None:
        return ""
    if isinstance(monto, str) and not monto.strip():
        return ""
    dec = max(0, min(int(decimales), 8))
    q = Decimal("1").scaleb(-dec) if dec else Decimal("1")
    try:
        d = Decimal(str(monto)).quantize(q, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return str(monto)
    return f"{d:,.{dec}f}"
