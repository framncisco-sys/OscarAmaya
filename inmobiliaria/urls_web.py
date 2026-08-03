"""Rutas de la interfaz web minimalista bajo /app/."""

from django.urls import include, path
from django.views.generic import RedirectView

from docs import views_web as docs_views

from . import views_asesor_alquiler, views_recibo_alquiler, views_web as views

app_name = "app"

urlpatterns = [
    path("", views.AppIndexView.as_view(), name="index"),
    path("confirmar-acceso/", views.sensitive_reauth, name="sensitive_reauth"),
    path("inmuebles/alquileres/", views.inmuebles_alquiler_hub, name="inmuebles_alquiler_hub"),
    path("inmuebles/venta/", views.inmuebles_venta_hub, name="inmuebles_venta_hub"),
    path("mapa/", views.MapaEditorView.as_view(), name="mapa_editor"),
    path("mapa/catastral/", views.MapaCatastralView.as_view(), name="mapa_catastral"),
    path("proyectos/", views.ProyectoListView.as_view(), name="proyecto_list"),
    path("proyectos/nuevo/", views.ProyectoCreateView.as_view(), name="proyecto_create"),
    path("proyectos/<int:pk>/editar/", views.ProyectoUpdateView.as_view(), name="proyecto_update"),
    path("proyectos/<int:pk>/eliminar/", views.ProyectoDeleteView.as_view(), name="proyecto_delete"),
    path("poligonos/", views.PoligonoListView.as_view(), name="poligono_list"),
    path("poligonos/nuevo/", views.PoligonoCreateView.as_view(), name="poligono_create"),
    path("poligonos/<int:pk>/editar/", views.PoligonoUpdateView.as_view(), name="poligono_update"),
    path("poligonos/<int:pk>/eliminar/", views.PoligonoDeleteView.as_view(), name="poligono_delete"),
    path(
        "inmuebles/casas/nuevo/",
        views.InmuebleCreateCasaView.as_view(),
        name="inmueble_casa_create",
    ),
    path("inmuebles/casas/", views.InmuebleCasaListView.as_view(), name="inmueble_casa_list"),
    path(
        "inmuebles/arrendamientos/locales/nuevo/",
        views.LocalAlquilerCreateView.as_view(),
        name="local_alquiler_create",
    ),
    path(
        "inmuebles/arrendamientos/locales/",
        views.ArrendamientoLocalesListView.as_view(),
        name="arrendamiento_locales_list",
    ),
    path(
        "inmuebles/arrendamientos/casas/nuevo/",
        views.CasaAlquilerCreateView.as_view(),
        name="casa_alquiler_create",
    ),
    path(
        "inmuebles/arrendamientos/casas/",
        views.ArrendamientoCasasListView.as_view(),
        name="arrendamiento_casas_list",
    ),
    path(
        "inmuebles/recibo-comision-vendedor/",
        views_recibo_alquiler.recibo_comision_hub,
        name="recibo_comision_hub",
    ),
    path(
        "inmuebles/locales/recibo-comision/",
        RedirectView.as_view(
            pattern_name="app:recibo_comision_alquiler_local",
            permanent=False,
        ),
        name="recibo_comision_alquiler_local_legacy",
    ),
    path(
        "inmuebles/casas/recibo-comision/",
        docs_views.recibo_comision_casa_venta_elegir,
        name="recibo_comision_casa_venta",
    ),
    path(
        "inmuebles/arrendamientos/locales/recibo-comision/",
        views_recibo_alquiler.recibo_comision_alquiler_elegir,
        {"segmento": "local"},
        name="recibo_comision_alquiler_local",
    ),
    path(
        "inmuebles/arrendamientos/casas/recibo-comision/",
        views_recibo_alquiler.recibo_comision_alquiler_elegir,
        {"segmento": "casa"},
        name="recibo_comision_alquiler_casa",
    ),
    path(
        "inmuebles/arrendamientos/<int:inmueble_id>/recibo-comision/",
        views_recibo_alquiler.emitir_recibo_comision_alquiler_view,
        name="emitir_recibo_comision_alquiler",
    ),
    path("inmuebles/nuevo/", views.InmuebleCreateLoteView.as_view(), name="inmueble_create"),
    path("inmuebles/", views.InmuebleLoteListView.as_view(), name="inmueble_list"),
    path("inmuebles/<int:pk>/editar/", views.InmuebleUpdateView.as_view(), name="inmueble_update"),
    path(
        "inmuebles/<int:pk>/casa-y-fotos/",
        views.InmuebleCasaGaleriaView.as_view(),
        name="inmueble_casa_galeria",
    ),
    path(
        "inmuebles/<int:pk>/local-alquiler/",
        views.LocalAlquilerFichaView.as_view(),
        name="local_alquiler_ficha",
    ),
    path(
        "inmuebles/<int:pk>/casa-alquiler/",
        views.CasaAlquilerFichaView.as_view(),
        name="casa_alquiler_ficha",
    ),
    path("inmuebles/<int:pk>/eliminar/", views.InmuebleDeleteView.as_view(), name="inmueble_delete"),
    path(
        "inmuebles/<int:inmueble_pk>/imagenes/<int:pk>/eliminar/",
        views.inmueble_imagen_eliminar,
        name="inmueble_imagen_eliminar",
    ),
    path(
        "inmuebles/<int:inmueble_pk>/imagenes/<int:pk>/portada/",
        views.inmueble_imagen_portada,
        name="inmueble_imagen_portada",
    ),
    path(
        "inmuebles/<int:inmueble_pk>/imagenes/<int:pk>/descripcion/",
        views.inmueble_imagen_descripcion,
        name="inmueble_imagen_descripcion",
    ),
    path("clientes/", views.ClienteListView.as_view(), name="cliente_list"),
    path("clientes/nuevo/", views.ClienteCreateView.as_view(), name="cliente_create"),
    path("clientes/<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="cliente_update"),
    path("clientes/<int:pk>/eliminar/", views.ClienteDeleteView.as_view(), name="cliente_delete"),
    path(
        "clientes/<int:pk>/reporte.pdf",
        views.cliente_reporte_pdf,
        name="cliente_reporte_pdf",
    ),
    path(
        "clientes/<int:pk>/estado-cuenta.pdf",
        views.cliente_estado_cuenta_pdf,
        name="cliente_estado_cuenta_pdf",
    ),
    path(
        "clientes/documentos/<int:pk>/eliminar/",
        views.cliente_documento_delete,
        name="cliente_documento_delete",
    ),
    path("vendedores/", views.VendedorListView.as_view(), name="vendedor_list"),
    path("vendedores/nuevo/", views.VendedorCreateView.as_view(), name="vendedor_create"),
    path("vendedores/<int:pk>/editar/", views.VendedorUpdateView.as_view(), name="vendedor_update"),
    path("vendedores/<int:pk>/eliminar/", views.VendedorDeleteView.as_view(), name="vendedor_delete"),
    path("asesores-alquiler/", views_asesor_alquiler.AsesorAlquilerListView.as_view(), name="asesor_alquiler_list"),
    path("asesores-alquiler/nuevo/", views_asesor_alquiler.AsesorAlquilerCreateView.as_view(), name="asesor_alquiler_create"),
    path("asesores-alquiler/<int:pk>/editar/", views_asesor_alquiler.AsesorAlquilerUpdateView.as_view(), name="asesor_alquiler_update"),
    path("asesores-alquiler/<int:pk>/eliminar/", views_asesor_alquiler.AsesorAlquilerDeleteView.as_view(), name="asesor_alquiler_delete"),
    path(
        "estado-cuenta/",
        views.estado_cuenta_hub,
        name="estado_cuenta_hub",
    ),
    path("contratos/", views.ContratoListView.as_view(), name="contrato_list"),
    path("contratos/nuevo/", views.ContratoCreateView.as_view(), name="contrato_create"),
    path(
        "contratos/credito-cliente/<int:cliente_id>/",
        views.contrato_credito_cliente_json,
        name="contrato_credito_cliente_json",
    ),
    path("contratos/<int:pk>/editar/", views.ContratoUpdateView.as_view(), name="contrato_update"),
    path("contratos/<int:pk>/eliminar/", views.ContratoDeleteView.as_view(), name="contrato_delete"),
    path(
        "contratos/<int:pk>/estado-cuenta/",
        views.contrato_estado_cuenta,
        name="contrato_estado_cuenta",
    ),
    path(
        "contratos/<int:pk>/estado-cuenta.pdf",
        views.contrato_estado_cuenta_pdf,
        name="contrato_estado_cuenta_pdf",
    ),
    path(
        "formato-aceptacion/lista/",
        views.FormatoAceptacionListView.as_view(),
        name="formato_aceptacion_list",
    ),
    path(
        "formato-aceptacion/elevar-superusuario/",
        views.formato_superuser_gate,
        name="formato_superuser_gate",
    ),
    path(
        "formato-aceptacion/nuevo/",
        RedirectView.as_view(
            pattern_name="app:formato_aceptacion",
            permanent=False,
        ),
        name="formato_aceptacion_nuevo",
    ),
    path(
        "formato-aceptacion/",
        views.FormatoAceptacionCreateStandaloneView.as_view(),
        name="formato_aceptacion",
    ),
    path(
        "formato-aceptacion/<int:pk>/editar/",
        views.FormatoAceptacionUpdateView.as_view(),
        name="formato_aceptacion_edit",
    ),
    path(
        "formato-aceptacion/<int:pk>/eliminar/",
        views.FormatoAceptacionDeleteView.as_view(),
        name="formato_aceptacion_delete",
    ),
    path(
        "formato-aceptacion/<int:pk>/firma/<slug:tipo>/",
        views.formato_firma_preview,
        name="formato_firma_preview",
    ),
    path(
        "formato-aceptacion/<int:pk>/adjunto/<slug:tipo>/",
        views.formato_aceptacion_adjunto_descargar,
        name="formato_aceptacion_adjunto_descargar",
    ),
    path(
        "formato-aceptacion/<int:pk>.pdf",
        views.formato_aceptacion_pdf,
        name="formato_aceptacion_pdf",
    ),
    path(
        "formato-aceptacion/<int:pk>/promesa/subir/",
        views.formato_aceptacion_promesa_subir,
        name="formato_aceptacion_promesa_subir",
    ),
    path(
        "formato-aceptacion/<int:pk>/promesa/descargar/",
        views.formato_aceptacion_promesa_descargar,
        name="formato_aceptacion_promesa_descargar",
    ),
    path(
        "formato-aceptacion/<int:pk>/compraventa/subir/",
        views.formato_aceptacion_compraventa_subir,
        name="formato_aceptacion_compraventa_subir",
    ),
    path(
        "formato-aceptacion/<int:pk>/compraventa/descargar/",
        views.formato_aceptacion_compraventa_descargar,
        name="formato_aceptacion_compraventa_descargar",
    ),
    path("reportes/pagos.csv", views.export_pagos_csv, name="export_pagos_csv"),
    path("pagos/", views.PagoListView.as_view(), name="pago_list"),
    path("pagos/nuevo/", views.PagoCreateView.as_view(), name="pago_create"),
    path(
        "pagos/<int:pk>/validar-abono/",
        views.pago_validar_abono,
        name="pago_validar_abono",
    ),
    path(
        "pagos/<int:pk>/rechazar-abono/",
        views.pago_rechazar_abono,
        name="pago_rechazar_abono",
    ),
    path(
        "formatos-aceptacion/precios-pendientes/",
        views.formato_precio_pendiente_list,
        name="formato_precio_pendiente_list",
    ),
    path(
        "formatos-aceptacion/<int:pk>/aprobar-precio/",
        views.formato_precio_aprobar,
        name="formato_precio_aprobar",
    ),
    path(
        "formatos-aceptacion/<int:pk>/rechazar-precio/",
        views.formato_precio_rechazar,
        name="formato_precio_rechazar",
    ),
    path(
        "parametros-etapa-venta/",
        views.ParametroEtapaVentaUpdateView.as_view(),
        name="parametro_etapa_venta",
    ),
    path("pagos/<int:pk>/editar/", views.PagoUpdateView.as_view(), name="pago_update"),
    path("pagos/<int:pk>/eliminar/", views.PagoDeleteView.as_view(), name="pago_delete"),
    path("avisos-cobro/", views.aviso_cobro_list, name="aviso_cobro_list"),
    path("parametros-mora/", views.ParametroMoraListView.as_view(), name="parametro_mora_list"),
    path("parametros-mora/nuevo/", views.ParametroMoraCreateView.as_view(), name="parametro_mora_create"),
    path(
        "parametros-mora/<int:pk>/editar/",
        views.ParametroMoraUpdateView.as_view(),
        name="parametro_mora_update",
    ),
    path(
        "parametros-mora/<int:pk>/eliminar/",
        views.ParametroMoraDeleteView.as_view(),
        name="parametro_mora_delete",
    ),
    path("api/mapa/proyecto/<int:proyecto_id>/", views.api_mapa_proyecto, name="api_mapa_proyecto"),
    path(
        "api/mapa/inmueble/<int:inmueble_id>/guardar/",
        views.api_mapa_guardar_lote,
        name="api_mapa_guardar_lote",
    ),
    path(
        "api/mapa/catastral/proyecto/<int:proyecto_id>/",
        views.api_mapa_catastral,
        name="api_mapa_catastral",
    ),
    path(
        "api/mapa/catastral/inmueble/<int:inmueble_id>/guardar/",
        views.api_mapa_catastral_guardar,
        name="api_mapa_catastral_guardar",
    ),
    path(
        "api/inmueble/<int:inmueble_id>/estado/",
        views.api_inmueble_estado,
        name="api_inmueble_estado",
    ),
    path("", include("audit.urls_web")),
    path("", include("usuarios.urls_web")),
    path("", include("docs.urls_web")),
]
