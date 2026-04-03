import re

from django.core.exceptions import ValidationError


def validar_dui_sv(value: str) -> None:
    """DUI salvadoreño: 9 dígitos (sin o con guión opcional)."""
    if not value:
        return
    s = value.strip().replace("-", "")
    if not re.fullmatch(r"\d{9}", s):
        raise ValidationError("El DUI debe tener 9 dígitos.")


def validar_nit_sv(value: str) -> None:
    """NIT común en SV (persona natural/jurídica): solo dígitos, longitud típica 9–14."""
    if not value:
        return
    s = value.strip().replace("-", "")
    if not re.fullmatch(r"\d{9,14}", s):
        raise ValidationError("El NIT debe contener entre 9 y 14 dígitos.")
