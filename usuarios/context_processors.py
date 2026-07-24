from inmobiliaria.contratos_acceso import (
    aplica_restriccion_contratos_por_vendedor,
    vendedor_catalogo_activo_vinculado,
)
from inmobiliaria.vendedor_acceso import es_vendedor_restringido

from .roles import (
    codigo_rol,
    es_superusuario_o_admin_app,
    obtener_perfil,
    puede_gestionar_usuarios,
    puede_gestionar_vendedores,
    puede_validar_abonos,
)


def perfil_app(request):
    if not request.user.is_authenticated:
        return {
            "perfil_app_ctx": None,
            "puede_gestionar_usuarios_app": False,
            "puede_gestionar_vendedores_app": False,
            "puede_validar_abonos_app": False,
            "puede_ver_historial_auditoria": False,
            "rol_app_codigo": None,
            "vendedor_catalogo_vinculado_ctx": None,
            "contratos_restriccion_vendedor": False,
            "es_vendedor_restringido": False,
        }
    vc = vendedor_catalogo_activo_vinculado(request.user)
    return {
        "perfil_app_ctx": obtener_perfil(request.user),
        "puede_gestionar_usuarios_app": puede_gestionar_usuarios(request.user),
        "puede_gestionar_vendedores_app": puede_gestionar_vendedores(request.user),
        "puede_validar_abonos_app": puede_validar_abonos(request.user),
        "puede_ver_historial_auditoria": es_superusuario_o_admin_app(request.user),
        "rol_app_codigo": codigo_rol(request.user),
        "vendedor_catalogo_vinculado_ctx": vc,
        "contratos_restriccion_vendedor": aplica_restriccion_contratos_por_vendedor(
            request.user
        ),
        "es_vendedor_restringido": es_vendedor_restringido(request.user),
    }
