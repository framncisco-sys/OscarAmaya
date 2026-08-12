"""Estado activo del menú lateral según la vista actual."""

from __future__ import annotations

_CLIENTE = frozenset(
    {
        "cliente_list",
        "cliente_create",
        "cliente_update",
        "cliente_delete",
        "cliente_reporte_pdf",
        "cliente_documento_delete",
        "cliente_estado_cuenta_pdf",
    }
)

_LOCAL = frozenset(
    {
        "arrendamiento_locales_list",
        "local_alquiler_ficha",
        "local_alquiler_create",
    }
)

_CASA_RENT = frozenset(
    {
        "arrendamiento_casas_list",
        "casa_alquiler_ficha",
        "casa_alquiler_create",
    }
)

_CASA_VENTA = frozenset(
    {
        "inmueble_casa_list",
        "inmueble_casa_create",
        "inmueble_casa_galeria",
        "inmueble_imagen_eliminar",
        "inmueble_imagen_portada",
        "inmueble_imagen_descripcion",
    }
)

_LOTE_VENTA = frozenset(
    {
        "inmueble_list",
        "inmueble_create",
        "inmueble_update",
        "inmueble_delete",
    }
)

_COMISION_ALQUILER = frozenset(
    {
        "recibo_comision_alquiler_local",
        "recibo_comision_alquiler_casa",
        "emitir_recibo_comision_alquiler",
    }
)

_COMISION_VENTA = frozenset(
    {
        "recibo_comision_hub",
        "recibo_comision_casa_venta",
        "emitir_recibo_comision",
    }
)

_VENDEDORES = frozenset(
    {
        "vendedor_list",
        "vendedor_create",
        "vendedor_update",
        "vendedor_delete",
    }
)

_ASESORES_ALQUILER = frozenset(
    {
        "asesor_alquiler_list",
        "asesor_alquiler_create",
        "asesor_alquiler_update",
        "asesor_alquiler_delete",
    }
)

_INMUEBLES_ALQUILER = frozenset({"inmuebles_alquiler_hub"}) | _LOCAL | _CASA_RENT | _COMISION_ALQUILER
_INMUEBLES_VENTA = frozenset({"inmuebles_venta_hub"}) | _CASA_VENTA | _LOTE_VENTA | _COMISION_VENTA
_INMUEBLES = _INMUEBLES_ALQUILER | _INMUEBLES_VENTA

_PROYECTOS = frozenset(
    {
        "proyecto_list",
        "proyecto_create",
        "proyecto_update",
        "proyecto_delete",
        "poligono_list",
        "poligono_create",
        "poligono_update",
        "poligono_delete",
        "mapa_editor",
        "api_mapa_proyecto",
        "api_mapa_guardar_lote",
        "mapa_catastral",
        "api_mapa_catastral",
        "api_mapa_catastral_guardar",
    }
)

_CARTERA = frozenset(
    {
        "contrato_list",
        "contrato_create",
        "contrato_update",
        "contrato_delete",
        "contrato_estado_cuenta",
        "contrato_estado_cuenta_pdf",
        "estado_cuenta_hub",
        "contrato_credito_cliente_json",
        "pago_list",
        "pago_create",
        "pago_update",
        "pago_delete",
        "export_pagos_csv",
        "flujo_venta_validar_list",
        "flujo_venta_validar_formato",
        "flujo_venta_validar_contrato",
        "aviso_cobro_list",
        "parametro_mora_list",
        "parametro_mora_create",
        "parametro_mora_update",
        "parametro_mora_delete",
    }
)

_DOCS = frozenset(
    {
        "formato_aceptacion",
        "formato_aceptacion_nuevo",
        "formato_aceptacion_list",
        "formato_aceptacion_edit",
        "formato_aceptacion_pdf",
        "formato_aceptacion_delete",
        "formato_firma_preview",
        "formato_aceptacion_adjunto_descargar",
        "formato_superuser_gate",
        "formato_aceptacion_promesa_subir",
        "formato_aceptacion_promesa_descargar",
        "formato_precio_pendiente_list",
        "formato_precio_aprobar",
        "formato_precio_rechazar",
        "docs_list",
        "docs_cliente",
        "doc_download",
        "emitir_promesa",
        "emitir_recibo",
    }
)

_ADMIN = frozenset(
    {
        "usuario_list",
        "usuario_create",
        "usuario_update",
        "usuario_delete",
        "usuario_roles_manual",
        "audit_log_list",
        "audit_log_detail",
    }
)

_CONTABLE = frozenset(
    {
        "contable_libro_ventas",
        "contable_ingresos_mes",
        "contable_cuentas_por_cobrar",
        "contable_estado_capital_intereses",
    }
)

_GESTION = frozenset({"index"}) | _PROYECTOS | _CARTERA | _DOCS | _ADMIN


def build_sidebar_nav(url_name: str | None, *, pago_concepto: str | None = None) -> dict:
    u = url_name or ""
    concepto = (pago_concepto or "").strip().upper()
    in_set = lambda names: u in names  # noqa: E731
    pago_create = u == "pago_create"
    return {
        "u": u,
        "clientes_active": in_set(_CLIENTE),
        "vendedores_active": in_set(_VENDEDORES),
        "vendedor_list_active": u
        in {
            "vendedor_list",
            "vendedor_update",
            "vendedor_delete",
        },
        "vendedor_create_active": u == "vendedor_create",
        "recibo_comision_vendedor_active": u
        in {
            "recibo_comision_casa_venta",
            "emitir_recibo_comision",
        },
        "asesores_alquiler_active": in_set(_ASESORES_ALQUILER),
        "asesor_alquiler_list_active": u
        in {
            "asesor_alquiler_list",
            "asesor_alquiler_update",
            "asesor_alquiler_delete",
        },
        "asesor_alquiler_create_active": u == "asesor_alquiler_create",
        "inmuebles_active": in_set(_INMUEBLES),
        "inmuebles_alquiler_nav_active": in_set(_INMUEBLES_ALQUILER),
        "inmuebles_venta_nav_active": in_set(_INMUEBLES_VENTA),
        "cliente_active": in_set(_CLIENTE),
        "cliente_list_active": u
        in {
            "cliente_list",
            "cliente_update",
            "cliente_delete",
            "cliente_reporte_pdf",
            "cliente_documento_delete",
            "cliente_estado_cuenta_pdf",
        },
        "cliente_create_active": u == "cliente_create",
        "gestion_active": in_set(_GESTION),
        "contable_active": in_set(_CONTABLE),
        "contable_libro_ventas_active": u == "contable_libro_ventas",
        "contable_ingresos_active": u == "contable_ingresos_mes",
        "contable_cxp_active": u == "contable_cuentas_por_cobrar",
        "contable_capital_active": u == "contable_estado_capital_intereses",
        "open_proyectos": in_set(_PROYECTOS),
        "open_cartera": in_set(_CARTERA),
        "open_docs": in_set(_DOCS),
        "open_admin": in_set(_ADMIN),
        "index_active": u == "index",
        "proyecto_active": u in {"proyecto_list", "proyecto_create", "proyecto_update"},
        "poligono_active": u in {"poligono_list", "poligono_create", "poligono_update"},
        "inmueble_list_active": u
        in {"inmueble_list", "inmueble_create", "inmueble_update", "inmueble_delete"},
        "mapa_editor_active": u in {"mapa_editor", "api_mapa_proyecto", "api_mapa_guardar_lote"},
        "mapa_catastral_active": u
        in {"mapa_catastral", "api_mapa_catastral", "api_mapa_catastral_guardar"},
        "contrato_active": u
        in {
            "contrato_create",
            "contrato_update",
            "contrato_delete",
            "contrato_credito_cliente_json",
        },
        "contrato_list_active": u == "contrato_list",
        "estado_cuenta_active": u
        in {
            "estado_cuenta_hub",
            "cliente_estado_cuenta_pdf",
            "contrato_estado_cuenta_pdf",
            "contrato_estado_cuenta",
        },
        "pago_active": u in {"pago_list", "pago_create", "pago_update", "export_pagos_csv"},
        "pago_list_active": u in {"pago_list", "pago_update", "export_pagos_csv"},
        "pago_reserva_active": pago_create and concepto == "RESERVA",
        "pago_prima_active": pago_create and concepto == "PRIMA",
        "pago_contado_active": pago_create and concepto == "CONTADO",
        "pago_cuota_active": pago_create and concepto == "CUOTA",
        "aviso_cobro_active": u == "aviso_cobro_list",
        "mora_active": u
        in {
            "parametro_mora_list",
            "parametro_mora_create",
            "parametro_mora_update",
        },
        "formato_active": u
        in {
            "formato_aceptacion",
            "formato_aceptacion_nuevo",
            "formato_aceptacion_edit",
            "formato_aceptacion_pdf",
        },
        "formato_list_active": u == "formato_aceptacion_list",
        "precio_formato_active": u
        in {
            "formato_precio_pendiente_list",
            "formato_precio_aprobar",
            "formato_precio_rechazar",
        },
        "flujo_validar_active": u
        in {
            "flujo_venta_validar_list",
            "flujo_venta_validar_formato",
            "flujo_venta_validar_contrato",
        },
        "etapa_venta_active": u == "parametro_etapa_venta",
        "docs_active": u in {"docs_list", "docs_cliente", "doc_download", "emitir_promesa", "emitir_recibo"},
        "usuario_active": u
        in {
            "usuario_list",
            "usuario_create",
            "usuario_update",
            "usuario_delete",
            "usuario_roles_manual",
        },
        "audit_active": u in {"audit_log_list", "audit_log_detail"},
    }
