"""Libera lotes cuya reserva ya venció (estado → Disponible). Ejecutar diario con tarea programada."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from inmobiliaria.models import Inmueble


class Command(BaseCommand):
    help = "Pone en Disponible los inmuebles en Reservado con fecha límite vencida."

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        qs = Inmueble.objects.filter(
            estado=Inmueble.Estado.RESERVADO,
            reserva_hasta__isnull=False,
            reserva_hasta__lt=hoy,
        )
        n = 0
        for inv in qs:
            inv.estado = Inmueble.Estado.DISPONIBLE
            inv.reserva_hasta = None
            inv.cliente_reserva = None
            inv.save(update_fields=["estado", "reserva_hasta", "cliente_reserva"])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Reservas liberadas: {n} inmueble(s)."))
