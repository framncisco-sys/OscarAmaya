from django.urls import path

from . import views_web as views

urlpatterns = [
    path("usuarios/", views.UsuarioListView.as_view(), name="usuario_list"),
    path("usuarios/nuevo/", views.usuario_create, name="usuario_create"),
    path("usuarios/<int:pk>/editar/", views.usuario_update, name="usuario_update"),
    path("usuarios/<int:pk>/eliminar/", views.UsuarioDeleteView.as_view(), name="usuario_delete"),
    path("usuarios/roles/", views.usuario_roles_manual, name="usuario_roles_manual"),
]
