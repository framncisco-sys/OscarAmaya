from __future__ import annotations

import logging
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from inmobiliaria.contratos_acceso import (
    aplica_restriccion_contratos_por_vendedor,
    filtrar_contratos_queryset_por_vendedor,
    usuario_puede_ver_contrato,
    vendedor_catalogo_activo_vinculado,
)
from inmobiliaria.models import Contrato, Inmueble, Pago

from .forms import ReciboComisionVendedorForm
from .models import DocumentoEmitido, DocumentoTipo
from .recibo_notificacion import ReciboNotificacionInfo, construir_url_whatsapp_recibo
from .services import (
    emitir_promesa_venta,
    emitir_recibo_comision_vendedor,
    emitir_recibo_ingreso,
    regenerar_pdf_y_persistir,
)

logger = logging.getLogger(__name__)


def _contrato_desde_documento(doc: DocumentoEmitido) -> Contrato | None:
    if doc.contrato_id:
        return doc.contrato
    if doc.pago_id:
        return doc.pago.contrato
    return None


def _documento_emitido_queryset_para_descarga():
    return DocumentoEmitido.objects.select_related(
        "contrato",
        "contrato__cliente",
        "contrato__inmueble",
        "contrato__inmueble__proyecto",
        "contrato__inmueble__poligono",
        "contrato__vendedor",
        "contrato__vendedor_perfil",
        "pago",
        "pago__contrato",
        "pago__contrato__cliente",
        "pago__contrato__inmueble",
        "pago__contrato__inmueble__proyecto",
        "vendedor",
    )


def _html_estado_correo_recibo(notif: ReciboNotificacionInfo) -> str:
    if notif.correo_entrega_real:
        return (
            '<p class="alert-recibo__meta">Correo: el PDF se envió al email del cliente vía SMTP.</p>'
        )
    if notif.correo_enviado:
        return (
            '<p class="alert-recibo__meta alert-recibo__meta--warn">'
            "Correo: el servidor <strong>no</strong> está usando SMTP real (falta <code>EMAIL_HOST</code> o usa backend de consola). "
            "El cliente <strong>no</strong> recibió el correo. Configure SMTP en App Platform: "
            "<code>EMAIL_HOST</code>, <code>EMAIL_PORT</code>, <code>EMAIL_HOST_USER</code>, "
            "<code>EMAIL_HOST_PASSWORD</code>, <code>DEFAULT_FROM_EMAIL</code> (véase <code>.env.example</code>).</p>"
        )
    return (
        '<p class="alert-recibo__meta alert-recibo__meta--warn">'
        "Correo: no se envió (confirme que el cliente tenga email o revise los logs del servidor).</p>"
    )


def _html_whatsapp_enlace_manual() -> str:
    return (
        '<p class="alert-recibo__meta">'
        "<strong>Abrir WhatsApp</strong> usa <code>wa.me</code>: solo abre el chat con texto; "
        "<strong>no adjunta el PDF</strong> (así funciona WhatsApp). "
        "Para que el mensaje incluya un enlace de descarga HTTPS al PDF: "
        "<code>PUBLIC_BASE_URL=https://su-app.ondigitalocean.app</code> y, en producción, "
        "<code>DJANGO_SERVE_MEDIA_PUBLIC=1</code> (sirve <code>/media/</code> sin login; evalúe privacidad). "
        "Alternativa: API Meta/Twilio para enviar el PDF como documento.</p>"
    )


def _alerta_html_recibo_emitido(
    *,
    doc_numero: str,
    url_pdf: str,
    wa_url: str | None,
    notif: ReciboNotificacionInfo,
) -> str:
    """HTML del aviso tras emitir recibo: compacto y en bloques."""
    bloque_correo = _html_estado_correo_recibo(notif)

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
        partes = [bloque_correo]
        if notif.whatsapp_pdf_por_api:
            partes.append(
                '<p class="alert-recibo__meta">WhatsApp: el PDF se entregó como documento (API Meta o Twilio).</p>'
            )
        elif notif.meta_solo_texto:
            partes.append(
                '<p class="alert-recibo__meta alert-recibo__meta--warn">'
                "WhatsApp (Meta) solo entregó texto, no el archivo. Revise token, "
                "<code>PUBLIC_BASE_URL</code> HTTPS, MIME <code>application/pdf</code> o tamaño del PDF."
                "</p>"
            )
        elif notif.meta_configurado:
            partes.append(
                '<p class="alert-recibo__meta alert-recibo__meta--warn">'
                "WhatsApp (Meta) no pudo completar el envío. Revise la consola del servidor."
                "</p>"
            )
        else:
            partes.append(_html_whatsapp_enlace_manual())
        detalle = mark_safe("".join(partes))
    else:
        acciones = format_html(
            '<p class="alert-recibo__actions"><a href="{}">Descargar PDF</a></p>',
            url_pdf,
        )
        detalle = mark_safe(
            bloque_correo
            + '<p class="alert-recibo__meta">Agregue teléfono al cliente para generar el enlace de WhatsApp.</p>'
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


def _contrato_para_recibo_comision(contrato_id: int, user):
    base = Contrato.objects.select_related(
        "vendedor_perfil",
        "vendedor",
        "cliente",
        "inmueble",
        "inmueble__proyecto",
    )
    return get_object_or_404(
        filtrar_contratos_queryset_por_vendedor(base, user),
        pk=contrato_id,
    )


def _contratos_venta_queryset(user):
    """Contratos de venta (lotes/casas), no alquiler — para comisión al vendedor."""
    qs = (
        Contrato.objects.select_related(
            "cliente",
            "inmueble",
            "inmueble__proyecto",
            "vendedor_perfil",
            "vendedor",
        )
        .filter(inmueble__en_alquiler=False)
        .order_by("-fecha_firma", "-id")
    )
    return filtrar_contratos_queryset_por_vendedor(qs, user)


def _contratos_casa_venta_queryset(user):
    """Compat: casas de venta; el listado principal usa todos los de venta."""
    return _contratos_venta_queryset(user).filter(
        inmueble__tipo__in=(Inmueble.Tipo.CASA_NUEVA, Inmueble.Tipo.CASA_SEGUNDA),
    )


def _cancel_url_recibo_comision(contrato: Contrato) -> tuple[str, str]:
    return reverse("app:recibo_comision_hub"), "Recibos de comisión al vendedor"


@login_required
def recibo_comision_casa_venta_elegir(request: HttpRequest) -> HttpResponse:
    """Elige contrato de venta para emitir recibo de comisión al vendedor."""
    from inmobiliaria.comision_vendedor import (
        prefetch_pagos_para_comision,
        requisitos_comision_venta,
    )

    qs = prefetch_pagos_para_comision(_contratos_venta_queryset(request.user))
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    for contrato in page:
        contrato.monto_comision_ref = contrato.monto_comision_efectivo()
        contrato.req_comision = requisitos_comision_venta(contrato)
    return render(
        request,
        "app/recibo_comision_casa_venta_elegir.html",
        {
            "items": page,
            "page_obj": page,
            "page_title": "Recibo de comisión — venta",
            "page_meta": (
                "1) Vendedor con su comisión en el contrato · "
                "2) Reserva y prima pagadas y validadas en cuenta · "
                "3) Generar el recibo de comisión de venta."
            ),
        },
    )


@login_required
def emitir_recibo_comision(request: HttpRequest, contrato_id: int) -> HttpResponse:
    from inmobiliaria.comision_vendedor import requisitos_comision_venta

    contrato = _contrato_para_recibo_comision(contrato_id, request.user)
    req = requisitos_comision_venta(contrato)
    nombre_v = req.vendedor_nombre

    if request.method == "POST":
        if not req.puede_emitir:
            messages.error(
                request,
                "Aún no se puede generar la comisión: " + " ".join(req.motivos),
            )
            return redirect("app:emitir_recibo_comision", contrato_id=contrato.pk)
        form = ReciboComisionVendedorForm(request.POST, contrato=contrato)
        if form.is_valid():
            try:
                doc = emitir_recibo_comision_vendedor(
                    contrato=contrato,
                    emitido_por=request.user,
                    monto_comision=form.cleaned_data["monto_comision"],
                    comision_porcentaje=form.cleaned_data.get("comision_porcentaje"),
                    concepto=form.cleaned_data.get("concepto") or "",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("app:emitir_recibo_comision", contrato_id=contrato.pk)
            url_pdf = reverse("app:doc_download", args=[doc.id])
            messages.success(
                request,
                format_html(
                    'Recibo de comisión al vendedor <strong>{}</strong> generado. '
                    '<a href="{}">Descargar PDF</a>.',
                    doc.numero,
                    url_pdf,
                ),
                extra_tags="allow_html",
            )
            return redirect("app:doc_download", doc_id=doc.id)
    else:
        form = ReciboComisionVendedorForm(contrato=contrato)

    monto_sugerido = contrato.monto_comision_efectivo()
    cancel_url, cancel_label = _cancel_url_recibo_comision(contrato)
    return render(
        request,
        "app/recibo_comision_preparar.html",
        {
            "form": form,
            "contrato": contrato,
            "vendedor_nombre": nombre_v or "— (sin vendedor)",
            "monto_sugerido": monto_sugerido,
            "precio_final": contrato.precio_final,
            "form_title": "Recibo de comisión al vendedor",
            "cancel_url": cancel_url,
            "cancel_label": cancel_label,
            "req_comision": req,
            "puede_emitir_comision": req.puede_emitir,
        },
    )


@login_required
def emitir_promesa(request: HttpRequest, contrato_id: int) -> HttpResponse:
    contrato = get_object_or_404(
        filtrar_contratos_queryset_por_vendedor(Contrato.objects.all(), request.user),
        pk=contrato_id,
    )
    doc = emitir_promesa_venta(contrato=contrato, emitido_por=request.user)
    return redirect("app:doc_download", doc_id=doc.id)


@login_required
def emitir_recibo(request: HttpRequest, pago_id: int) -> HttpResponse:
    pago = get_object_or_404(
        Pago.objects.select_related("contrato"),
        pk=pago_id,
    )
    if not usuario_puede_ver_contrato(request.user, pago.contrato):
        raise Http404("Pago no disponible")
    if pago.pendiente_validacion_gerente:
        messages.error(
            request,
            "Este abono (reserva, prima, cuota o abono a capital) aún no está validado por gerencia. "
            "No se puede emitir el recibo ni notificar al cliente hasta confirmar el depósito en cuenta.",
        )
        return redirect("app:pago_list")
    if pago.validacion_abono == Pago.ValidacionAbono.RECHAZADO:
        messages.error(
            request,
            "Este abono fue rechazado por gerencia. No se emite recibo al cliente.",
        )
        return redirect("app:pago_list")
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
        extra_tags="allow_html",
    )
    return redirect("app:docs_list")


@login_required
def doc_download(request: HttpRequest, doc_id: int) -> HttpResponse:
    doc = get_object_or_404(_documento_emitido_queryset_para_descarga(), pk=doc_id)
    c_perm = _contrato_desde_documento(doc)
    if c_perm is not None and not usuario_puede_ver_contrato(request.user, c_perm):
        raise Http404("Documento no disponible")
    if (
        c_perm is None
        and doc.tipo == DocumentoTipo.RECIBO_COMISION_VENDEDOR
        and doc.vendedor_id
        and aplica_restriccion_contratos_por_vendedor(request.user)
    ):
        vc = vendedor_catalogo_activo_vinculado(request.user)
        if vc is None or doc.vendedor_id != vc.pk:
            raise Http404("Documento no disponible")
    if not doc.pdf_file or not doc.pdf_file.name:
        raise Http404("Documento sin PDF")
    safe_name = f"{doc.numero.replace('/', '-')}.pdf"
    storage = doc.pdf_file.storage
    path = doc.pdf_file.name
    if storage.exists(path):
        try:
            fh = doc.pdf_file.open("rb")
        except FileNotFoundError:
            logger.warning(
                "El almacenamiento indicó archivo existente pero no se pudo abrir; se regenera (doc_id=%s).",
                doc.id,
            )
        else:
            return FileResponse(
                fh,
                as_attachment=True,
                filename=safe_name,
                content_type="application/pdf",
            )
    logger.warning(
        "PDF ausente en almacenamiento; se regenera desde la BD (doc_id=%s path=%s).",
        doc.id,
        path,
    )
    try:
        pdf_bytes = regenerar_pdf_y_persistir(doc)
    except ValueError as exc:
        raise Http404(str(exc)) from exc
    return FileResponse(
        BytesIO(pdf_bytes),
        as_attachment=True,
        filename=safe_name,
        content_type="application/pdf",
    )


@login_required
def docs_list(request: HttpRequest) -> HttpResponse:
    items = DocumentoEmitido.objects.select_related(
        "contrato", "pago", "pago__contrato", "vendedor"
    ).order_by("-id")
    if aplica_restriccion_contratos_por_vendedor(request.user):
        vc = vendedor_catalogo_activo_vinculado(request.user)
        allowed = filtrar_contratos_queryset_por_vendedor(Contrato.objects.all(), request.user)
        q_vis = Q(contrato__in=allowed) | Q(pago__contrato__in=allowed)
        if vc is not None:
            q_vis |= Q(vendedor_id=vc.pk, tipo=DocumentoTipo.RECIBO_COMISION_VENDEDOR)
        items = items.filter(q_vis).distinct()
    items = items[:200]
    from django.shortcuts import render

    return render(request, "app/docs_list.html", {"items": items})

