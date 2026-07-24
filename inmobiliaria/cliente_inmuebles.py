"""Consultas de relación cliente ↔ inmueble (venta, reserva, alquiler)."""

from __future__ import annotations

from inmobiliaria.models import Cliente, Contrato, Inmueble


def build_cliente_inmuebles_context(cliente: Cliente) -> dict:
    contratos = (
        Contrato.objects.filter(cliente=cliente)
        .select_related("inmueble", "inmueble__proyecto")
        .order_by("-fecha_firma", "-pk")
    )
    reservas = (
        Inmueble.objects.filter(cliente_reserva=cliente)
        .select_related("proyecto")
        .order_by("proyecto__nombre", "codigo")
    )
    alquileres_local = (
        Inmueble.objects.filter(detalle_local_alquiler__inquilino=cliente, en_alquiler=True)
        .select_related("proyecto", "detalle_local_alquiler")
        .order_by("codigo")
    )
    alquileres_casa = (
        Inmueble.objects.filter(detalle_casa_alquiler__inquilino=cliente, en_alquiler=True)
        .select_related("proyecto", "detalle_casa_alquiler")
        .order_by("codigo")
    )
    return {
        "cliente_contratos": contratos,
        "cliente_reservas": reservas,
        "cliente_alquileres_local": alquileres_local,
        "cliente_alquileres_casa": alquileres_casa,
        "cliente_tiene_inmuebles": any(
            [
                contratos.exists(),
                reservas.exists(),
                alquileres_local.exists(),
                alquileres_casa.exists(),
            ]
        ),
    }
