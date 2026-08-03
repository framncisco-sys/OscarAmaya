from django.urls import path

from . import views_web as views

urlpatterns = [
    path("docs/", views.docs_list, name="docs_list"),
    path("docs/cliente/", views.docs_cliente, name="docs_cliente"),
    path("docs/<int:doc_id>/descargar/", views.doc_download, name="doc_download"),
    path("docs/promesa/<int:contrato_id>/", views.emitir_promesa, name="emitir_promesa"),
    path("docs/recibo/<int:pago_id>/", views.emitir_recibo, name="emitir_recibo"),
    path(
        "docs/recibo-comision/<int:contrato_id>/",
        views.emitir_recibo_comision,
        name="emitir_recibo_comision",
    ),
]
