from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = 'audit'

    def ready(self) -> None:
        from django.conf import settings

        if getattr(settings, "AUDIT_SIGNALS_ENABLED", False):
            from . import signals  # noqa: F401
