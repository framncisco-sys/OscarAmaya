"""Teléfonos El Salvador (+503) para formularios y WhatsApp (Meta / Twilio / wa.me)."""

from __future__ import annotations

from django.conf import settings


def digitos_telefono_e164_sv(raw: str | None, pais: str | None = None) -> str | None:
    """
    Solo dígitos con código país, sin '+' (p. ej. 50370123456).
    Móvil local: 8 dígitos → se antepone 503. Con 0 inicial (9 dígitos) se quita el 0.
    Si ya empieza por 503 y tiene longitud adecuada, se devuelve tal cual.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return None
    p = (pais or getattr(settings, "RECIBO_WHATSAPP_PAIS", None) or "503").strip()
    if digits.startswith(p) and len(digits) >= 11:
        return digits
    if len(digits) == 8:
        return f"{p}{digits}"
    if len(digits) == 9 and digits.startswith("0"):
        return f"{p}{digits[1:]}"
    if len(digits) >= 10:
        return digits
    return None


def normalizar_guardado_telefono_sv(raw: str | None) -> str:
    """
    Valor legible para guardar en CharField: +503 NNNN NNNN cuando es móvil SV de 8 dígitos
    (o ya viene con 503); si no encaja, devuelve dígitos normalizados o el texto original.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    p = getattr(settings, "RECIBO_WHATSAPP_PAIS", None) or "503"
    core = digitos_telefono_e164_sv(s, p)
    if not core:
        return s
    if core.startswith(p) and len(core) == 11 and core[3:].isdigit() and len(core[3:]) == 8:
        rest = core[3:]
        return f"+{p} {rest[:4]} {rest[4:]}"
    return core
