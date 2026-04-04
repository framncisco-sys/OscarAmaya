"""
WSGI config for backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

application = get_wsgi_application()

# Una línea por worker: comparar HOST/NAME con `verificar_formatos_aceptacion` en la misma plataforma.
try:
    import logging

    from django.conf import settings as django_settings

    _d = django_settings.DATABASES["default"]
    logging.getLogger("pbr.database").info(
        "PBR DB default host=%s name=%s (debe coincidir con la consola one-off)",
        _d.get("HOST", ""),
        _d.get("NAME", ""),
    )
except Exception:
    pass
