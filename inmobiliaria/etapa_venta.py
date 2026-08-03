"""Etapas de venta generales + precio por lote según contador del proyecto.

Reglas de negocio:
- Rangos de etapa: configuración general (ParametroEtapaVenta).
- Contador: lotes VENDIDO + RESERVADO del proyecto.
- Precio: cada lote tiene precio_preventa / promocional / pos_preventa.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Q

if TYPE_CHECKING:
    from inmobiliaria.models import Inmueble, ParametroEtapaVenta, Proyecto

ETAPA_PREVENTA = "PREVENTA"
ETAPA_PROMOCIONAL = "PROMOCIONAL"
ETAPA_POS_PREVENTA = "POS_PREVENTA"

ETAPA_LABELS = {
    ETAPA_PREVENTA: "Preventa",
    ETAPA_PROMOCIONAL: "Promocional",
    ETAPA_POS_PREVENTA: "Pos preventa",
}


def get_parametro_etapa() -> ParametroEtapaVenta:
    from inmobiliaria.models import ParametroEtapaVenta

    obj = ParametroEtapaVenta.objects.order_by("pk").first()
    if obj is None:
        obj = ParametroEtapaVenta.objects.create()
    return obj


def contar_lotes_comprometidos(proyecto: Proyecto | int) -> int:
    """Lotes del proyecto en RESERVADO o VENDIDO (avance comercial)."""
    from inmobiliaria.models import Inmueble

    pid = proyecto.pk if hasattr(proyecto, "pk") else int(proyecto)
    return (
        Inmueble.objects.filter(proyecto_id=pid, tipo=Inmueble.Tipo.LOTE)
        .filter(Q(estado=Inmueble.Estado.VENDIDO) | Q(estado=Inmueble.Estado.RESERVADO))
        .count()
    )


def etapa_codigo_para_contador(n: int, param: ParametroEtapaVenta | None = None) -> str:
    p = param or get_parametro_etapa()
    # n = cantidad ya comprometida; el siguiente lote sería n+1 en orden de venta.
    # La etapa se basa en cuántos ya están comprometidos (0 → preventa).
    if n < p.hasta_preventa:
        return ETAPA_PREVENTA
    if n < p.hasta_promocional:
        return ETAPA_PROMOCIONAL
    return ETAPA_POS_PREVENTA


def etapa_para_proyecto(proyecto: Proyecto | int) -> dict:
    """Etapa vigente del proyecto según su contador."""
    p = get_parametro_etapa()
    n = contar_lotes_comprometidos(proyecto)
    codigo = etapa_codigo_para_contador(n, p)
    return {
        "codigo": codigo,
        "label": ETAPA_LABELS.get(codigo, codigo),
        "comprometidos": n,
        "hasta_preventa": p.hasta_preventa,
        "hasta_promocional": p.hasta_promocional,
        "hasta_pos_preventa": p.hasta_pos_preventa,
        "rango_label": _rango_label(codigo, p),
    }


def _rango_label(codigo: str, p: ParametroEtapaVenta) -> str:
    if codigo == ETAPA_PREVENTA:
        return f"0–{p.hasta_preventa} lotes"
    if codigo == ETAPA_PROMOCIONAL:
        return f"{p.hasta_preventa + 1}–{p.hasta_promocional} lotes"
    return f"{p.hasta_promocional + 1}–{p.hasta_pos_preventa} lotes"


def precio_lote_en_etapa(inmueble: Inmueble, codigo_etapa: str | None = None) -> Decimal | None:
    """Precio del lote para la etapa dada (o la del proyecto del lote)."""
    if codigo_etapa is None:
        codigo_etapa = etapa_para_proyecto(inmueble.proyecto_id)["codigo"]

    mapping = {
        ETAPA_PREVENTA: inmueble.precio_preventa,
        ETAPA_PROMOCIONAL: inmueble.precio_promocional,
        ETAPA_POS_PREVENTA: inmueble.precio_pos_preventa,
    }
    precio = mapping.get(codigo_etapa)
    if precio is not None:
        return Decimal(precio).quantize(Decimal("0.01"))
    # Fallback: precio_lista histórico
    if inmueble.precio_lista is not None:
        return Decimal(inmueble.precio_lista).quantize(Decimal("0.01"))
    return None


def sync_precio_lista(inmueble: Inmueble, save: bool = False) -> Decimal | None:
    """Actualiza precio_lista al precio de la etapa actual del proyecto."""
    precio = precio_lote_en_etapa(inmueble)
    if precio is None:
        return None
    if inmueble.precio_lista != precio:
        inmueble.precio_lista = precio
        if save and inmueble.pk:
            inmueble.save(update_fields=["precio_lista"])
    return precio


def decimales_iguales(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return Decimal(a).quantize(Decimal("0.01")) == Decimal(b).quantize(Decimal("0.01"))
