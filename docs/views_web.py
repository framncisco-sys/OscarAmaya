from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from inmobiliaria.models import Contrato, Pago

from .models import DocumentoEmitido, DocumentoTipo
from .recibo_notificacion import ReciboNotificacionInfo, construir_url_whatsapp_recibo
from .services import (
    emitir_promesa_venta,
    emitir_recibo_comision_vendedor,
    emitir_recibo_ingreso,
)


def _alerta_html_recibo_emitido(
    *,
    doc_numero: str,
    url_pdf: str,
    wa_url: str | None,
    notif: ReciboNotificacionInfo,
) -> str:
    """HTML del aviso tras emitir recibo: compacto y en bloques."""
    if wa_url:
        acciones = format_html(
            '<p class="alert-recibo__actions">'
            '<a href="{}">Descargar PDF</a>'
            '<span class="alert-recibo__sep">·</span>'
            '<a href="{}" target="_blank" rel="noopener noreferrer">Abrir WhatsApp</a>'
            "</p>",
            url_pdf,
            wa_url,
        )
        if notif.whatsapp_pdf_por_api:
            detalle = mark_safe(
                '<p class="alert-recibo__meta">Correo: se envió copia con PDF si el cliente tiene email.</p>'
                '<p class="alert-recibo__meta">WhatsApp: el PDF también se entregó como documento (API).</p>'
            )
        elif notif.meta_solo_texto:
            detalle = mark_safe(
                '<p class="alert-recibo__meta">Correo: se envió copia con PDF si el cliente tiene email.</p>'
                '<p class="alert-recibo__meta alert-recibo__meta--warn">'
                "WhatsApp (Meta) solo entregó texto, no el archivo. Revise en el servidor: token, URL pública del PDF, "
                "MIME <code>application/pdf</code> o tamaño del archivo.</p>"
            )
        elif notif.meta_configurado:
            detalle = mark_safe(
                '<p class="alert-recibo__meta">Correo: se envió copia con PDF si el cliente tiene email.</p>'
                '<p class="alert-recibo__meta alert-recibo__meta--warn">'
                "WhatsApp (Meta) no pudo completar el envío. Revise la consola del servidor.</p>"
            )
        else:
            detalle = mark_safe(
                '<p class="alert-recibo__meta">Correo: se envió copia con PDF si el cliente tiene email.</p>'
            )
    else:
        acciones = format_html(
            '<p class="alert-recibo__actions"><a href="{}">Descargar PDF</a></p>',
            url_pdf,
        )
        detalle = mark_safe(
            '<p class="alert-recibo__meta">Correo: se envió copia con PDF si el cliente tiene email.</p>'
            '<p class="alert-recibo__meta">Agregue teléfono al cliente para generar el enlace de WhatsApp.</p>'
        )

    return format_html(
        '<div class="alert-recibo">'
        '<p class="alert-recibo__title">Recibo <strong>{}</strong> generado.</p>'
        "{}{}"
        "</div>",
        doc_numero,
        acciones,
        detalle,
    )


@login_required
def emitir_recibo_comision(request: HttpRequest, contrato_id: int) -> HttpResponse:
    contrato = get_object_or_404(
        Contrato.objects.select_related(
            "vendedor_perfil",
            "vendedor",
            "cliente",
            "inmueble",
            "inmueble__proyecto",
        ),
        pk=contrato_id,
    )
    try:
        doc = emitir_recibo_comision_vendedor(contrato=contrato, emitido_por=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("app:contrato_update", pk=contrato.pk)
    url_pdf = reverse("app:doc_download", args=[doc.id])
    messages.success(
        request,
        format_html(
            'Recibo de comisión <strong>{}</strong> generado. <a href="{}">Descargar PDF</a>.',
            doc.numero,
            url_pdf,
        ),
    )
    return redirect("app:contrato_list")


@login_required
def emitir_promesa(request: HttpRequest, contrato_id: int) -> HttpResponse:
    contrato = get_object_or_404(Contrato, pk=contrato_id)
    doc = emitir_promesa_venta(contrato=contrato, emitido_por=request.user)
    return redirect("app:doc_download", doc_id=doc.id)


@login_required
def emitir_recibo(request: HttpRequest, pago_id: int) -> HttpResponse:
    pago = get_object_or_404(Pago, pk=pago_id)
    doc, notif = emitir_recibo_ingreso(pago=pago, emitido_por=request.user)
    wa = construir_url_whatsapp_recibo(pago.contrato.cliente, doc, pago)
    url_pdf = reverse("app:doc_download", args=[doc.id])
    messages.success(
        request,
        _alerta_html_recibo_emitido(
            doc_numero=doc.numero,
            url_pdf=url_pdf,
            wa_url=wa,
            notif=notif,
        ),
    )
    return redirect("app:docs_list")


@login_required
def doc_download(request: HttpRequest, doc_id: int) -> HttpResponse:
    doc = get_object_or_404(DocumentoEmitido, pk=doc_id)
    if not doc.pdf_file:
        raise Http404("Documento sin PDF")
    safe_name = f"{doc.numero.replace('/', '-')}.pdf"
    return FileResponse(
        doc.pdf_file.open("rb"),
        as_attachment=True,
        filename=safe_name,
        content_type="application/pdf",
    )


@login_required
def docs_list(request: HttpRequest) -> HttpResponse:
    items = (
        DocumentoEmitido.objects.select_related("contrato", "pago", "vendedor")
        .order_by("-id")[:200]
    )
    from django.shortcuts import render

    return render(request, "app/docs_list.html", {"items": items})

