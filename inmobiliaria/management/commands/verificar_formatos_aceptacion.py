"""Diagnóstico: cuántos formatos de aceptación hay en la base `default`."""

from django.conf import settings
from django.core.management.base import BaseCommand

from inmobiliaria.models import FormatoAceptacion


class Command(BaseCommand):
    help = (
        "Muestra el total de registros en FormatoAceptacion y los últimos (misma BD que usa la app)."
    )

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")
        name = db.get("NAME", "")
        host = (db.get("HOST") or "")[:80]
        self.stdout.write(f"BD default: engine={engine}")
        self.stdout.write(f"  NAME={name!r} HOST={host!r}")

        n = FormatoAceptacion.objects.count()
        self.stdout.write(self.style.WARNING(f"Total formatos de aceptación: {n}"))

        if n == 0:
            self.stdout.write(
                "Si acaba de guardar en la web y aquí sale 0: "
                "revise que el Web Service use esta misma DATABASE_URL, "
                "y ejecute: python manage.py migrate --noinput"
            )
            return

        for f in FormatoAceptacion.objects.order_by("-id")[:15]:
            self.stdout.write(
                f"  id={f.pk} nº={f.numero_formulario:04d} nombre={f.nombre_cliente!r}"
            )
