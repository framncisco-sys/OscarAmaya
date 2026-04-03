from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import CuotaProgramada, HistorialPrecioInmueble, Inmueble, Pago

_inmueble_precio_anterior: dict[int, Decimal] = {}


@receiver(pre_save, sender=Inmueble)
def _recordar_precio_inmueble_antes_de_guardar(sender, instance: Inmueble, **kwargs):
    if not instance.pk:
        return
    try:
        prev = Inmueble.objects.get(pk=instance.pk)
        _inmueble_precio_anterior[instance.pk] = prev.precio_lista
    except Inmueble.DoesNotExist:
        pass


@receiver(post_save, sender=Inmueble)
def _historial_precio_inmueble(sender, instance: Inmueble, created: bool, **kwargs):
    if created:
        return
    prev = _inmueble_precio_anterior.pop(instance.pk, None)
    if prev is None or prev == instance.precio_lista:
        return
    HistorialPrecioInmueble.objects.create(
        inmueble=instance,
        precio_anterior=prev,
        precio_nuevo=instance.precio_lista,
    )


@receiver(post_save, sender=Pago)
def aplicar_pago_a_cuota_programada(sender, instance: Pago, created: bool, **kwargs):
    if not created:
        return
    if instance.concepto != Pago.Concepto.CUOTA:
        return

    n = max(1, min(int(instance.cuotas_incluidas or 1), 60))

    def _apply():
        with transaction.atomic():
            qs = (
                CuotaProgramada.objects.select_for_update()
                .filter(
                    contrato=instance.contrato,
                    estado__in=[
                        CuotaProgramada.Estado.PENDIENTE,
                        CuotaProgramada.Estado.VENCIDA,
                    ],
                    pago__isnull=True,
                )
                .order_by("vence_en", "numero", "id")
            )
            cuotas = list(qs[:n])
            if len(cuotas) < n:
                return
            suma = sum((c.monto for c in cuotas), Decimal("0")).quantize(Decimal("0.01"))
            if instance.monto != suma:
                return
            for cuota in cuotas:
                cuota.pago = instance
                cuota.estado = CuotaProgramada.Estado.PAGADA
                cuota.pagado_en = instance.fecha
                cuota.save(update_fields=["pago", "estado", "pagado_en"])

    transaction.on_commit(_apply)


@receiver(post_save, sender=CuotaProgramada)
def marcar_vencida_si_aplica(sender, instance: CuotaProgramada, created: bool, **kwargs):
    # MVP: marcar vencida si vence_en ya pasó y sigue pendiente.
    if instance.estado != CuotaProgramada.Estado.PENDIENTE:
        return
    hoy = timezone.localdate()
    if instance.vence_en < hoy:
        CuotaProgramada.objects.filter(pk=instance.pk, estado=CuotaProgramada.Estado.PENDIENTE).update(
            estado=CuotaProgramada.Estado.VENCIDA
        )
