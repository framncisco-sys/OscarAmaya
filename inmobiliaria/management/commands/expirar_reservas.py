"""Libera lotes cuya reserva ya venció (estado → Disponible). Ejecutar diario con tarea programada."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from inmobiliaria.models import Inmueble


class Command(BaseCommand):
    help = "Pone en Disponible los inmuebles en Reservado con fecha límite vencida."

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        n = Inmueble.objects.filter(
            estado=Inmueble.Estado.RESERVADO,
            reserva_hasta__isnull=False,
            reserva_hasta__lt=hoy,
        ).update(
            estado=Inmueble.Estado.DISPONIBLE,
            reserva_hasta=None,
            cliente_reserva=None,
        )
        self.stdout.write(self.style.SUCCESS(f"Reservas liberadas: {n} inmueble(s)."))
