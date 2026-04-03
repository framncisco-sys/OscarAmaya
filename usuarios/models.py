from django.conf import settings
from django.db import models


class PerfilUsuario(models.Model):
    """
    Rol operativo en la app de gestión (no reemplaza al superusuario de Django ni al admin /interno/).
    Cada usuario del staff debería tener un perfil tras el despliegue inicial.
    """

    class Rol(models.TextChoices):
        ADMINISTRADOR = "ADMINISTRADOR", "Administrador de sistema"
        GERENCIA = "GERENCIA", "Gerencia"
        VENTAS = "VENTAS", "Ventas / comercial"
        CARTERA = "CARTERA", "Cartera / finanzas"
        PROYECTOS = "PROYECTOS", "Proyectos, lotes y mapa"
        MARKETING = "MARKETING", "Marketing / CRM"
        LECTURA = "LECTURA", "Solo consulta"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil_app",
        verbose_name="usuario",
    )
    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.LECTURA,
        db_index=True,
        verbose_name="rol",
    )
    telefono = models.CharField(max_length=40, blank=True, verbose_name="teléfono")
    activo_en_app = models.BooleanField(
        default=True,
        verbose_name="activo en gestión web",
        help_text="Si está desmarcado, no podrá usar /app/ (solo cerrar sesión).",
    )
    notas = models.TextField(blank=True, verbose_name="notas internas")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil de usuario (app)"
        verbose_name_plural = "Perfiles de usuario (app)"
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"{self.user.get_username()} ({self.get_rol_display()})"
