"""Sincroniza reservas de inventario desde formatos de aceptación ya guardados."""

from django.core.management.base import BaseCommand

from inmobiliaria.formato_reserva import sincronizar_reservas_desde_formatos


class Command(BaseCommand):
    help = (
        "Marca en RESERVADO los lotes de formatos guardados que siguen DISPONIBLES "
        "(corrección tras despliegue de reserva automática al guardar formato)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--todos",
            action="store_true",
            help="Revisar todos los formatos, no solo lotes aún disponibles.",
        )

    def handle(self, *args, **options):
        n = sincronizar_reservas_desde_formatos(solo_sin_reserva=not options["todos"])
        self.stdout.write(
            self.style.SUCCESS(f"Lotes puestos en reserva desde formatos: {n}")
        )
