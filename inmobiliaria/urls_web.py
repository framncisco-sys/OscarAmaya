"""Rutas de la interfaz web minimalista bajo /app/."""

from django.urls import include, path
from django.views.generic import RedirectView

from . import views_web as views

app_name = "app"

urlpatterns = [
    path("", views.AppIndexView.as_view(), name="index"),
    path("confirmar-acceso/", views.sensitive_reauth, name="sensitive_reauth"),
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
    path("inmuebles/", views.InmuebleListView.as_view(), name="inmueble_list"),
    path("inmuebles/nuevo/", views.InmuebleCreateView.as_view(), name="inmueble_create"),
    path("inmuebles/<int:pk>/editar/", views.InmuebleUpdateView.as_view(), name="inmueble_update"),
    path("inmuebles/<int:pk>/eliminar/", views.InmuebleDeleteView.as_view(), name="inmueble_delete"),
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
        "clientes/documentos/<int:pk>/eliminar/",
        views.cliente_documento_delete,
        name="cliente_documento_delete",
    ),
    path("vendedores/", views.VendedorListView.as_view(), name="vendedor_list"),
    path("vendedores/nuevo/", views.VendedorCreateView.as_view(), name="vendedor_create"),
    path("vendedores/<int:pk>/editar/", views.VendedorUpdateView.as_view(), name="vendedor_update"),
    path("vendedores/<int:pk>/eliminar/", views.VendedorDeleteView.as_view(), name="vendedor_delete"),
    path("contratos/", views.ContratoListView.as_view(), name="contrato_list"),
    path("contratos/nuevo/", views.ContratoCreateView.as_view(), name="contrato_create"),
    path("contratos/<int:pk>/editar/", views.ContratoUpdateView.as_view(), name="contrato_update"),
    path("contratos/<int:pk>/eliminar/", views.ContratoDeleteView.as_view(), name="contrato_delete"),
    path(
        "contratos/<int:pk>/estado-cuenta/",
        views.contrato_estado_cuenta,
        name="contrato_estado_cuenta",
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
    path("reportes/pagos.csv", views.export_pagos_csv, name="export_pagos_csv"),
    path("pagos/", views.PagoListView.as_view(), name="pago_list"),
    path("pagos/nuevo/", views.PagoCreateView.as_view(), name="pago_create"),
    path("pagos/<int:pk>/editar/", views.PagoUpdateView.as_view(), name="pago_update"),
    path("pagos/<int:pk>/eliminar/", views.PagoDeleteView.as_view(), name="pago_delete"),
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
    path("", include("audit.urls_web")),
    path("", include("usuarios.urls_web")),
    path("", include("docs.urls_web")),
]
