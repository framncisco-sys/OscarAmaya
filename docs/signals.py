from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from inmobiliaria.models import Pago

from .services import emitir_recibo_ingreso


@receiver(post_save, sender=Pago)
def emitir_recibo_al_crear_pago(sender, instance: Pago, created: bool, **kwargs):
    # MVP: emitir recibo para cualquier pago creado (manual/bancario).
    if not created:
        return
    try:
        emitir_recibo_ingreso(pago=instance, emitido_por=None)[0]
    except Exception:
        # Si falla el PDF, no bloqueamos el registro del pago.
        return

