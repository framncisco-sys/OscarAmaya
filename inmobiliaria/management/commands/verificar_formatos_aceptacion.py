"""Diagnóstico: formatos guardados, origen de DATABASE y estado de migraciones en esta BD."""

import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from inmobiliaria.models import FormatoAceptacion


def _origen_config_bd() -> str:
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if raw and not raw.startswith("${"):
        return "DATABASE_URL (tiene prioridad en settings)"
    if (os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOSTNAME") or "").strip():
        return "PGHOST / PGDATABASE / variables libpq"
    if (os.environ.get("DB_HOST") or "").strip():
        return "DB_HOST / DB_NAME (convención DB_*)"
    return "POSTGRES_HOST + POSTGRES_DB (valores por defecto en settings)"


class Command(BaseCommand):
    help = (
        "Cuenta formatos de aceptación y muestra qué BD usa este proceso "
        "(debe coincidir con el Web Service para que lista y guardado vean los mismos datos)."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE(f"Origen configuración BD: {_origen_config_bd()}"))
        if (os.environ.get("DATABASE_URL") or "").strip().startswith("${"):
            self.stdout.write(
                self.style.ERROR(
                    "DATABASE_URL parece sin resolver (${...}). En DO, vincule la BD al componente "
                    "o pegue la URL completa; si no, la app puede caer en POSTGRES_* distintos."
                )
            )

        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")
        name = db.get("NAME", "")
        host = db.get("HOST") or ""
        port = db.get("PORT") or ""
        user = db.get("USER") or ""
        self.stdout.write(f"BD default: engine={engine}")
        self.stdout.write(f"  NAME={name!r}")
        self.stdout.write(f"  HOST={host!r} PORT={port!r} USER={user!r}")
        self.stdout.write(
            "Compare HOST con los logs de arranque del Web (línea PBR DB default) "
            "y con otra consola: deben ser el mismo cluster."
        )

        # Migraciones aplicadas en esta misma conexión
        self.stdout.write("")
        self.stdout.write("Últimas migraciones inmobiliaria registradas en esta BD:")
        rec = (
            MigrationRecorder.Migration.objects.filter(app="inmobiliaria")
            .order_by("-applied")
            .values_list("name", "applied")[:15]
        )
        rows = list(rec)
        if not rows:
            self.stdout.write(self.style.ERROR("  (ninguna — BD nueva o tabla django_migrations vacía)"))
        else:
            for mname, applied in rows:
                self.stdout.write(f"  {mname}  ({applied})")

        # Columna crítica post-0021
        self.stdout.write("")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'inmobiliaria_formatoaceptacion'
                      AND column_name = 'lugar_nacimiento'
                    """
                )
                col_ok = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'inmobiliaria_formatoaceptacion'
                    """
                )
                table_ok = cursor.fetchone()[0]
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"No se pudo consultar information_schema: {exc}"))
            col_ok = table_ok = 0

        if not table_ok:
            self.stdout.write(
                self.style.ERROR(
                    "La tabla inmobiliaria_formatoaceptacion no existe en esta BD. "
                    "Ejecute: python manage.py migrate --noinput"
                )
            )
        elif not col_ok:
            self.stdout.write(
                self.style.ERROR(
                    "Falta la columna lugar_nacimiento (migración 0021 no aplicada en esta BD). "
                    "Ejecute: python manage.py migrate --noinput"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Tabla y columna lugar_nacimiento: OK"))

        self.stdout.write("")
        n = FormatoAceptacion.objects.count()
        self.stdout.write(self.style.WARNING(f"Total formatos de aceptación (ORM): {n}"))

        if n == 0 and table_ok:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM inmobiliaria_formatoaceptacion")
                    raw_n = cursor.fetchone()[0]
                self.stdout.write(f"Total filas (SQL directo): {raw_n}")
            except Exception as exc:
                self.stdout.write(f"SQL COUNT falló: {exc}")

        if n == 0:
            self.stdout.write(
                "\nSi guardó en la web y sigue en 0: el navegador habla con otro HOST de Postgres "
                "que esta consola, o el guardado falló (revise logs del Web Service tras enviar el formulario)."
            )
            return

        for f in FormatoAceptacion.objects.order_by("-id")[:15]:
            self.stdout.write(
                f"  id={f.pk} nº={f.numero_formulario:04d} nombre={f.nombre_cliente!r}"
            )
            for label, img in (
                ("aceptante", f.firma_aceptante),
                ("vendedor", f.firma_vendedor),
                ("autorizado", f.firma_autorizado),
            ):
                nm = getattr(img, "name", None) or ""
                if not nm:
                    self.stdout.write(self.style.ERROR(f"    firma {label}: (sin nombre en BD)"))
                elif default_storage.exists(nm):
                    try:
                        sz = default_storage.size(nm)
                    except Exception:
                        sz = "?"
                    self.stdout.write(f"    firma {label}: OK en storage ({sz} bytes) {nm!r}")
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"    firma {label}: BD tiene ruta pero NO existe en storage — "
                            f"PDF sin imagen; use DJANGO_USE_S3_MEDIA o volumen persistente. {nm!r}"
                        )
                    )
