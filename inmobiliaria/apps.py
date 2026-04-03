from django.apps import AppConfig


class InmobiliariaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inmobiliaria"
    verbose_name = "Inmobiliaria"

    def ready(self) -> None:
        from . import signals  # noqa: F401
