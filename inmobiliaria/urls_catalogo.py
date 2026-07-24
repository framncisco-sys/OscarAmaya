from django.urls import path

from . import views_catalogo

app_name = "catalogo"

urlpatterns = [
    path("", views_catalogo.catalogo_list, name="list"),
    path("qr.png", views_catalogo.catalogo_qr, name="qr"),
    path("<int:pk>/qr.png", views_catalogo.catalogo_qr, name="qr_detalle"),
    path("<int:pk>/", views_catalogo.catalogo_detalle, name="detalle"),
]
