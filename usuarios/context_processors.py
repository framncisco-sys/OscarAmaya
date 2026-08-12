from inmobiliaria.contratos_acceso import (
    aplica_restriccion_contratos_por_vendedor,
    vendedor_catalogo_activo_vinculado,
)
from inmobiliaria.vendedor_acceso import es_vendedor_restringido

from .roles import (
    codigo_empresa,
    codigo_rol,
    es_superusuario_o_admin_app,
    obtener_perfil,
    puede_aprobar_precio_formato,
    puede_cambiar_empresa,
    puede_gestionar_usuarios,
    puede_gestionar_vendedores,
    puede_validar_abonos,
    puede_ver_historial_auditoria,
    puede_ver_reportes_contables,
)


def perfil_app(request):
    if not request.user.is_authenticated:
        return {
            "perfil_app_ctx": None,
            "puede_gestionar_usuarios_app": False,
            "puede_gestionar_vendedores_app": False,
            "puede_validar_abonos_app": False,
            "puede_ver_reportes_contables_app": False,
            "puede_aprobar_precio_formato_app": False,
            "puede_ver_historial_auditoria": False,
            "puede_cambiar_empresa": False,
            "empresa_app_codigo": None,
            "empresa_asignada_label": None,
            "empresa_asignada_marca": None,
            "rol_app_codigo": None,
            "vendedor_catalogo_vinculado_ctx": None,
            "contratos_restriccion_vendedor": False,
            "es_vendedor_restringido": False,
        }
    from core.marcas import get_marca

    vc = vendedor_catalogo_activo_vinculado(request.user)
    emp_cod = codigo_empresa(request.user)
    marca_asig = None
    label = None
    if emp_cod == "ambas":
        label = "Ambas empresas"
    else:
        marca_asig = get_marca(emp_cod)
        if marca_asig:
            label = marca_asig.get("nombre")
        else:
            p = obtener_perfil(request.user)
            label = p.get_empresa_display() if p else emp_cod
    return {
        "perfil_app_ctx": obtener_perfil(request.user),
        "puede_gestionar_usuarios_app": puede_gestionar_usuarios(request.user),
        "puede_gestionar_vendedores_app": puede_gestionar_vendedores(request.user),
        "puede_validar_abonos_app": puede_validar_abonos(request.user),
        "puede_ver_reportes_contables_app": puede_ver_reportes_contables(request.user),
        "puede_aprobar_precio_formato_app": puede_aprobar_precio_formato(request.user),
        "puede_ver_historial_auditoria": puede_ver_historial_auditoria(request.user),
        "puede_cambiar_empresa": puede_cambiar_empresa(request.user),
        "empresa_app_codigo": emp_cod,
        "empresa_asignada_label": label,
        "empresa_asignada_marca": marca_asig,
        "rol_app_codigo": codigo_rol(request.user),
        "vendedor_catalogo_vinculado_ctx": vc,
        "contratos_restriccion_vendedor": aplica_restriccion_contratos_por_vendedor(
            request.user
        ),
        "es_vendedor_restringido": es_vendedor_restringido(request.user),
    }
