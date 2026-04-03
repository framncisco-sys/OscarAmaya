from django.contrib import admin

from .models import PerfilUsuario


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "rol", "activo_en_app", "telefono", "creado_en")
    list_filter = ("rol", "activo_en_app")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
    raw_id_fields = ("user",)
