from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Contrato, CuotaProgramada, HistorialPrecioInmueble, Inmueble, Pago

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
def intentar_comision_vendedor_tras_validar_abono(
    sender, instance: Pago, created: bool, **kwargs
):
    """
    Si ya hay reserva y prima validadas, y el vendedor está completo,
    genera automáticamente el recibo de comisión al vendedor.
    """
    if instance.concepto not in (
        Pago.Concepto.RESERVA,
        Pago.Concepto.PRIMA,
        Pago.Concepto.CONTADO,
    ):
        return
    if not instance.contrato_id:
        return
    if instance.validacion_abono != Pago.ValidacionAbono.VALIDADO:
        return
    # Solo al pasar a validado (no en el alta pendiente).
    if created and instance.pendiente_validacion_gerente:
        return

    contrato_id = instance.contrato_id

    def _emitir():
        from inmobiliaria.comision_vendedor import intentar_emitir_comision_automatica

        intentar_emitir_comision_automatica(contrato_id)

    transaction.on_commit(_emitir)


@receiver(post_save, sender=Pago)
def aplicar_pago_a_cuota_programada(sender, instance: Pago, created: bool, **kwargs):
    """Marca cuotas del calendario solo cuando el abono ya puede contar (validado o sin validación)."""
    if instance.concepto != Pago.Concepto.CUOTA:
        return
    if not instance.puede_emitir_recibo_cliente:
        return
    # Alta pendiente: no aplicar. Tras validar (update a VALIDADO): aplicar.
    if created and instance.pendiente_validacion_gerente:
        return
    if not created and instance.validacion_abono != Pago.ValidacionAbono.VALIDADO:
        return

    def _apply():
        aplicar_cuotas_programadas_del_pago(instance)

    transaction.on_commit(_apply)


def aplicar_cuotas_programadas_del_pago(pago: Pago) -> list:
    """
    Liquida las N primeras cuotas pendientes.
    El monto del pago puede ser mayor (excedente = abono a capital en el mismo recibo).
    """
    if pago.concepto != Pago.Concepto.CUOTA or not pago.contrato_id:
        return []
    if not pago.puede_emitir_recibo_cliente:
        return []
    n = max(1, min(int(pago.cuotas_incluidas or 1), 200))
    aplicadas = []
    with transaction.atomic():
        qs = (
            CuotaProgramada.objects.select_for_update()
            .filter(
                contrato=pago.contrato,
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
            return []
        suma = sum((c.monto for c in cuotas), Decimal("0")).quantize(Decimal("0.01"))
        if pago.monto < suma:
            return []
        for cuota in cuotas:
            cuota.pago = pago
            cuota.estado = CuotaProgramada.Estado.PAGADA
            cuota.pagado_en = pago.fecha
            cuota.save(update_fields=["pago", "estado", "pagado_en"])
            aplicadas.append(cuota)
        if aplicadas:
            intentar_liquidar_contrato_si_completo(pago.contrato_id)
    return aplicadas


def intentar_liquidar_contrato_si_completo(contrato_id: int | None) -> bool:
    """
    Si el plan tiene calendario y todas las cuotas están pagadas,
    pasa a LIQUIDADO (también si estaba en BORRADOR), etapa CIERRE y lote VENDIDO.
    """
    if not contrato_id:
        return False
    with transaction.atomic():
        contrato = (
            Contrato.objects.select_for_update()
            .select_related("inmueble")
            .filter(pk=contrato_id)
            .first()
        )
        if contrato is None:
            return False
        if contrato.estado in (
            Contrato.Estado.LIQUIDADO,
            Contrato.Estado.CANCELADO,
        ):
            return False

        total = CuotaProgramada.objects.filter(contrato_id=contrato.pk).count()
        if total < 1:
            return False
        abiertas = (
            CuotaProgramada.objects.filter(contrato_id=contrato.pk)
            .exclude(estado=CuotaProgramada.Estado.PAGADA)
            .exists()
        )
        if abiertas:
            return False

        contrato.estado = Contrato.Estado.LIQUIDADO
        contrato.etapa_comercial = Contrato.EtapaComercial.CIERRE
        contrato.save(update_fields=["estado", "etapa_comercial"])

        if contrato.inmueble_id:
            Inmueble.objects.filter(pk=contrato.inmueble_id).exclude(
                estado=Inmueble.Estado.VENDIDO
            ).update(
                estado=Inmueble.Estado.VENDIDO,
                cliente_reserva_id=contrato.cliente_id,
            )
        return True


@receiver(post_save, sender=Pago)
def avanzar_etapa_comercial_por_pago(sender, instance: Pago, created: bool, **kwargs):
    """Reserva/prima/contado/cuotas: efectos comerciales al validar el abono."""
    if not instance.contrato_id:
        return
    if instance.pendiente_validacion_gerente:
        return
    if instance.validacion_abono == Pago.ValidacionAbono.RECHAZADO:
        return
    # Alta pendiente: no aplicar. Tras validar (update a VALIDADO): aplicar.
    if created and instance.requiere_validacion_gerente:
        return
    if not created and instance.validacion_abono != Pago.ValidacionAbono.VALIDADO:
        return
    if not created and not instance.requiere_validacion_gerente:
        return

    _aplicar_efectos_comerciales_pago(instance)


def _aplicar_efectos_comerciales_pago(instance: Pago) -> None:
    contrato = instance.contrato
    etapa = contrato.etapa_comercial
    nueva = None
    if instance.concepto == Pago.Concepto.RESERVA:
        if etapa in (
            Contrato.EtapaComercial.CONVERSACION,
            Contrato.EtapaComercial.RESERVA,
        ):
            nueva = Contrato.EtapaComercial.RESERVA
    elif instance.concepto == Pago.Concepto.PRIMA:
        if etapa != Contrato.EtapaComercial.CIERRE:
            nueva = Contrato.EtapaComercial.DOCUMENTOS
    elif instance.concepto == Pago.Concepto.CONTADO:
        nueva = Contrato.EtapaComercial.CIERRE

    if nueva and nueva != etapa:
        Contrato.objects.filter(pk=contrato.pk).update(etapa_comercial=nueva)

    if instance.concepto == Pago.Concepto.RESERVA:
        inm = contrato.inmueble
        if inm and inm.estado == Inmueble.Estado.DISPONIBLE:
            Inmueble.objects.filter(pk=inm.pk).update(
                estado=Inmueble.Estado.RESERVADO,
                cliente_reserva_id=contrato.cliente_id,
            )
    elif instance.concepto == Pago.Concepto.CONTADO:
        # Contado: cierra la operación (activo o borrador → liquidado).
        Contrato.objects.filter(pk=contrato.pk).exclude(
            estado=Contrato.Estado.CANCELADO
        ).update(
            estado=Contrato.Estado.LIQUIDADO,
            etapa_comercial=Contrato.EtapaComercial.CIERRE,
        )
        # Refrescar para notificación de cierre si hace falta
        contrato.refresh_from_db(fields=["estado", "etapa_comercial"])
        if etapa != Contrato.EtapaComercial.CIERRE:
            # Disparar aviso al vendedor (update() no dispara post_save de etapa)
            from docs.vendedor_notificacion import notificar_vendedor_cierre_venta

            cid = contrato.pk

            def _enviar():
                notificar_vendedor_cierre_venta(cid)

            transaction.on_commit(_enviar)
        inm = contrato.inmueble
        if inm and inm.estado != Inmueble.Estado.VENDIDO:
            Inmueble.objects.filter(pk=inm.pk).update(
                estado=Inmueble.Estado.VENDIDO,
                cliente_reserva_id=contrato.cliente_id,
            )
    elif instance.concepto in (
        Pago.Concepto.CUOTA,
        Pago.Concepto.ABONO_CAPITAL,
    ):
        # Por si el pago se validó después de aplicar cuotas en otro camino.
        intentar_liquidar_contrato_si_completo(contrato.pk)


@receiver(pre_save, sender=Contrato)
def _contrato_recordar_etapa_comercial_previa(sender, instance: Contrato, **kwargs):
    if not instance.pk:
        instance._etapa_comercial_previa = None
        return
    prev = (
        Contrato.objects.filter(pk=instance.pk)
        .values_list("etapa_comercial", flat=True)
        .first()
    )
    instance._etapa_comercial_previa = prev


@receiver(post_save, sender=Contrato)
def _contrato_notificar_vendedor_cierre(sender, instance: Contrato, created: bool, **kwargs):
    if not getattr(settings, "VENDEDOR_NOTIFICAR_CIERRE_EMAIL", True):
        return
    prev = getattr(instance, "_etapa_comercial_previa", None)
    if instance.etapa_comercial != Contrato.EtapaComercial.CIERRE:
        return
    if prev == Contrato.EtapaComercial.CIERRE:
        return
    cid = instance.pk

    def _enviar():
        from docs.vendedor_notificacion import notificar_vendedor_cierre_venta

        notificar_vendedor_cierre_venta(cid)

    transaction.on_commit(_enviar)


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
