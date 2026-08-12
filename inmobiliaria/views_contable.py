"""Vistas web — módulo Contable (reportes mensuales)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from inmobiliaria.contable_export import (
    contable_pdf_context,
    respuesta_pdf,
    xlsx_cuentas_por_cobrar,
    xlsx_estado_capital,
    xlsx_ingresos_mes,
    xlsx_libro_ventas,
)
from inmobiliaria.contable_reportes import (
    build_cuentas_por_cobrar,
    build_estado_capital_intereses,
    build_ingresos_mes,
    build_libro_ventas,
    contable_branding_context,
    mes_param_str,
    parse_mes_param,
)
from usuarios.roles import puede_ver_reportes_contables


def _mes_context(request: HttpRequest) -> dict:
    anio, mes, inicio, fin = parse_mes_param(request.GET.get("mes"))
    return {
        "mes_anio": anio,
        "mes_num": mes,
        "mes_valor": mes_param_str(anio, mes),
        "mes_inicio": inicio,
        "mes_fin": fin,
    }


def _denegar_contable(request: HttpRequest) -> HttpResponse | None:
    if not puede_ver_reportes_contables(request.user):
        return render(
            request,
            "app/contable/sin_acceso.html",
            {"page_title": "Contable"},
            status=403,
        )
    return None


def _brand(pie: str) -> dict:
    return contable_branding_context(pie_inmobiliaria=pie)


def _export_fmt(request: HttpRequest) -> str:
    return (request.GET.get("export") or "").strip().lower()


def _cxp_secciones(buckets: dict) -> list[tuple[str, list]]:
    return [
        ("Al día", buckets["al_dia"]),
        ("1 – 30 días de atraso", buckets["1_30"]),
        ("31 – 60 días de atraso", buckets["31_60"]),
        ("61 – 90 días de atraso", buckets["61_90"]),
        ("Más de 90 días", buckets["91_mas"]),
    ]


@login_required
def contable_libro_ventas(request: HttpRequest) -> HttpResponse:
    denied = _denegar_contable(request)
    if denied:
        return denied
    ctx = _mes_context(request)
    data = build_libro_ventas(request.user, ctx["mes_anio"], ctx["mes_num"])
    pie = "Reporte contable · Libro de Ventas (IVA)"
    full = {
        "page_title": "Libro de Ventas (IVA)",
        "page_meta": (
            "Listado de comprobantes y recibos emitidos en el mes por cuotas, primas "
            "y mantenimiento. Base para la declaración mensual de IVA (DGII)."
        ),
        **ctx,
        **data,
        **_brand(pie),
    }
    fmt = _export_fmt(request)
    if fmt == "pdf":
        return respuesta_pdf(
            template_name="docs/contable/libro_ventas_pdf.html",
            context=contable_pdf_context(pie_inmobiliaria=pie, **data),
            filename_base=f"libro_ventas_iva_{data['inicio'].strftime('%Y%m')}",
        )
    if fmt in ("xlsx", "excel"):
        return xlsx_libro_ventas(data)
    return render(request, "app/contable/libro_ventas.html", full)


@login_required
def contable_ingresos_mes(request: HttpRequest) -> HttpResponse:
    denied = _denegar_contable(request)
    if denied:
        return denied
    ctx = _mes_context(request)
    data = build_ingresos_mes(request.user, ctx["mes_anio"], ctx["mes_num"])
    pie = "Reporte contable · Ingresos del mes (Pago a Cuenta)"
    full = {
        "page_title": "Reporte de Ingresos del Mes",
        "page_meta": (
            "Resumen del dinero efectivamente recibido en el mes por cuotas e intereses. "
            "Para calcular y declarar el Pago a Cuenta del Impuesto sobre la Renta."
        ),
        **ctx,
        **data,
        **_brand(pie),
    }
    fmt = _export_fmt(request)
    if fmt == "pdf":
        return respuesta_pdf(
            template_name="docs/contable/ingresos_mes_pdf.html",
            context=contable_pdf_context(pie_inmobiliaria=pie, **data),
            filename_base=f"ingresos_mes_{data['inicio'].strftime('%Y%m')}",
        )
    if fmt in ("xlsx", "excel"):
        return xlsx_ingresos_mes(data)
    return render(request, "app/contable/ingresos_mes.html", full)


@login_required
def contable_cuentas_por_cobrar(request: HttpRequest) -> HttpResponse:
    denied = _denegar_contable(request)
    if denied:
        return denied
    data = build_cuentas_por_cobrar(request.user)
    secciones = _cxp_secciones(data["buckets"])
    pie = "Reporte contable · Cuentas por cobrar (antigüedad)"
    full = {
        "page_title": "Cuentas por Cobrar",
        "page_meta": (
            "Cartera de clientes por antigüedad de saldos: al día, 30, 60, 90+ días. "
            "Para provisiones contables y seguimiento de cobro."
        ),
        "secciones": secciones,
        **data,
        **_brand(pie),
    }
    fmt = _export_fmt(request)
    if fmt == "pdf":
        return respuesta_pdf(
            template_name="docs/contable/cuentas_por_cobrar_pdf.html",
            context=contable_pdf_context(pie_inmobiliaria=pie, secciones=secciones, **data),
            filename_base=f"cuentas_por_cobrar_{data['hoy'].strftime('%Y%m%d')}",
        )
    if fmt in ("xlsx", "excel"):
        return xlsx_cuentas_por_cobrar(data)
    return render(request, "app/contable/cuentas_por_cobrar.html", full)


@login_required
def contable_estado_capital_intereses(request: HttpRequest) -> HttpResponse:
    denied = _denegar_contable(request)
    if denied:
        return denied
    ctx = _mes_context(request)
    data = build_estado_capital_intereses(request.user, ctx["mes_anio"], ctx["mes_num"])
    pie = "Reporte contable · Capital e intereses por cliente"
    full = {
        "page_title": "Estado de Cuenta — Capital e Intereses",
        "page_meta": (
            "Historial de pagos del período con desglose de capital, intereses y recargos. "
            "Para clasificación contable y auditoría de la deuda por comprador."
        ),
        **ctx,
        **data,
        **_brand(pie),
    }
    fmt = _export_fmt(request)
    if fmt == "pdf":
        return respuesta_pdf(
            template_name="docs/contable/estado_capital_pdf.html",
            context=contable_pdf_context(pie_inmobiliaria=pie, **data),
            filename_base=f"capital_intereses_{data['inicio'].strftime('%Y%m')}",
        )
    if fmt in ("xlsx", "excel"):
        return xlsx_estado_capital(data)
    return render(request, "app/contable/estado_capital_intereses.html", full)
