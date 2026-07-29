"""Estado de cuenta detallado por cliente / contrato (PDF imprimible)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from inmobiliaria.models import Contrato, CuotaProgramada, Pago
from inmobiliaria.recargo_administrativo import (
    detalle_recargo_por_cuota,
    parametro_recargo_activo,
    resumen_cobro_contrato,
)


def _filas_cuotas_contrato(contrato: Contrato, *, hoy, param) -> list[dict]:
    dias_gracia = int(param.dias_gracia) if param else 0
    monto_unitario = (param.monto_recargo if param else None) or Decimal("0")
    cobro = resumen_cobro_contrato(contrato, hoy=hoy)
    filas: list[dict] = []
    cuotas_qs = contrato.cuotas_programadas.select_related("pago").order_by("numero")
    for c in cuotas_qs:
        liquidada = c.estado == CuotaProgramada.Estado.PAGADA or c.pago_id is not None
        fecha_pago = None
        if liquidada:
            fecha_pago = (c.pago.fecha if c.pago_id else None) or c.pagado_en
        dias_tarde = None
        dias_impago = None
        if fecha_pago is not None:
            dias_tarde = max(0, (fecha_pago - c.vence_en).days)
        elif c.estado in (
            CuotaProgramada.Estado.PENDIENTE,
            CuotaProgramada.Estado.VENCIDA,
        ) and hoy > c.vence_en:
            dias_impago = (hoy - c.vence_en).days
        det = detalle_recargo_por_cuota(
            c, hoy=hoy, dias_gracia=dias_gracia, monto_unitario=monto_unitario
        )
        es_proxima = cobro.cuota is not None and cobro.cuota.pk == c.pk
        filas.append(
            {
                "cuota": c,
                "fecha_pago": fecha_pago,
                "dias_tarde_al_pagar": dias_tarde,
                "dias_impago_tras_venc": dias_impago,
                "pago_monto": c.pago.monto if c.pago_id else None,
                "pago_referencia": (
                    (c.pago.referencia or "").strip() or None if c.pago_id else None
                ),
                "genera_recargo": det["genera_recargo"],
                "fecha_limite_gracia": det["fecha_limite_gracia"],
                "es_proxima": es_proxima,
                "a_cobrar_total": cobro.monto_total if es_proxima else None,
                "a_cobrar_recargo": cobro.monto_recargo if es_proxima else None,
            }
        )
    return filas


def _resumen_financiero_contrato(contrato: Contrato) -> dict:
    pagos = contrato.pagos.all()
    qp = contrato.cuotas_programadas
    monto_plan = qp.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    monto_pagadas = (
        qp.filter(estado=CuotaProgramada.Estado.PAGADA).aggregate(t=Sum("monto"))["t"]
        or Decimal("0")
    )
    total_bruto = pagos.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    total_recargos = (
        pagos.filter(concepto=Pago.Concepto.MORA).aggregate(t=Sum("monto"))["t"]
        or Decimal("0")
    ) + (
        pagos.filter(concepto=Pago.Concepto.CUOTA).aggregate(
            t=Sum("monto_recargo_incluido")
        )["t"]
        or Decimal("0")
    )
    total_pagado = (total_bruto - total_recargos).quantize(Decimal("0.01"))
    saldo = (contrato.precio_final - total_pagado).quantize(Decimal("0.01"))
    return {
        "total_cuotas": qp.count(),
        "pagadas": qp.filter(estado=CuotaProgramada.Estado.PAGADA).count(),
        "pendientes": qp.filter(estado=CuotaProgramada.Estado.PENDIENTE).count(),
        "vencidas": qp.filter(estado=CuotaProgramada.Estado.VENCIDA).count(),
        "monto_plan_total": monto_plan,
        "monto_cuotas_pagadas": monto_pagadas,
        "monto_cuotas_por_pagar": monto_plan - monto_pagadas,
        "total_pagado": total_pagado,
        "total_recargos": total_recargos.quantize(Decimal("0.01")),
        "saldo_estimado": saldo,
        "pagos": list(pagos.order_by("fecha", "id")),
    }


def build_bloque_contrato(contrato: Contrato, *, hoy=None, param=None) -> dict:
    hoy = hoy or timezone.localdate()
    if param is None:
        param = parametro_recargo_activo()
    fin = _resumen_financiero_contrato(contrato)
    cobro = resumen_cobro_contrato(contrato, hoy=hoy)
    return {
        "contrato": contrato,
        "inmueble": contrato.inmueble,
        "proyecto": contrato.inmueble.proyecto if contrato.inmueble_id else None,
        "filas_cuotas": _filas_cuotas_contrato(contrato, hoy=hoy, param=param),
        "resumen": fin,
        "cobro_mes": cobro,
    }


def build_estado_cuenta_cliente_context(cliente, *, contratos_qs=None) -> dict:
    """Contexto completo para PDF de estado de cuenta por cliente."""
    from docs.services import branding_pdf_context

    hoy = timezone.localdate()
    param = parametro_recargo_activo()
    if contratos_qs is None:
        contratos_qs = (
            Contrato.objects.filter(cliente=cliente)
            .select_related("inmueble", "inmueble__proyecto", "vendedor_perfil")
            .order_by("-fecha_firma", "-pk")
        )
    else:
        contratos_qs = contratos_qs.select_related(
            "inmueble", "inmueble__proyecto", "vendedor_perfil"
        )

    bloques = [build_bloque_contrato(c, hoy=hoy, param=param) for c in contratos_qs]

    total_precio = sum((b["contrato"].precio_final for b in bloques), Decimal("0"))
    total_pagado = sum((b["resumen"]["total_pagado"] for b in bloques), Decimal("0"))
    total_saldo = sum((b["resumen"]["saldo_estimado"] for b in bloques), Decimal("0"))
    total_vencidas = sum((b["resumen"]["vencidas"] for b in bloques), 0)

    proy = None
    proyecto_nombre = ""
    if bloques:
        proy = bloques[0]["proyecto"]
        if proy is not None:
            proyecto_nombre = proy.nombre or ""

    brand = branding_pdf_context(proy)
    return {
        "cliente": cliente,
        "bloques": bloques,
        "hoy": hoy,
        "emitido_en": timezone.now(),
        "param_recargo": param,
        "proyecto": proy,
        "totales": {
            "contratos": len(bloques),
            "precio": total_precio.quantize(Decimal("0.01")),
            "pagado": total_pagado.quantize(Decimal("0.01")),
            "saldo": total_saldo.quantize(Decimal("0.01")),
            "vencidas": total_vencidas,
        },
        **brand,
        "proyecto_nombre": proyecto_nombre or brand.get("proyecto_nombre") or "",
    }
