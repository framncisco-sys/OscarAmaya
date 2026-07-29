"""
Introspección de columnas de `FormatoAceptacion` para despliegues sin migración al día.

Si el código Django incluye campos que aún no existen en PostgreSQL, el SELECT falla.
Se usa `.defer()` en querysets y se omiten campos del formulario hasta que existan las columnas.
"""

from __future__ import annotations

from django.db import connection

from inmobiliaria.models import FormatoAceptacion

FORMATO_CREDITO_EXTRA_FIELDS = (
    "prima_1_fecha",
    "prima_2_fecha",
    "observaciones_financiamiento",
)

FORMATO_TIPO_FINANCIAMIENTO_FIELD = "tipo_financiamiento"

FORMATO_ADJUNTOS_FIELDS = (
    "dui_cliente_archivo",
    "formato_aceptacion_fisico",
    "boucher_pago_reserva",
)


def _formato_column_names_lower() -> set[str] | None:
    table = FormatoAceptacion._meta.db_table
    try:
        with connection.cursor() as cursor:
            desc = connection.introspection.get_table_description(cursor, table)
        return {(getattr(row, "name", "") or "").lower() for row in desc}
    except Exception:
        return None


def formato_aceptacion_promesa_column_ready() -> bool:
    """True si existe `promesa_venta_escaneada` (migración 0024+)."""
    names = _formato_column_names_lower()
    if names is None:
        return True
    return "promesa_venta_escaneada" in names


def formato_aceptacion_compraventa_column_ready() -> bool:
    """True si existe `contrato_compraventa_escaneado` (migración 0048+)."""
    names = _formato_column_names_lower()
    if names is None:
        return True
    return "contrato_compraventa_escaneado" in names


def formato_aceptacion_credito_extra_columns_ready() -> bool:
    """True si existen columnas de migración 0026 (fechas de prima + observaciones)."""
    names = _formato_column_names_lower()
    if names is None:
        return True
    return "prima_1_fecha" in names


def formato_aceptacion_tipo_financiamiento_column_ready() -> bool:
    """True si existe `tipo_financiamiento` (migración 0040)."""
    names = _formato_column_names_lower()
    if names is None:
        return True
    return "tipo_financiamiento" in names


def formato_aceptacion_adjuntos_columns_ready() -> bool:
    """True si existen columnas de migración 0039 (DUI, físico, boucher)."""
    names = _formato_column_names_lower()
    if names is None:
        return True
    return "dui_cliente_archivo" in names


def formato_aceptacion_defer_missing_columns(qs):
    """Aplica defer a columnas ausentes para que listados y detalle no rompan el SELECT."""
    if not formato_aceptacion_promesa_column_ready():
        qs = qs.defer("promesa_venta_escaneada")
    if not formato_aceptacion_compraventa_column_ready():
        qs = qs.defer("contrato_compraventa_escaneado")
    if not formato_aceptacion_credito_extra_columns_ready():
        qs = qs.defer(*FORMATO_CREDITO_EXTRA_FIELDS)
    if not formato_aceptacion_tipo_financiamiento_column_ready():
        qs = qs.defer(FORMATO_TIPO_FINANCIAMIENTO_FIELD)
    if not formato_aceptacion_adjuntos_columns_ready():
        qs = qs.defer(*FORMATO_ADJUNTOS_FIELDS)
    return qs
