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
    _log = logging.getLogger("pbr.database")
    _log.info(
        "PBR DB default host=%s name=%s (debe coincidir con la consola one-off)",
        _d.get("HOST", ""),
        _d.get("NAME", ""),
    )
    if not django_settings.DEBUG:
        if getattr(django_settings, "DJANGO_USE_S3_MEDIA", False):
            _log.info("PBR media: S3/Spaces (persistente entre redeploys).")
        else:
            _log.warning(
                "PBR media: FileSystemStorage — en App Platform el disco del contenedor es "
                "EFÍMERO; firmas y PDFs en /media se pierden al redeploy. Defina "
                "DJANGO_USE_S3_MEDIA=1 y credenciales Spaces (ver deploy/COPIAR_A_DIGITALOCEAN.txt)."
            )
except Exception:
    pass
