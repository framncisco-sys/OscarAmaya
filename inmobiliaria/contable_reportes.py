"""Reportes contables mensuales para inmobiliaria con financiamiento propio (El Salvador)."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Q, Sum
from django.utils import timezone

from inmobiliaria.contratos_acceso import (
    filtrar_contratos_queryset_por_vendedor,
    filtrar_pagos_queryset_por_vendedor,
)
from inmobiliaria.models import Contrato, CuotaProgramada, Pago, Proyecto
from inmobiliaria.pago_desglose import desglose_para_recibo

from core.marcas import MARCAS, SLUG_BIENES_RAICES, SLUG_DESARROLLOS


def proyecto_activo_contable() -> Proyecto | None:
    """Proyecto activo principal para cabecera de reportes contables."""
    return Proyecto.objects.filter(activo=True).order_by("nombre", "pk").first()


def contable_branding_context(*, pie_inmobiliaria: str) -> dict[str, Any]:
    """Logos corporativos + proyecto activo (misma línea visual que PDF estado de cuenta)."""
    proyecto = proyecto_activo_contable()
    des = MARCAS[SLUG_DESARROLLOS]
    br = MARCAS[SLUG_BIENES_RAICES]
    return {
        "proyecto": proyecto,
        "proyecto_nombre": (proyecto.nombre if proyecto else "Valle Alegre Residencial"),
        "logo_desarrollos_static": str(des["logo"]),
        "logo_bienes_static": str(br["logo"]),
        "proyecto_logo_fallback": "logo_valle_alegre.png",
        "empresa_nombre": str(des["nombre"]),
        "pie_inmobiliaria": pie_inmobiliaria,
        "emitido_en": timezone.localtime(),
    }


def parse_mes_param(raw: str | None, *, hoy: date | None = None) -> tuple[int, int, date, date]:
    """Parámetro ?mes=YYYY-MM → (año, mes, primer_día, último_día)."""
    hoy = hoy or timezone.localdate()
    raw = (raw or "").strip()
    if len(raw) == 7 and raw[4] == "-":
        try:
            y, m = int(raw[:4]), int(raw[5:7])
            if 1 <= m <= 12:
                ultimo = calendar.monthrange(y, m)[1]
                return y, m, date(y, m, 1), date(y, m, ultimo)
        except ValueError:
            pass
    return hoy.year, hoy.month, date(hoy.year, hoy.month, 1), date(
        hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1]
    )


def mes_param_str(anio: int, mes: int) -> str:
    return f"{anio:04d}-{mes:02d}"


def _pagos_mes_validados(user, inicio: date, fin: date):
    qs = (
        Pago.objects.select_related(
            "contrato",
            "contrato__cliente",
            "contrato__inmueble",
            "contrato__inmueble__proyecto",
        )
        .filter(
            fecha__gte=inicio,
            fecha__lte=fin,
        )
        .exclude(validacion_abono=Pago.ValidacionAbono.RECHAZADO)
        .order_by("fecha", "id")
    )
    qs = filtrar_pagos_queryset_por_vendedor(qs, user)
    # Solo abonos confirmados en cuenta (contabilidad).
    qs = qs.filter(
        Q(validacion_abono=Pago.ValidacionAbono.VALIDADO)
        | Q(validacion_abono=Pago.ValidacionAbono.NO_APLICA)
    )
    return qs


def build_libro_ventas(user, anio: int, mes: int) -> dict[str, Any]:
    inicio, fin = parse_mes_param(mes_param_str(anio, mes))[2:]
    filas = []
    total_gravado = Decimal("0.00")
    total_iva = Decimal("0.00")
    for p in _pagos_mes_validados(user, inicio, fin):
        contrato = p.contrato
        iva_contrato = contrato.desglose_iva_monto or Decimal("0.00")
        # Referencia IVA proporcional al pago sobre precio final (estimado contable).
        prop = Decimal("0.00")
        if contrato.precio_final and contrato.precio_final > 0 and iva_contrato > 0:
            prop = (p.monto / contrato.precio_final * iva_contrato).quantize(Decimal("0.01"))
        gravado = (p.monto - prop).quantize(Decimal("0.01"))
        filas.append(
            {
                "fecha": p.fecha,
                "comprobante": p.referencia.strip() or f"REC-{p.pk}",
                "cliente": str(contrato.cliente),
                "contrato": contrato.numero,
                "concepto": p.get_concepto_display(),
                "monto": p.monto,
                "gravado": gravado,
                "iva": prop,
            }
        )
        total_gravado += gravado
        total_iva += prop
    return {
        "filas": filas,
        "total_monto": sum((f["monto"] for f in filas), Decimal("0")).quantize(Decimal("0.01")),
        "total_gravado": total_gravado.quantize(Decimal("0.01")),
        "total_iva": total_iva.quantize(Decimal("0.01")),
        "inicio": inicio,
        "fin": fin,
    }


def build_ingresos_mes(user, anio: int, mes: int) -> dict[str, Any]:
    inicio, fin = parse_mes_param(mes_param_str(anio, mes))[2:]
    filas_pago = list(_pagos_mes_validados(user, inicio, fin))
    por_concepto: dict[str, Decimal] = {}
    total_cuotas = Decimal("0.00")
    total_capital = Decimal("0.00")
    total_interes = Decimal("0.00")
    total_recargo = Decimal("0.00")
    total_otros = Decimal("0.00")

    for p in filas_pago:
        lbl = p.get_concepto_display()
        por_concepto[lbl] = por_concepto.get(lbl, Decimal("0.00")) + p.monto
        if p.concepto == Pago.Concepto.CUOTA:
            d = desglose_para_recibo(p)
            total_cuotas += d.monto_cuotas
            total_capital += d.monto_abono_capital
            total_recargo += d.monto_recargo
            # Interés estimado: monto cuota menos abono capital (si cuota incluye interés).
            interes_est = max(Decimal("0.00"), (p.monto - d.monto_cuotas - d.monto_recargo - d.monto_abono_capital))
            total_interes += interes_est
        elif p.concepto == Pago.Concepto.ABONO_CAPITAL:
            total_capital += p.monto
        elif p.concepto in (Pago.Concepto.MORA,):
            total_recargo += p.monto
        else:
            total_otros += p.monto

    total_recibido = sum((p.monto for p in filas_pago), Decimal("0")).quantize(Decimal("0.01"))
    return {
        "filas_concepto": sorted(por_concepto.items(), key=lambda x: x[0]),
        "total_recibido": total_recibido,
        "total_cuotas": total_cuotas.quantize(Decimal("0.01")),
        "total_capital": total_capital.quantize(Decimal("0.01")),
        "total_interes": total_interes.quantize(Decimal("0.01")),
        "total_recargo": total_recargo.quantize(Decimal("0.01")),
        "total_otros": total_otros.quantize(Decimal("0.01")),
        "inicio": inicio,
        "fin": fin,
        "n_comprobantes": len(filas_pago),
    }


def build_cuentas_por_cobrar(user) -> dict[str, Any]:
    hoy = timezone.localdate()
    qs = Contrato.objects.select_related("cliente", "inmueble", "inmueble__proyecto").filter(
        estado=Contrato.Estado.ACTIVO
    )
    qs = filtrar_contratos_queryset_por_vendedor(qs, user)
    buckets = {
        "al_dia": [],
        "1_30": [],
        "31_60": [],
        "61_90": [],
        "91_mas": [],
    }
    total_pendiente = Decimal("0.00")

    for c in qs:
        cuotas = c.cuotas_programadas.filter(
            estado__in=[
                CuotaProgramada.Estado.PENDIENTE,
                CuotaProgramada.Estado.VENCIDA,
            ],
            pago__isnull=True,
        ).order_by("vence_en")
        if not cuotas.exists():
            continue
        primera = cuotas.first()
        assert primera is not None
        dias = max(0, (hoy - primera.vence_en).days) if hoy > primera.vence_en else 0
        saldo = cuotas.aggregate(t=Sum("monto"))["t"] or Decimal("0.00")
        total_pendiente += saldo
        fila = {
            "contrato": c,
            "cliente": c.cliente,
            "dias_atraso": dias,
            "saldo_pendiente": saldo,
            "cuotas_pendientes": cuotas.count(),
            "proximo_vencimiento": primera.vence_en,
        }
        if dias == 0:
            buckets["al_dia"].append(fila)
        elif dias <= 30:
            buckets["1_30"].append(fila)
        elif dias <= 60:
            buckets["31_60"].append(fila)
        elif dias <= 90:
            buckets["61_90"].append(fila)
        else:
            buckets["91_mas"].append(fila)

    for lst in buckets.values():
        lst.sort(key=lambda x: (-x["dias_atraso"], str(x["cliente"])))

    return {
        "buckets": buckets,
        "total_pendiente": total_pendiente.quantize(Decimal("0.01")),
        "hoy": hoy,
        "n_clientes": sum(len(v) for v in buckets.values()),
    }


def build_estado_capital_intereses(user, anio: int, mes: int) -> dict[str, Any]:
    inicio, fin = parse_mes_param(mes_param_str(anio, mes))[2:]
    filas = []
    for p in _pagos_mes_validados(user, inicio, fin):
        d = desglose_para_recibo(p)
        capital = Decimal("0.00")
        interes = Decimal("0.00")
        if p.concepto == Pago.Concepto.CUOTA:
            capital = d.monto_cuotas + d.monto_abono_capital
            interes = max(
                Decimal("0.00"),
                (p.monto - capital - d.monto_recargo).quantize(Decimal("0.01")),
            )
        elif p.concepto == Pago.Concepto.ABONO_CAPITAL:
            capital = p.monto
        elif p.concepto not in (Pago.Concepto.MORA,):
            capital = p.monto
        filas.append(
            {
                "pago": p,
                "cliente": p.contrato.cliente,
                "contrato": p.contrato,
                "capital": capital,
                "interes": interes,
                "recargo": d.monto_recargo if p.concepto == Pago.Concepto.CUOTA else (
                    p.monto if p.concepto == Pago.Concepto.MORA else Decimal("0.00")
                ),
                "total": p.monto,
            }
        )

    total_cap = sum((f["capital"] for f in filas), Decimal("0")).quantize(Decimal("0.01"))
    total_int = sum((f["interes"] for f in filas), Decimal("0")).quantize(Decimal("0.01"))
    return {
        "filas": filas,
        "total_capital": total_cap,
        "total_interes": total_int,
        "total_recibido": sum((f["total"] for f in filas), Decimal("0")).quantize(Decimal("0.01")),
        "inicio": inicio,
        "fin": fin,
    }
