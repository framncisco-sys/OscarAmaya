"""Reglas de visibilidad de contratos para usuarios con vínculo al catálogo Vendedor."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from inmobiliaria.models import Contrato, Vendedor
from usuarios.roles import obtener_perfil


def usuario_ve_todos_los_contratos(user) -> bool:
    """Superusuario, administrador, gerencia o usuario sin perfil (compatibilidad) ven el universo completo."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    p = obtener_perfil(user)
    if p is None:
        return True
    if not p.activo_en_app:
        return True
    return p.rol in (p.Rol.ADMINISTRADOR, p.Rol.GERENCIA)


def vendedor_catalogo_activo_vinculado(user):
    """Registro en catálogo Vendedor con `usuario_vinculo` = este usuario y activo."""
    if not user or not user.is_authenticated:
        return None
    return (
        Vendedor.objects.filter(usuario_vinculo_id=user.pk, activo=True)
        .order_by("id")
        .first()
    )


def aplica_restriccion_contratos_por_vendedor(user) -> bool:
    """True si este usuario solo debe ver contratos donde figura como vendedor."""
    from inmobiliaria.vendedor_acceso import es_vendedor_restringido

    return es_vendedor_restringido(user)


def filtrar_contratos_queryset_por_vendedor(qs, user):
    """Restringe el queryset a contratos del catálogo vinculado o con `contrato.vendedor` = usuario."""
    if not aplica_restriccion_contratos_por_vendedor(user):
        return qs
    v = vendedor_catalogo_activo_vinculado(user)
    if v is not None:
        return qs.filter(Q(vendedor_perfil_id=v.pk) | Q(vendedor_id=user.pk))
    # Rol Ventas sin catálogo: solo contratos donde el usuario figura como vendedor interno.
    return qs.filter(vendedor_id=user.pk)


def usuario_puede_ver_contrato(user, contrato: Contrato) -> bool:
    if not aplica_restriccion_contratos_por_vendedor(user):
        return True
    v = vendedor_catalogo_activo_vinculado(user)
    if v is not None:
        return contrato.vendedor_perfil_id == v.pk or contrato.vendedor_id == user.pk
    return contrato.vendedor_id == user.pk


def filtrar_pagos_queryset_por_vendedor(qs, user):
    """Limita pagos a contratos visibles para el usuario (misma regla que la lista de contratos)."""
    allowed = filtrar_contratos_queryset_por_vendedor(Contrato.objects.all(), user)
    return qs.filter(contrato__in=allowed)


def totales_comision_contratos(qs):
    """
    Recorre el queryset (idealmente .only(...) ligero) y acumula comisiones calculables.
    Retorna (suma_usd, contratos_con_comisión_definida, total_contratos).
    """
    total = Decimal("0")
    con_monto = 0
    n = 0
    for c in qs.iterator(chunk_size=400):
        n += 1
        m = c.monto_comision_efectivo()
        if m is not None:
            total += m
            con_monto += 1
    return total, con_monto, n
