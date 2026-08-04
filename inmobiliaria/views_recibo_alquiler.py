"""Recibo de comisión del módulo de alquileres (independiente de ventas, contratos y casa nueva/usada)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html

from docs.services import emitir_recibo_comision_alquiler

from .forms_recibo_alquiler import (
    ReciboComisionAlquilerForm,
    nombre_beneficiario_recibo_alquiler,
    renta_mensual_alquiler,
)
from .models import AsesorAlquiler, Inmueble


def _asesores_catalogo_map() -> dict[str, dict]:
    return {
        str(a.pk): {
            "nombre": a.nombre_completo,
            "pct": str(a.comision_arrendamiento_pct),
        }
        for a in AsesorAlquiler.objects.filter(activo=True).order_by("apellidos", "nombres")
    }


def _segmento_alquiler_inmueble(inmueble: Inmueble) -> str | None:
    if not inmueble.en_alquiler:
        return None
    if inmueble.tipo == Inmueble.Tipo.LOCAL:
        return "local"
    if inmueble.tipo in (Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA):
        return "casa"
    return None


def _inmuebles_alquiler_queryset(segmento: str):
    if segmento == "local":
        return (
            Inmueble.objects.select_related("proyecto", "detalle_local_alquiler")
            .filter(tipo=Inmueble.Tipo.LOCAL, en_alquiler=True)
            .order_by("proyecto__nombre", "codigo")
        )
    if segmento == "casa":
        return (
            Inmueble.objects.select_related("proyecto", "detalle_casa_alquiler")
            .filter(
                tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
                en_alquiler=True,
            )
            .order_by("proyecto__nombre", "codigo")
        )
    return None


@login_required
def recibo_comision_alquiler_elegir(request: HttpRequest, segmento: str) -> HttpResponse:
    qs = _inmuebles_alquiler_queryset(segmento)
    if qs is None:
        raise Http404("Segmento de alquiler no válido.")
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    for inmueble in page:
        inmueble.renta_ref = renta_mensual_alquiler(inmueble)
    if segmento == "local":
        page_title = "Recibo de comisión — alquiler de local"
        page_meta = (
            "Módulo de alquileres. Elija el local, defina la comisión y genere el PDF."
        )
    else:
        page_title = "Recibo de comisión — casa en alquiler"
        page_meta = (
            "Módulo de alquileres. Elija la casa en alquiler, defina la comisión y genere el PDF."
        )
    return render(
        request,
        "app/recibo_alquiler_elegir.html",
        {
            "items": page,
            "page_obj": page,
            "segmento": segmento,
            "page_title": page_title,
            "page_meta": page_meta,
        },
    )


@login_required
def emitir_recibo_comision_alquiler_view(
    request: HttpRequest, inmueble_id: int
) -> HttpResponse:
    inmueble = get_object_or_404(
        Inmueble.objects.select_related("proyecto"),
        pk=inmueble_id,
        en_alquiler=True,
    )
    segmento = _segmento_alquiler_inmueble(inmueble)
    if segmento not in ("local", "casa"):
        messages.error(
            request,
            "Este inmueble no pertenece al módulo de alquileres (debe estar marcado en alquiler).",
        )
        return redirect("app:index")

    if request.method == "POST":
        form = ReciboComisionAlquilerForm(request.POST, inmueble=inmueble)
        if form.is_valid():
            try:
                doc = emitir_recibo_comision_alquiler(
                    inmueble=inmueble,
                    emitido_por=request.user,
                    vendedor_nombre=nombre_beneficiario_recibo_alquiler(form.cleaned_data),
                    asesor_alquiler=form.cleaned_data.get("asesor_perfil"),
                    monto_comision=form.cleaned_data["monto_comision"],
                    comision_porcentaje=form.cleaned_data.get("comision_porcentaje"),
                    concepto=form.cleaned_data.get("concepto") or "",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(
                    "app:emitir_recibo_comision_alquiler",
                    inmueble_id=inmueble.pk,
                )
            url_pdf = reverse("app:doc_download", args=[doc.id])
            messages.success(
                request,
                format_html(
                    'Recibo de comisión (alquiler) <strong>{}</strong> generado. '
                    '<a href="{}">Descargar PDF</a>.',
                    doc.numero,
                    url_pdf,
                ),
            )
            return redirect("app:doc_download", doc_id=doc.id)
    else:
        form = ReciboComisionAlquilerForm(inmueble=inmueble)

    return render(
        request,
        "app/recibo_alquiler_preparar.html",
        {
            "form": form,
            "inmueble": inmueble,
            "renta_mensual": renta_mensual_alquiler(inmueble),
            "cancel_url": reverse("app:recibo_comision_hub"),
            "cancel_label": "Recibos de comisión",
            "form_title": f"Recibo de comisión (alquiler) · {inmueble.codigo}",
            "segmento": segmento,
            "vendedores_catalogo": _asesores_catalogo_map(),
        },
    )


@login_required
def recibo_comision_hub(request: HttpRequest) -> HttpResponse:
    """Centro de recibos de comisión al vendedor/asesor (alquiler y venta)."""
    from inmobiliaria.views_web import _bloquear_si_desarrollos

    bloqueo = _bloquear_si_desarrollos(request)
    if bloqueo:
        return bloqueo
    return render(
        request,
        "app/recibo_comision_hub.html",
        {
            "page_title": "Recibo de comisión al asesor",
            "page_meta": (
                "Liquidación de comisión al asesor de ventas o de alquiler: nombre del beneficiario, "
                "monto en USD, porcentaje de referencia y concepto impreso en el PDF."
            ),
        },
    )
