from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "usuarios"
    verbose_name = "Usuarios y roles"

    def ready(self) -> None:
        from . import signals  # noqa: F401
