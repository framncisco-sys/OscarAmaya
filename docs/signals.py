from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from inmobiliaria.models import Pago

from .services import emitir_recibo_ingreso

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Pago)
def emitir_recibo_al_crear_pago(sender, instance: Pago, created: bool, **kwargs):
    """
    Recibo automático solo si el abono no requiere validación de gerencia,
    o ya fue validado (p. ej. tras confirmar depósito).
    Reserva/prima/cuotas pendientes: no PDF, no correo, no WhatsApp.
    """
    if not created:
        return
    if not instance.puede_emitir_recibo_cliente:
        return
    try:
        emitir_recibo_ingreso(pago=instance, emitido_por=None)[0]
    except Exception:
        logger.exception(
            "No se pudo emitir recibo PDF automático para pago id=%s (el pago sí quedó guardado).",
            instance.pk,
        )
