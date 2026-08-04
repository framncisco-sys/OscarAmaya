"""Marcas comerciales del portal de entrada (sesión)."""

from __future__ import annotations

from typing import Any

SESSION_KEY = "pbr_marca"

SLUG_BIENES_RAICES = "bienes-raices"
SLUG_DESARROLLOS = "desarrollos"

MARCAS: dict[str, dict[str, Any]] = {
    SLUG_BIENES_RAICES: {
        "slug": SLUG_BIENES_RAICES,
        "nombre": "Paredes Bienes Raíces",
        "subtitulo": "Arrendamientos, intermediación y gestión inmobiliaria",
        "logo": "logo_paredes_bienes_raices.png",
        "eyebrow": "Bienes raíces",
        # Sistema aparte: menú Clientes / Asesores de ventas / Inmuebles / Asesores
        "sistema": "bienes_raices",
        "muestra_gestion": False,
    },
    SLUG_DESARROLLOS: {
        "slug": SLUG_DESARROLLOS,
        "nombre": "Paredes Desarrollos Inmobiliarios",
        "subtitulo": "Proyectos, lotificaciones, ventas y cartera",
        "logo": "logo_paredes_desarrollos.png",
        "eyebrow": "Desarrollos inmobiliarios",
        "sistema": "desarrollos",
        "muestra_gestion": True,
    },
}


def get_marca(slug: str | None) -> dict[str, Any] | None:
    if not slug:
        return None
    return MARCAS.get(slug)


def marca_from_session(request) -> dict[str, Any] | None:
    return get_marca(request.session.get(SESSION_KEY))


def set_marca(request, slug: str) -> dict[str, Any] | None:
    marca = get_marca(slug)
    if marca:
        request.session[SESSION_KEY] = slug
    return marca


def es_bienes_raices(marca: dict[str, Any] | None) -> bool:
    return bool(marca and marca.get("slug") == SLUG_BIENES_RAICES)


def es_desarrollos(marca: dict[str, Any] | None) -> bool:
    return bool(marca and marca.get("slug") == SLUG_DESARROLLOS)


# Rutas del namespace `app` exclusivas de Bienes Raíces (alquileres / venta casas-inmuebles).
RUTAS_SOLO_BIENES_RAICES: frozenset[str] = frozenset(
    {
        "inmuebles_alquiler_hub",
        "inmuebles_venta_hub",
        "inmueble_casa_list",
        "inmueble_casa_create",
        "inmueble_casa_galeria",
        "inmueble_imagen_eliminar",
        "inmueble_imagen_portada",
        "inmueble_imagen_descripcion",
        "arrendamiento_locales_list",
        "arrendamiento_casas_list",
        "local_alquiler_create",
        "local_alquiler_ficha",
        "casa_alquiler_create",
        "casa_alquiler_ficha",
        "recibo_comision_hub",
        "recibo_comision_casa_venta",
        "recibo_comision_alquiler_local",
        "recibo_comision_alquiler_casa",
        "recibo_comision_alquiler_local_legacy",
        "emitir_recibo_comision_alquiler",
        "asesor_alquiler_list",
        "asesor_alquiler_create",
        "asesor_alquiler_update",
        "asesor_alquiler_delete",
        "cliente_list",
        "cliente_create",
        "cliente_update",
        "cliente_delete",
        "cliente_reporte_pdf",
        "cliente_estado_cuenta_pdf",
        "cliente_documento_delete",
    }
)


def ruta_solo_bienes_raices(url_name: str | None) -> bool:
    return bool(url_name and url_name in RUTAS_SOLO_BIENES_RAICES)

