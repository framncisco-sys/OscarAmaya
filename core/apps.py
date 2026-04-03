from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self) -> None:
        from .signing_patch import apply as apply_signing_patch

        apply_signing_patch()
        from . import signals  # noqa: F401
