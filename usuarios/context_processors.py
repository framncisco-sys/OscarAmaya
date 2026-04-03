from .roles import (
    codigo_rol,
    es_superusuario_o_admin_app,
    obtener_perfil,
    puede_gestionar_usuarios,
    puede_gestionar_vendedores,
)


def perfil_app(request):
    if not request.user.is_authenticated:
        return {
            "perfil_app_ctx": None,
            "puede_gestionar_usuarios_app": False,
            "puede_gestionar_vendedores_app": False,
            "puede_ver_historial_auditoria": False,
            "rol_app_codigo": None,
        }
    return {
        "perfil_app_ctx": obtener_perfil(request.user),
        "puede_gestionar_usuarios_app": puede_gestionar_usuarios(request.user),
        "puede_gestionar_vendedores_app": puede_gestionar_vendedores(request.user),
        "puede_ver_historial_auditoria": es_superusuario_o_admin_app(request.user),
        "rol_app_codigo": codigo_rol(request.user),
    }
