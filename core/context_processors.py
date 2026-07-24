"""Context processors globales del núcleo."""

from __future__ import annotations

from inmobiliaria.contratos_acceso import aplica_restriccion_contratos_por_vendedor
from inmobiliaria.vendedor_acceso import es_vendedor_restringido

from core.dashboard_data import build_sidebar_stats
from core.marcas import (
    MARCAS,
    SLUG_BIENES_RAICES,
    es_bienes_raices,
    es_desarrollos,
    marca_from_session,
)
from core.sidebar_nav import build_sidebar_nav
from usuarios.roles import es_superusuario_o_admin_app, puede_gestionar_usuarios, puede_gestionar_vendedores


def _es_ruta_catalogo(request) -> bool:
    match = getattr(request, "resolver_match", None)
    return bool(match and getattr(match, "namespace", None) == "catalogo")


def sidebar_context(request):
    marca_sesion = marca_from_session(request)
    # El catálogo público pertenece solo a Paredes Bienes Raíces (marca fija).
    if _es_ruta_catalogo(request):
        marca = MARCAS[SLUG_BIENES_RAICES]
    else:
        marca = marca_sesion or MARCAS["desarrollos"]

    if not request.user.is_authenticated:
        return {
            "sidebar_stats": None,
            "sidebar_nav": None,
            "marca_portal": marca,
            "es_sistema_bienes_raices": False,
            "es_sistema_desarrollos": False,
            "muestra_sidebar_gestion": False,
            "es_vendedor_restringido": False,
        }

    url_name = ""
    if request.resolver_match:
        url_name = request.resolver_match.url_name or ""

    restriccion = aplica_restriccion_contratos_por_vendedor(request.user)
    vend_restringido = es_vendedor_restringido(request.user)
    return {
        "marca_portal": marca,
        "es_sistema_bienes_raices": es_bienes_raices(marca_sesion) and not vend_restringido,
        "es_sistema_desarrollos": es_desarrollos(marca_sesion) and not vend_restringido,
        "muestra_sidebar_gestion": bool(
            marca_sesion and marca_sesion.get("muestra_gestion") and not vend_restringido
        ),
        "es_vendedor_restringido": vend_restringido,
        "sidebar_nav": build_sidebar_nav(url_name),
        "sidebar_stats": build_sidebar_stats(
            user=request.user,
            contratos_restringidos=restriccion,
            incluir_admin=es_superusuario_o_admin_app(request.user),
            incluir_usuarios=puede_gestionar_usuarios(request.user),
            incluir_vendedores=puede_gestionar_vendedores(request.user),
        ),
    }
