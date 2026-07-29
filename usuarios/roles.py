"""Helpers de autorización por rol de app (PerfilUsuario)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.marcas import MARCAS, SLUG_BIENES_RAICES, SLUG_DESARROLLOS, get_marca

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from usuarios.models import PerfilUsuario


def obtener_perfil(user: AbstractUser | None) -> PerfilUsuario | None:
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "perfil_app", None)


def codigo_rol(user: AbstractUser | None) -> str | None:
    p = obtener_perfil(user)
    return p.rol if p else None


def es_superusuario_o_admin_app(user: AbstractUser | None) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    return bool(p and p.rol == p.Rol.ADMINISTRADOR)


def es_gerencia_app(user: AbstractUser | None) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return False
    p = obtener_perfil(user)
    return bool(p and p.activo_en_app and p.rol == p.Rol.GERENCIA)


def codigo_empresa(user: AbstractUser | None) -> str:
    """
    Empresa asignada al perfil.
    Superusuario / administrador → siempre «ambas».
    Sin perfil → «ambas» (compatibilidad).
    """
    if not user or not user.is_authenticated:
        return "ambas"
    if user.is_superuser:
        return "ambas"
    p = obtener_perfil(user)
    if p is None:
        return "ambas"
    if p.rol == p.Rol.ADMINISTRADOR:
        return "ambas"
    return p.empresa or "ambas"


def puede_acceder_marca(user: AbstractUser | None, slug: str | None) -> bool:
    if not slug or slug not in MARCAS:
        return False
    emp = codigo_empresa(user)
    if emp == "ambas":
        return True
    return emp == slug


def marcas_permitidas(user: AbstractUser | None) -> list[dict[str, Any]]:
    emp = codigo_empresa(user)
    if emp == "ambas":
        return list(MARCAS.values())
    marca = get_marca(emp)
    return [marca] if marca else []


def slug_unica_permitida(user: AbstractUser | None) -> str | None:
    """Si el usuario solo puede una empresa, devuelve su slug; si ambas, None."""
    emp = codigo_empresa(user)
    if emp in (SLUG_BIENES_RAICES, SLUG_DESARROLLOS):
        return emp
    return None


def puede_cambiar_empresa(user: AbstractUser | None) -> bool:
    return codigo_empresa(user) == "ambas"


def puede_ver_historial_auditoria(user: AbstractUser | None) -> bool:
    """Administradores (ambas) y gerencia (solo su empresa)."""
    if es_superusuario_o_admin_app(user):
        return True
    return es_gerencia_app(user)


def slug_filtro_auditoria(user: AbstractUser | None) -> str | None:
    """
    None = ve todas las marcas (admin).
    Slug = solo esa marca (gerencia u otros con empresa fija).
    """
    if es_superusuario_o_admin_app(user):
        return None
    return slug_unica_permitida(user)


def puede_gestionar_vendedores(user: AbstractUser | None) -> bool:
    """Alta/edición/baja del catálogo de vendedores y comisiones (no el vendedor de campo)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    if not p or not p.activo_en_app:
        return False
    return p.rol in (
        p.Rol.ADMINISTRADOR,
        p.Rol.GERENCIA,
    )


def puede_validar_abonos(user: AbstractUser | None) -> bool:
    """Confirmar en cuenta reserva, prima, cuotas y abono a capital antes de emitir recibo."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    if not p or not p.activo_en_app:
        return False
    return p.rol in (p.Rol.ADMINISTRADOR, p.Rol.GERENCIA)


def puede_gestionar_usuarios(user: AbstractUser | None) -> bool:
    """Crear/editar usuarios y perfiles en /app/usuarios/."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    if not p or not p.activo_en_app:
        return False
    return p.rol in (p.Rol.ADMINISTRADOR, p.Rol.GERENCIA)


def puede_acceder_app(user: AbstractUser | None) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    if p is None:
        return True
    return p.activo_en_app


def salta_reautenticacion_sensible(user: AbstractUser | None) -> bool:
    """Quién no debe pasar por confirmación de contraseña al editar/eliminar (además de superusuario)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    if not p or not p.activo_en_app:
        return False
    return p.rol in (p.Rol.ADMINISTRADOR, p.Rol.GERENCIA)


def descripcion_roles_para_manual() -> list[tuple[str, str]]:
    """Texto de ayuda en plantillas (documentación de negocio)."""
    return [
        (
            "Administrador de sistema",
            "Acceso a ambas empresas, gestión de usuarios, historial completo y sin paso extra de contraseña al editar. "
            "Ideal para TI o responsable del sistema.",
        ),
        (
            "Gerencia",
            "Solo ve y gestiona la empresa a la que está asignada. Puede gestionar usuarios de su empresa, "
            "validar abonos y ver el historial de actividad de su empresa.",
        ),
        (
            "Ventas / comercial",
            "Acceso solo al flujo de venta de su empresa: formato de aceptación, contrato, reserva, prima/promesa, "
            "recibos a plazos y listado de sus contratos. Debe tener usuario vinculado en el catálogo Vendedores.",
        ),
        (
            "Cartera / finanzas",
            "Pagos, cuotas, exportaciones contables de su empresa; confirmación de contraseña al guardar cambios.",
        ),
        (
            "Proyectos, lotes y mapa",
            "Proyectos, polígonos, inmuebles y mapa interactivo de su empresa.",
        ),
        (
            "Marketing / CRM",
            "Orientado a leads y visitas cuando use el módulo CRM de su empresa.",
        ),
        (
            "Solo consulta",
            "Puede ver listados y detalles de su empresa; cualquier edición requiere confirmación de contraseña.",
        ),
    ]
