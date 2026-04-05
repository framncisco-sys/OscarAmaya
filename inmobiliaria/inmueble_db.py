"""
Introspección de columnas de `Inmueble` para despliegues sin migración al día (p. ej. 0028).

Si el código incluye `modo_catalogo` y campos de alquiler pero PostgreSQL aún no tiene esas columnas,
cualquier SELECT que traiga el modelo completo falla. Se aplica `.defer()` en querysets hasta que existan.
"""

from __future__ import annotations

from django.db import connection

from inmobiliaria.models import Inmueble

INMUEBLE_CATALOGO_ALQUILER_FIELDS = (
    "modo_catalogo",
    "precio_alquiler_mensual",
    "deposito_alquiler",
)


def _inmueble_column_names_lower() -> set[str] | None:
    table = Inmueble._meta.db_table
    try:
        with connection.cursor() as cursor:
            desc = connection.introspection.get_table_description(cursor, table)
        return {(getattr(row, "name", "") or "").lower() for row in desc}
    except Exception:
        return None


def inmueble_catalogo_alquiler_columns_ready() -> bool:
    """True si existe `modo_catalogo` (migración 0028+)."""
    names = _inmueble_column_names_lower()
    if names is None:
        return True
    return "modo_catalogo" in names


def inmueble_defer_missing_catalogo_columns(qs):
    """Evita que el SELECT pida columnas que aún no existen en la BD."""
    if not inmueble_catalogo_alquiler_columns_ready():
        qs = qs.defer(*INMUEBLE_CATALOGO_ALQUILER_FIELDS)
    return qs
