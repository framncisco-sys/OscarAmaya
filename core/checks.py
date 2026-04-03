"""
Comprobaciones de despliegue. Se ejecutan con: python manage.py check --deploy
Cuando existe PORT (Gunicorn / App Platform), la BD no puede seguir en localhost.
"""

from __future__ import annotations

import os

from django.core.checks import Error, register, Tags


def _is_local_host(host: str) -> bool:
    h = (host or "").strip()
    return h in frozenset({"localhost", "127.0.0.1", "::1", "[::1]"}) or h == ""


@register(Tags.database, deploy=True)
def check_database_not_localhost_on_paas(app_configs, **kwargs):
    """
    Con PORT definido (típico en App Platform), PostgreSQL en localhost fallará en runtime.
    """
    if not os.environ.get("PORT"):
        return []
    from django.conf import settings

    host = (settings.DATABASES.get("default") or {}).get("HOST") or ""
    if not _is_local_host(host):
        return []
    return [
        Error(
            "Con PORT (PaaS/Gunicorn) la base de datos apunta a localhost; en el contenedor no hay PostgreSQL local.",
            hint="Defina DATABASE_URL o POSTGRES_* en el Web Service de DigitalOcean. "
            "Validación local: python manage.py validate_digitalocean --as-app-platform. "
            "Vea deploy/DIGITALOCEAN.md.",
            id="pbr.E001",
        )
    ]
