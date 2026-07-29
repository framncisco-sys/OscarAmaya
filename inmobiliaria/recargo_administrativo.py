"""Recargo administrativo (no «mora» diaria): monto fijo + días de gracia.

Regla de negocio:
- Si la cuota 21 se paga tarde, ese recibo lleva SOLO la cuota.
- El recargo por ese atraso se cobra en la cuota siguiente (22): cuota 22 + recargo.
- Si se liquidan varias juntas (21 y 22), el recargo de la(s) anterior(es)
  atrasada(s) sí entra en ese mismo pago; la última cuota del lote no genera
  recargo en ese recibo (pasa a la siguiente si también viene tarde).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from inmobiliaria.models import CuotaProgramada, ParametroMora, Pago


def parametro_recargo_activo() -> ParametroMora | None:
    return (
        ParametroMora.objects.filter(activo=True)
        .order_by("-id")
        .first()
    )


def fecha_limite_gracia(vence_en: date, dias_gracia: int) -> date:
    return vence_en + timedelta(days=max(0, int(dias_gracia or 0)))


def cuota_impaga(cuota: CuotaProgramada) -> bool:
    if cuota.pago_id is not None:
        return False
    return cuota.estado in (
        CuotaProgramada.Estado.PENDIENTE,
        CuotaProgramada.Estado.VENCIDA,
    )


def cuota_genera_recargo(
    cuota: CuotaProgramada,
    *,
    hoy: date | None = None,
    dias_gracia: int = 0,
) -> bool:
    """True si la cuota sigue sin pagar y ya pasó el vencimiento + gracia."""
    if not cuota_impaga(cuota):
        return False
    corte = hoy or timezone.localdate()
    return corte > fecha_limite_gracia(cuota.vence_en, dias_gracia)


def monto_recargos_pagados(
    contrato_id: int,
    *,
    excluir_pago_id: int | None = None,
) -> Decimal:
    """Suma de recargos cubiertos: pagos MORA + recargo incluido en pagos de cuota."""
    qs_mora = Pago.objects.filter(
        contrato_id=contrato_id,
        concepto=Pago.Concepto.MORA,
    ).exclude(validacion_abono=Pago.ValidacionAbono.RECHAZADO)
    qs_inc = Pago.objects.filter(
        contrato_id=contrato_id,
        concepto=Pago.Concepto.CUOTA,
    ).exclude(validacion_abono=Pago.ValidacionAbono.RECHAZADO)
    if excluir_pago_id:
        qs_mora = qs_mora.exclude(pk=excluir_pago_id)
        qs_inc = qs_inc.exclude(pk=excluir_pago_id)
    mora = qs_mora.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    incluido = qs_inc.aggregate(t=Sum("monto_recargo_incluido"))["t"] or Decimal("0")
    return (mora + incluido).quantize(Decimal("0.01"))


def _clave_cuota(c: CuotaProgramada) -> tuple:
    return (c.vence_en, c.numero, c.pk)


def _pagos_cuota_con_atraso_en_ultima(
    contrato_id: int,
    *,
    dias_gracia: int,
    excluir_pago_id: int | None = None,
    antes_de_clave: tuple | None = None,
) -> list[Pago]:
    """
    Pagos de cuota anteriores cuya *última* cuota se pagó después de la gracia.
    Cada uno = 1 evento de recargo (se cobra en un pago posterior, no en ese).

    Se filtra por orden de cuotas (vence/número), no por la fecha del pago frente
    a «hoy»: en pruebas o pagos anticipados la fecha del recibo puede ser anterior
    al vencimiento del calendario y eso no debe ocultar atrasos ya registrados.
    """
    qs = (
        Pago.objects.filter(
            contrato_id=contrato_id,
            concepto=Pago.Concepto.CUOTA,
        )
        .exclude(validacion_abono=Pago.ValidacionAbono.RECHAZADO)
        .prefetch_related("cuotas_aplicadas")
        .order_by("fecha", "id")
    )
    if excluir_pago_id:
        qs = qs.exclude(pk=excluir_pago_id)
    out: list[Pago] = []
    for p in qs:
        vinculadas = sorted(
            p.cuotas_aplicadas.all(),
            key=lambda c: (c.vence_en, c.numero, c.pk),
        )
        if not vinculadas or not p.fecha:
            continue
        ultima = vinculadas[-1]
        if not ultima.vence_en:
            continue
        # Solo atrasos de cuotas anteriores a la que se está cobrando ahora.
        if antes_de_clave is not None and _clave_cuota(ultima) >= antes_de_clave:
            continue
        if p.fecha > fecha_limite_gracia(ultima.vence_en, dias_gracia):
            out.append(p)
    return out


@dataclass(frozen=True)
class CobroMes:
    """Qué debe verse al cobrar el mes (cuota actual + recargos)."""

    cuota: CuotaProgramada | None
    monto_cuota: Decimal
    monto_recargo: Decimal
    cantidad_recargos: int
    monto_total: Decimal
    dias_gracia: int
    monto_unitario_recargo: Decimal
    cuotas_que_generan_recargo: tuple[CuotaProgramada, ...]
    nota: str


def _cuotas_contrato(contrato_id: int) -> list[CuotaProgramada]:
    return list(
        CuotaProgramada.objects.filter(contrato_id=contrato_id)
        .select_related("pago")
        .order_by("numero", "id")
    )


def contar_eventos_recargo(
    contrato,
    *,
    fecha: date | None = None,
    cuotas_a_liquidar: list[CuotaProgramada] | tuple[CuotaProgramada, ...] | None = None,
    excluir_pago_id: int | None = None,
) -> tuple[int, Decimal, int, tuple[CuotaProgramada, ...]]:
    """
    Eventos de recargo pendientes.

    Si la cuota 21 se atrasa: ese recibo = solo la cuota.
    El recargo se cobra al pagar la 22 (u otra cuota posterior).
    """
    corte = fecha or timezone.localdate()
    param = parametro_recargo_activo()
    dias_gracia = int(param.dias_gracia) if param else 0
    unitario = (
        Decimal(param.monto_recargo or 0).quantize(Decimal("0.01"))
        if param
        else Decimal("0.00")
    )
    if unitario <= 0:
        return 0, Decimal("0.00"), dias_gracia, ()

    cuotas = _cuotas_contrato(contrato.pk)
    seleccion = list(cuotas_a_liquidar or ())
    ids_sel = {c.pk for c in seleccion}
    ultima_id = None
    if seleccion:
        ultima = max(seleccion, key=lambda c: (c.vence_en, c.numero, c.pk))
        ultima_id = ultima.pk
    else:
        proxima = next((x for x in cuotas if cuota_impaga(x)), None)
        if proxima is not None:
            ultima_id = proxima.pk

    generadoras: list[CuotaProgramada] = []
    # Cuotas anteriores a la «actual» que siguen impagas tras la gracia,
    # o que se liquidan en este mismo pago junto con una posterior.
    for c in cuotas:
        if ultima_id is not None and c.pk == ultima_id:
            continue
        if c.pk in ids_sel:
            if c.vence_en and corte > fecha_limite_gracia(c.vence_en, dias_gracia):
                generadoras.append(c)
            continue
        if cuota_genera_recargo(c, hoy=corte, dias_gracia=dias_gracia):
            generadoras.append(c)

    # Límite de secuencia: atrasos ya pagados solo de cuotas anteriores a la actual.
    antes_de_clave = None
    if seleccion:
        primera = min(seleccion, key=lambda c: (c.vence_en, c.numero, c.pk))
        antes_de_clave = _clave_cuota(primera)
    else:
        proxima = next((x for x in cuotas if cuota_impaga(x)), None)
        if proxima is not None:
            antes_de_clave = _clave_cuota(proxima)

    n_pagos_atraso = len(
        _pagos_cuota_con_atraso_en_ultima(
            contrato.pk,
            dias_gracia=dias_gracia,
            excluir_pago_id=excluir_pago_id,
            antes_de_clave=antes_de_clave,
        )
    )

    n_bruto = len(generadoras) + n_pagos_atraso
    pagado = monto_recargos_pagados(contrato.pk, excluir_pago_id=excluir_pago_id)
    cubiertos = int(pagado // unitario) if unitario > 0 else 0
    pendientes = max(0, n_bruto - cubiertos)
    monto = (unitario * pendientes).quantize(Decimal("0.01"))
    return pendientes, monto, dias_gracia, tuple(generadoras)


def resumen_cobro_contrato(
    contrato,
    *,
    hoy: date | None = None,
) -> CobroMes:
    """
    Próxima cuota pendiente + recargos que corresponden a atrasos anteriores
    (no el de la propia cuota que está por cobrarse en este mes).
    """
    corte = hoy or timezone.localdate()
    param = parametro_recargo_activo()
    dias_gracia = int(param.dias_gracia) if param else 0
    unitario = (
        (param.monto_recargo or Decimal("0"))
        if param
        else Decimal("0")
    )

    cuotas = _cuotas_contrato(contrato.pk)
    proxima = next((c for c in cuotas if cuota_impaga(c)), None)
    monto_cuota = proxima.monto if proxima else Decimal("0.00")

    pendientes, monto_recargo, _, generadoras = contar_eventos_recargo(
        contrato, fecha=corte, cuotas_a_liquidar=None
    )
    total = (monto_cuota + monto_recargo).quantize(Decimal("0.01"))

    if pendientes and proxima:
        nota = (
            f"Cuota #{proxima.numero} (${monto_cuota}) + "
            f"{pendientes} recargo(s) administrativo(s) (${monto_recargo}) "
            f"por atraso(s) anterior(es). "
            f"Gracia: {dias_gracia} día(s) tras el vencimiento."
        )
    elif proxima:
        nota = (
            f"Cuota #{proxima.numero}: ${monto_cuota} "
            f"(sin recargo; si esta cuota se atrasa, el recargo va en la siguiente)."
        )
    else:
        nota = "No hay cuotas pendientes."

    return CobroMes(
        cuota=proxima,
        monto_cuota=monto_cuota,
        monto_recargo=monto_recargo,
        cantidad_recargos=pendientes,
        monto_total=total,
        dias_gracia=dias_gracia,
        monto_unitario_recargo=unitario if isinstance(unitario, Decimal) else Decimal(unitario or 0),
        cuotas_que_generan_recargo=generadoras,
        nota=nota,
    )


def monto_recargo_para_liquidacion(
    contrato,
    *,
    fecha: date | None,
    cuotas_a_liquidar: list[CuotaProgramada] | tuple[CuotaProgramada, ...],
    excluir_pago_id: int | None = None,
) -> Decimal:
    """Recargo a incluir al registrar el pago de las cuotas marcadas."""
    _n, monto, _dias, _gens = contar_eventos_recargo(
        contrato,
        fecha=fecha,
        cuotas_a_liquidar=cuotas_a_liquidar,
        excluir_pago_id=excluir_pago_id,
    )
    return monto


def detalle_recargo_por_cuota(
    cuota: CuotaProgramada,
    *,
    hoy: date | None = None,
    dias_gracia: int = 0,
    monto_unitario: Decimal = Decimal("0"),
) -> dict:
    """Datos de fila para estado de cuenta."""
    corte = hoy or timezone.localdate()
    genera = cuota_genera_recargo(
        cuota, hoy=corte, dias_gracia=dias_gracia
    )
    limite = fecha_limite_gracia(cuota.vence_en, dias_gracia)
    return {
        "genera_recargo": genera,
        "fecha_limite_gracia": limite,
        "monto_recargo_unitario": monto_unitario if genera else Decimal("0"),
    }
