"""Acceso limitado del vendedor al flujo de venta (formato → pagos)."""

from __future__ import annotations

from inmobiliaria.contratos_acceso import (
    usuario_ve_todos_los_contratos,
    vendedor_catalogo_activo_vinculado,
)
from usuarios.roles import obtener_perfil


# Rutas del namespace `app` permitidas para el vendedor (flujo de venta completo).
RUTAS_VENDEDOR_FLUJO: frozenset[str] = frozenset(
    {
        "index",
        "sensitive_reauth",
        # 1. Formato de aceptación
        "formato_aceptacion",
        "formato_aceptacion_nuevo",
        "formato_aceptacion_list",
        "formato_aceptacion_edit",
        "formato_aceptacion_pdf",
        "formato_aceptacion_delete",
        "formato_firma_preview",
        "formato_aceptacion_adjunto_descargar",
        "formato_aceptacion_promesa_subir",
        "formato_aceptacion_promesa_descargar",
        "formato_aceptacion_compraventa_subir",
        "formato_aceptacion_compraventa_descargar",
        "formato_superuser_gate",
        # 2–6. Pagos (contado, reserva, prima, cuotas) — oficiales tras validación gerencia
        "pago_list",
        "pago_create",
        "pago_update",
        "pago_delete",
        "export_pagos_csv",
        # Planes de pagos y estado de cuenta (borrador hasta validación)
        "contrato_list",
        "contrato_create",
        "contrato_update",
        "contrato_estado_cuenta",
        "contrato_estado_cuenta_pdf",
        "estado_cuenta_hub",
        "contrato_credito_cliente_json",
        # Documentos / promesa ligados al flujo
        "docs_list",
        "docs_cliente",
        "doc_download",
        "emitir_promesa",
        "emitir_recibo",
        "recibo_whatsapp_pago",
        # Consulta en vivo del estado del lote (formato, sin guardar)
        "api_inmueble_estado",
    }
)


def es_vendedor_restringido(user) -> bool:
    """
    Vendedor con acceso al sistema: solo ve el flujo de venta.
    - Tiene registro en catálogo Vendedor (usuario vínculo), o
    - Rol «Ventas / comercial»,
    y no es admin/gerencia/superusuario.
    """
    if usuario_ve_todos_los_contratos(user):
        return False
    if vendedor_catalogo_activo_vinculado(user) is not None:
        return True
    p = obtener_perfil(user)
    return bool(p and p.activo_en_app and p.rol == p.Rol.VENTAS)


def ruta_permitida_vendedor(url_name: str | None) -> bool:
    if not url_name:
        return False
    return url_name in RUTAS_VENDEDOR_FLUJO


def redirigir_vendedor_si_fuera_de_flujo(request):
    """
    Si el usuario es vendedor restringido y la ruta `app` no está en el allowlist,
    redirige al inicio del flujo. Devuelve None si puede continuar.
    """
    from django.contrib import messages
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None
    if not es_vendedor_restringido(request.user):
        return None
    match = getattr(request, "resolver_match", None)
    if not match or getattr(match, "namespace", None) != "app":
        return None
    if ruta_permitida_vendedor(getattr(match, "url_name", None)):
        return None
    messages.warning(
        request,
        "Su acceso de asesor de ventas solo incluye el flujo de venta: "
        "formato, pagos, planes, estado de cuenta y documentos "
        "(todo queda pendiente hasta validación de admin/gerencia).",
    )
    return HttpResponseRedirect(reverse("app:index"))
