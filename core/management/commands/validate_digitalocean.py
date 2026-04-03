"""
Valida la configuración de PostgreSQL antes/después de desplegar en App Platform.
"""

from __future__ import annotations

import os
import sys

from django.conf import settings
from django.core.management.base import BaseCommand


def _is_local_host(host: str) -> bool:
    h = (host or "").strip()
    return h in frozenset({"localhost", "127.0.0.1", "::1", "[::1]"}) or h == ""


class Command(BaseCommand):
    help = (
        "Comprueba que la BD no quede en localhost cuando se simula App Platform. "
        "Uso: python manage.py validate_digitalocean --as-app-platform"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-app-platform",
            action="store_true",
            help="Exige host remoto (simula despliegue con PORT) aunque no defina PORT en esta consola.",
        )
        parser.add_argument(
            "--try-connect",
            action="store_true",
            help="Intenta conectar a PostgreSQL tras la validación de host.",
        )

    def handle(self, *args, **options):
        as_paas = options["as_app_platform"] or bool(os.environ.get("PORT"))
        db = settings.DATABASES["default"]
        host = (db.get("HOST") or "").strip()
        is_local = _is_local_host(host)

        self.stdout.write("=== Validación Paredes Bienes Raíces (PostgreSQL / DigitalOcean) ===\n")
        self.stdout.write(f"HOST efectivo: {host!r}\n")
        self.stdout.write(f"NAME: {db.get('NAME')!r}\n")
        self.stdout.write(f"PORT (Django): {db.get('PORT')!r}\n")
        self.stdout.write(f"Usuario: {db.get('USER')!r}\n")
        self.stdout.write(f"¿Hay DATABASE_URL en el entorno?: {bool(os.environ.get('DATABASE_URL'))}\n")
        self.stdout.write(
            f"¿Hay POSTGRES_HOST en el entorno?: {bool((os.environ.get('POSTGRES_HOST') or '').strip())}\n"
        )
        self.stdout.write(f"Modo PaaS (variable PORT o --as-app-platform): {as_paas}\n")
        if os.environ.get("PORT") and not options["as_app_platform"]:
            self.stdout.write(
                "(Nota: tiene PORT en esta consola; para probar solo en local, cierre la terminal o "
                "ejecute: Remove-Item Env:PORT en PowerShell / unset PORT en bash.)\n"
            )

        self.stdout.write(
            "\nPor qué falla el login en DO si ves esto con host 'localhost':\n"
            "  En App Platform el contenedor no incluye PostgreSQL en 127.0.0.1:5432.\n"
            "  Sin DATABASE_URL (o POSTGRES_HOST remoto) Django usa los valores por defecto del código,\n"
            "  iguales a desarrollo local, y la conexión se rechaza.\n"
        )

        if as_paas and is_local:
            self.stderr.write(
                self.style.ERROR(
                    "\n[FALLO] Para desplegar, defina la base administrada en el Web Service.\n"
                )
            )
            self.stdout.write(
                "Pasos:\n"
                "  1. DigitalOcean → Databases → su clúster → Connection details.\n"
                "  2. Apps → su app → Components → Web Service → Environment.\n"
                "  3. Añada DATABASE_URL=postgresql://...?sslmode=require\n"
                "     o POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB,\n"
                "     y POSTGRES_SSLMODE=require.\n"
                "  4. Guardar, redeploy, luego: python manage.py migrate --noinput\n"
            )
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS("\n[OK] La configuración de BD es coherente con este modo."))

        if options["try_connect"]:
            from django.db import connection

            try:
                connection.ensure_connection()
                self.stdout.write(self.style.SUCCESS("[OK] Conexión a PostgreSQL correcta."))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"\n[FALLO] No se pudo conectar: {exc}"))
                sys.exit(1)
