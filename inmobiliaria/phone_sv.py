"""Teléfonos: El Salvador (8 dígitos) siempre válido; con «+» detecta otro país.

Sin prefijo internacional se asume El Salvador (+503) y se aceptan exactamente 8 dígitos.
Con «+» y código de país se guarda en formato internacional.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError

try:
    import phonenumbers
    from phonenumbers import NumberParseException, PhoneNumberFormat, region_code_for_number
except ImportError:  # pragma: no cover
    phonenumbers = None  # type: ignore[assignment]
    NumberParseException = Exception  # type: ignore[misc,assignment]
    PhoneNumberFormat = None  # type: ignore[assignment]
    region_code_for_number = None  # type: ignore[assignment]


TEL_HELP_TEXT = (
    "El Salvador: 8 dígitos (ej. 7012-3456). "
    "Otro país: escriba «+» y el código (ej. +52 55 1234 5678). "
    "Puede escribir libremente; al salir del campo se formatea solo."
)

TEL_PLACEHOLDER = "7012-3456  o  +52 55 …"

TEL_TITLE = (
    "El Salvador: 8 dígitos. Otro país: empiece con + (ej. +503, +52, +1)."
)

_TEL_ERROR = (
    "Teléfono no válido. En El Salvador use 8 dígitos (ej. 70123456). "
    "Para otro país escriba «+» y el código (ej. +52 55 1234 5678)."
)


def _solo_digitos(raw: str) -> str:
    return "".join(c for c in str(raw) if c.isdigit())


def _formato_sv_8(digits8: str) -> str:
    d = _solo_digitos(digits8)[:8]
    if len(d) != 8:
        return d
    return f"+503 {d[:4]} {d[4:]}"


def _region_default() -> str:
    try:
        raw = getattr(settings, "RECIBO_WHATSAPP_PAIS", None) or "SV"
    except Exception:
        raw = "SV"
    raw = str(raw).strip().upper()
    if raw.isdigit() or len(raw) != 2:
        return "SV"
    return raw


def _parse_intl(raw: str, region: str | None = None):
    """Parsea con phonenumbers solo cuando hay indicio internacional o texto con +."""
    if phonenumbers is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    reg = (region or _region_default()).upper()
    try:
        num = phonenumbers.parse(s, None if s.startswith("+") else reg)
    except NumberParseException:
        digits = _solo_digitos(s)
        if not digits:
            return None
        try:
            if digits.startswith("00"):
                num = phonenumbers.parse("+" + digits[2:], None)
            elif len(digits) >= 11:
                num = phonenumbers.parse("+" + digits, None)
            else:
                return None
        except NumberParseException:
            return None
    if not phonenumbers.is_possible_number(num):
        return None
    return num


def detectar_pais_telefono(raw: str | None, region: str | None = None) -> dict | None:
    """
    Metadatos del número. Prioriza 8 dígitos = El Salvador.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    digits = _solo_digitos(s)
    # Caso principal del negocio: móvil/fijo SV de 8 dígitos (con o sin guion).
    if len(digits) == 8 and not s.startswith("+"):
        return {
            "region": "SV",
            "country_code": 503,
            "e164": f"+503{digits}",
            "internacional": _formato_sv_8(digits),
            "nacional": f"{digits[:4]} {digits[4:]}",
        }
    if len(digits) == 11 and digits.startswith("503"):
        rest = digits[3:]
        return {
            "region": "SV",
            "country_code": 503,
            "e164": f"+{digits}",
            "internacional": _formato_sv_8(rest),
            "nacional": f"{rest[:4]} {rest[4:]}",
        }
    if len(digits) == 9 and digits.startswith("0"):
        rest = digits[1:]
        if len(rest) == 8:
            return {
                "region": "SV",
                "country_code": 503,
                "e164": f"+503{rest}",
                "internacional": _formato_sv_8(rest),
                "nacional": f"{rest[:4]} {rest[4:]}",
            }

    num = _parse_intl(s, region)
    if num is None or phonenumbers is None:
        return None
    reg = region_code_for_number(num) or ""
    return {
        "region": reg,
        "country_code": num.country_code,
        "e164": phonenumbers.format_number(num, PhoneNumberFormat.E164),
        "internacional": phonenumbers.format_number(num, PhoneNumberFormat.INTERNATIONAL),
        "nacional": phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL),
    }


def digitos_telefono_e164_sv(raw: str | None, pais: str | None = None) -> str | None:
    """Solo dígitos con código país, sin '+' (p. ej. 50370123456)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    region = None
    if pais:
        p = str(pais).strip()
        if p.isdigit() and p == "503":
            region = "SV"
        elif len(p) == 2:
            region = p.upper()

    info = detectar_pais_telefono(s, region)
    if info:
        return info["e164"].lstrip("+")

    digits = _solo_digitos(s)
    if not digits:
        return None
    if len(digits) == 8:
        return f"503{digits}"
    if len(digits) == 11 and digits.startswith("503"):
        return digits
    if len(digits) >= 10:
        return digits
    return None


def normalizar_guardado_telefono_sv(raw: str | None) -> str:
    """Valor legible para CharField (sin lanzar error)."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    info = detectar_pais_telefono(s)
    if info:
        return info["internacional"][:40]
    digits = _solo_digitos(s)
    if len(digits) == 8:
        return _formato_sv_8(digits)
    return s[:40]


def limpiar_telefono_formulario(raw, *, allow_empty: bool = True) -> str:
    """
    Normaliza para guardar en BD.
    Siempre acepta exactamente 8 dígitos (El Salvador).
    Otros países: «+» y código, o 503 + 8 dígitos.
    """
    if raw is None or not str(raw).strip():
        if allow_empty:
            return ""
        raise ValidationError("Indique el teléfono.")
    raw = str(raw).strip()
    digits = _solo_digitos(raw)

    # El Salvador: exactamente 8 dígitos — siempre válido.
    if len(digits) == 8:
        return _formato_sv_8(digits)
    if len(digits) == 11 and digits.startswith("503"):
        return _formato_sv_8(digits[3:])
    if len(digits) == 9 and digits.startswith("0") and len(digits[1:]) == 8:
        return _formato_sv_8(digits[1:])

    # Local sin «+»: solo se aceptan 8 dígitos (arriba). Cualquier otra longitud es error.
    if not raw.startswith("+"):
        if 1 <= len(digits) < 8:
            raise ValidationError(
                "En El Salvador el teléfono debe tener 8 dígitos (ej. 7012-3456)."
            )
        raise ValidationError(_TEL_ERROR)

    info = detectar_pais_telefono(raw)
    if info:
        return info["internacional"][:40]

    raise ValidationError(_TEL_ERROR)


def aplicar_attrs_telefono(field, *, help_text: bool = True) -> None:
    """Atributos de widget + ayuda para campos de teléfono en formularios."""
    if field is None:
        return
    w = field.widget
    cls = (w.attrs.get("class") or "").strip()
    parts = cls.split() if cls else []
    for token in ("input", "input--tel-intl"):
        if token not in parts:
            parts.append(token)
    w.attrs["class"] = " ".join(parts)
    w.attrs["maxlength"] = "40"
    w.attrs["inputmode"] = "tel"
    w.attrs["autocomplete"] = "tel"
    w.attrs["data-tel-intl"] = "1"
    w.attrs["placeholder"] = TEL_PLACEHOLDER
    w.attrs["title"] = TEL_TITLE
    if help_text:
        field.help_text = TEL_HELP_TEXT
