"""Helpers de autorización por rol de app (PerfilUsuario)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model

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


def puede_gestionar_vendedores(user: AbstractUser | None) -> bool:
    """Alta/edición/baja del catálogo de vendedores y comisiones."""
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
        p.Rol.VENTAS,
    )


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
            "Acceso total en la app, gestión de usuarios y sin paso extra de contraseña al editar. "
            "Ideal para TI o responsable del sistema.",
        ),
        (
            "Gerencia",
            "Puede gestionar usuarios, ve todo el negocio y no pide contraseña de confirmación al editar.",
        ),
        (
            "Ventas / comercial",
            "Clientes, contratos, seguimiento comercial; debe confirmar contraseña para cambios sensibles.",
        ),
        (
            "Cartera / finanzas",
            "Pagos, cuotas, exportaciones contables; confirmación de contraseña al guardar cambios.",
        ),
        (
            "Proyectos, lotes y mapa",
            "Proyectos, polígonos, inmuebles y mapa interactivo.",
        ),
        (
            "Marketing / CRM",
            "Orientado a leads y visitas cuando use el módulo CRM.",
        ),
        (
            "Solo consulta",
            "Puede ver listados y detalles; cualquier edición requiere confirmación de contraseña.",
        ),
    ]
