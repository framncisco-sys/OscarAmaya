"""Reserva de inventario al guardar formato de aceptación."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from inmobiliaria.models import FormatoAceptacion, Inmueble


def _dias_reserva_desde_formato() -> int:
    try:
        n = int(getattr(settings, "PBR_RESERVA_DIAS_DESDE_FORMATO", 30))
    except (TypeError, ValueError):
        n = 30
    return max(1, min(n, 365))


def vincular_contrato_desde_formato_si_falta(fmt: FormatoAceptacion) -> None:
    """Crea/vincula contrato desde el formato (reserva/prima o contado) si aún no tiene."""
    if fmt.contrato_id or not (fmt.num_lote or "").strip():
        return
    from inmobiliaria.credito_contrato import (
        asegurar_contrato_contado_desde_formato,
        asegurar_contrato_reserva_prima_desde_formato,
        resolver_inmueble_desde_formato,
    )

    if resolver_inmueble_desde_formato(fmt) is None:
        return

    tipo = (fmt.tipo_financiamiento or "").strip()
    if tipo == FormatoAceptacion.TipoFinanciamiento.CONTADO:
        asegurar_contrato_contado_desde_formato(fmt)
    else:
        asegurar_contrato_reserva_prima_desde_formato(fmt)


def aplicar_reserva_lote_desde_formato(fmt: FormatoAceptacion) -> bool:
    """
    Marca el lote del formato como RESERVADO para el cliente del formato.
    Devuelve True si el inventario quedó (o ya estaba) reservado para ese cliente.
    """
    if not (fmt.num_lote or "").strip():
        return False

    from inmobiliaria.credito_contrato import (
        cliente_desde_formato_aceptacion,
        resolver_inmueble_desde_formato,
    )

    inv = resolver_inmueble_desde_formato(fmt)
    if inv is None:
        return False

    if inv.estado in (Inmueble.Estado.VENDIDO, Inmueble.Estado.BLOQUEADO):
        return False

    cliente = cliente_desde_formato_aceptacion(fmt)
    hasta = timezone.localdate() + timedelta(days=_dias_reserva_desde_formato())

    if inv.estado == Inmueble.Estado.RESERVADO:
        if inv.cliente_reserva_id != cliente.pk:
            return False
        updates: dict = {}
        if not inv.reserva_hasta or inv.reserva_hasta < timezone.localdate():
            updates["reserva_hasta"] = hasta
        if updates:
            Inmueble.objects.filter(pk=inv.pk).update(**updates)
        return True

    if inv.estado == Inmueble.Estado.DISPONIBLE:
        Inmueble.objects.filter(pk=inv.pk).update(
            estado=Inmueble.Estado.RESERVADO,
            cliente_reserva_id=cliente.pk,
            reserva_hasta=hasta,
        )
        return True

    return False


def sincronizar_reservas_desde_formatos(*, solo_sin_reserva: bool = True) -> int:
    """
    Recorre formatos con lote y aplica reserva en inventario.
    Útil tras desplegar la corrección sobre datos ya guardados.
    """
    qs = FormatoAceptacion.objects.exclude(num_lote="").order_by("numero_formulario", "id")
    n = 0
    for fmt in qs.iterator():
        if solo_sin_reserva:
            inv = None
            from inmobiliaria.credito_contrato import resolver_inmueble_desde_formato

            inv = resolver_inmueble_desde_formato(fmt)
            if inv is None or inv.estado != Inmueble.Estado.DISPONIBLE:
                continue
        vincular_contrato_desde_formato_si_falta(fmt)
        if aplicar_reserva_lote_desde_formato(fmt):
            n += 1
    return n
