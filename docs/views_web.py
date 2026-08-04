from __future__ import annotations

import logging
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from inmobiliaria.contratos_acceso import (
    aplica_restriccion_contratos_por_vendedor,
    filtrar_contratos_queryset_por_vendedor,
    filtrar_documentos_queryset_por_vendedor,
    usuario_puede_ver_contrato,
    usuario_puede_ver_documento,
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
            '<p class="alert-recibo__meta">Correo: el PDF se enviÃ³ al email del cliente.</p>'
        )
    if notif.correo_enviado:
        return (
            '<p class="alert-recibo__meta alert-recibo__meta--warn">'
            "Correo: el servidor no estÃ¡ usando SMTP real; el cliente puede no haber recibido el email. "
            "Revise <code>EMAIL_HOST</code> y credenciales."
            "</p>"
        )
    return (
        '<p class="alert-recibo__meta">'
        "Correo: no enviado (cliente sin email o fallo de envÃ­o)."
        "</p>"
    )


def _html_whatsapp_enlace_manual(*, auto_abierto: bool) -> str:
    if auto_abierto:
        return (
            '<p class="alert-recibo__meta">'
            "WhatsApp: se prepara PDF + mensaje juntos. En el telÃ©fono elija WhatsApp y Enviar."
            "</p>"
        )
    return (
        '<p class="alert-recibo__meta">'
        "Pulse <strong>Abrir WhatsApp</strong> / enviar PDF + mensaje "
        "(en telÃ©fono van juntos; en PC el chat abre con el texto)."
        "</p>"
    )


def _alerta_html_recibo_emitido(
    *,
    doc_numero: str,
    url_pdf: str,
    wa_url: str | None,
    notif: ReciboNotificacionInfo,
) -> str:
    """HTML del aviso tras emitir recibo: descarga + WhatsApp personal (wa.me) + estado correo/API."""
    bloque_correo = _html_estado_correo_recibo(notif)
    # Abrir WhatsApp del vendedor si hay telÃ©fono y la API no entregÃ³ el PDF sola.
    auto_wa = bool(wa_url) and not notif.whatsapp_pdf_por_api

    if wa_url:
        acciones = format_html(
            '<p class="alert-recibo__actions">'
            '<a href="{}" class="alert-recibo__pdf" data-pbr-pdf-download>Descargar PDF</a>'
            '<span class="alert-recibo__sep">·</span>'
            '<a href="{}" class="alert-recibo__wa" target="_blank" rel="noopener noreferrer">Abrir WhatsApp</a>'
            "</p>",
            url_pdf,
            wa_url,
        )
        partes = [bloque_correo]
        if notif.whatsapp_pdf_por_api:
            partes.append(
                '<p class="alert-recibo__meta">WhatsApp: el PDF se enviÃ³ automÃ¡ticamente al cliente (API).</p>'
            )
        elif notif.meta_solo_texto:
            partes.append(
                '<p class="alert-recibo__meta alert-recibo__meta--warn">'
                "WhatsApp API enviÃ³ solo texto. Use Abrir WhatsApp (se abre solo) para completar con su app."
                "</p>"
            )
            partes.append(_html_whatsapp_enlace_manual(auto_abierto=auto_wa))
        elif notif.meta_configurado:
            partes.append(
                '<p class="alert-recibo__meta alert-recibo__meta--warn">'
                "WhatsApp API no completÃ³ el envÃ­o. Se abre su WhatsApp personal para enviarlo."
                "</p>"
            )
            partes.append(_html_whatsapp_enlace_manual(auto_abierto=auto_wa))
        else:
            partes.append(_html_whatsapp_enlace_manual(auto_abierto=auto_wa))
        detalle = mark_safe("".join(partes))
        root_attrs = format_html(
            ' class="alert-recibo" data-pbr-wa-open="{}" data-pbr-pdf-href="{}"',
            wa_url if auto_wa else "",
            url_pdf,
        )
    else:
        acciones = format_html(
            '<p class="alert-recibo__actions">'
            '<a href="{}" class="alert-recibo__pdf" data-pbr-pdf-download>Descargar PDF</a>'
            "</p>",
            url_pdf,
        )
        detalle = mark_safe(
            bloque_correo
            + '<p class="alert-recibo__meta">'
            "WhatsApp: agregue el telÃ©fono del cliente para abrir el chat automÃ¡ticamente."
            "</p>"
        )
        root_attrs = format_html(
            ' class="alert-recibo" data-pbr-pdf-href="{}"',
            url_pdf,
        )

    return format_html(
        "<div{}>"
        '<p class="alert-recibo__title">Recibo <strong>{}</strong> generado.</p>'
        "{}{}"
        "</div>",
        root_attrs,
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
    """Contratos de venta (lotes/casas), no alquiler — para comisión al asesor de ventas."""
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
    return reverse("app:recibo_comision_hub"), "Recibos de comisión al asesor de ventas"


@login_required
def recibo_comision_casa_venta_elegir(request: HttpRequest) -> HttpResponse:
    """Elige contrato de venta para emitir recibo de comisión al asesor de ventas."""
    from inmobiliaria.comision_vendedor import (
        prefetch_pagos_para_comision,
        requisitos_comision_venta,
    )

    qs = prefetch_pagos_para_comision(_contratos_venta_queryset(request.user))
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    from docs.models import DocumentoEmitido, DocumentoTipo

    contrato_ids = [c.pk for c in page]
    docs_por_contrato: dict[int, DocumentoEmitido] = {}
    if contrato_ids:
        for d in (
            DocumentoEmitido.objects.filter(
                contrato_id__in=contrato_ids,
                tipo=DocumentoTipo.RECIBO_COMISION_VENDEDOR,
            )
            .order_by("contrato_id", "-emitido_en", "-id")
        ):
            if d.contrato_id not in docs_por_contrato:
                docs_por_contrato[d.contrato_id] = d
    for contrato in page:
        contrato.monto_comision_ref = contrato.monto_comision_efectivo()
        contrato.req_comision = requisitos_comision_venta(contrato)
        contrato.doc_comision = docs_por_contrato.get(contrato.pk)
    return render(
        request,
        "app/recibo_comision_casa_venta_elegir.html",
        {
            "items": page,
            "page_obj": page,
            "page_title": "Recibo de comisión — venta",
            "page_meta": (
                "1) Asesor de ventas con su comisión en el contrato · "
                "2) Reserva y prima pagadas y validadas en cuenta · "
                "3) Generar o ver el recibo de comisión de venta."
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
                "AÃºn no se puede generar la comisión: " + " ".join(req.motivos),
            )
            return redirect("app:emitir_recibo_comision", contrato_id=contrato.pk)
        form = ReciboComisionVendedorForm(request.POST, contrato=contrato)
        if form.is_valid():
            try:
                from core.marcas import SESSION_KEY

                doc = emitir_recibo_comision_vendedor(
                    contrato=contrato,
                    emitido_por=request.user,
                    monto_comision=form.cleaned_data["monto_comision"],
                    comision_porcentaje=form.cleaned_data.get("comision_porcentaje"),
                    concepto=form.cleaned_data.get("concepto") or "",
                    marca_slug=(request.session.get(SESSION_KEY) or "").strip() or None,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("app:emitir_recibo_comision", contrato_id=contrato.pk)
            url_pdf = reverse("app:doc_download", args=[doc.id])
            messages.success(
                request,
                format_html(
                    'Recibo de comisión al asesor de ventas <strong>{}</strong> generado. '
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
    liquidacion_preview = None
    if monto_sugerido is not None:
        from inmobiliaria.retencion_comision_sv import liquidar_comision_vendedor

        liquidacion_preview = liquidar_comision_vendedor(
            monto_sugerido,
            vendedor=getattr(contrato, "vendedor_perfil", None),
        )
    return render(
        request,
        "app/recibo_comision_preparar.html",
        {
            "form": form,
            "contrato": contrato,
            "vendedor_nombre": nombre_v or "— (sin asesor de ventas)",
            "monto_sugerido": monto_sugerido,
            "precio_final": contrato.precio_final,
            "form_title": "Recibo de comisión al asesor de ventas",
            "cancel_url": cancel_url,
            "cancel_label": cancel_label,
            "req_comision": req,
            "puede_emitir_comision": req.puede_emitir,
            "liquidacion_preview": liquidacion_preview,
        },
    )


@login_required
def emitir_promesa(request: HttpRequest, contrato_id: int) -> HttpResponse:
    """POST obligatorio (CSRF). GET muestra confirmaciÃ³n para no romper enlaces antiguos."""
    contrato = get_object_or_404(
        filtrar_contratos_queryset_por_vendedor(Contrato.objects.all(), request.user),
        pk=contrato_id,
    )
    if request.method != "POST":
        return render(
            request,
            "app/confirm_emitir_documento.html",
            {
                "titulo": "Emitir promesa de venta",
                "blurb": (
                    f"Se generarÃ¡ el PDF de promesa para el contrato {contrato.numero}. "
                    "Confirme para continuar."
                ),
                "submit_label": "Emitir promesa PDF",
                "cancel_url": reverse("app:contrato_list"),
            },
        )
    doc = emitir_promesa_venta(contrato=contrato, emitido_por=request.user)
    return redirect("app:doc_download", doc_id=doc.id)


@login_required
def emitir_recibo(request: HttpRequest, pago_id: int) -> HttpResponse:
    """POST obligatorio (CSRF). GET muestra confirmaciÃ³n."""
    pago = get_object_or_404(
        Pago.objects.select_related("contrato", "contrato__cliente"),
        pk=pago_id,
    )
    if not usuario_puede_ver_contrato(request.user, pago.contrato):
        raise Http404("Pago no disponible")
    if request.method != "POST":
        return render(
            request,
            "app/confirm_emitir_documento.html",
            {
                "titulo": "Actualizar / emitir recibo digital",
                "blurb": (
                    f"Se actualizarÃ¡ el PDF del recibo del pago #{pago.pk} "
                    f"({pago.get_concepto_display()}, {pago.monto}) "
                    f"del contrato {pago.contrato.numero}. "
                    "Si ya existÃ­a un recibo, se conserva el mismo nÃºmero y solo se regenera el archivo."
                ),
                "submit_label": "Actualizar recibo / PDF",
                "cancel_url": reverse("app:pago_list"),
            },
        )
    if pago.pendiente_validacion_gerente:
        messages.error(
            request,
            "Este abono (reserva, prima, cuota o abono a capital) aÃºn no estÃ¡ validado por gerencia. "
            "No se puede emitir el recibo ni notificar al cliente hasta confirmar el depÃ³sito en cuenta.",
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
    # Sin Meta Cloud: abrir WhatsApp personal del asesor de ventas (PDF + mensaje de un solo).
    if wa and not notif.whatsapp_pdf_por_api:
        from docs.recibo_notificacion import datos_envio_whatsapp_personal

        datos = datos_envio_whatsapp_personal(pago.contrato.cliente, doc, pago) or {}
        return render(
            request,
            "app/recibo_abrir_whatsapp.html",
            {
                "doc_numero": doc.numero,
                "wa_url": wa,
                "url_pdf": url_pdf,
                "continue_url": reverse("app:docs_list"),
                "share_payload": {
                    "doc_numero": doc.numero,
                    "pdf_url": url_pdf,
                    "pdf_nombre": datos.get("pdf_nombre")
                    or f"{doc.numero.replace('/', '-')}.pdf",
                    "wa_url": wa,
                    "mensaje": datos.get("mensaje") or "",
                    "mensaje_con_enlace": datos.get("mensaje_con_enlace") or "",
                },
            },
        )
    return redirect("app:docs_list")


@login_required
def doc_download(request: HttpRequest, doc_id: int) -> HttpResponse:
    doc = get_object_or_404(_documento_emitido_queryset_para_descarga(), pk=doc_id)
    if not usuario_puede_ver_documento(request.user, doc):
        raise Http404("Documento no disponible")
    if not doc.pdf_file or not doc.pdf_file.name:
        raise Http404("Documento sin PDF")
    safe_name = f"{doc.numero.replace('/', '-')}.pdf"

    # Recibo de ingreso: siempre regenerar al descargar para aplicar layout/reglas actuales.
    if doc.tipo == DocumentoTipo.RECIBO_INGRESO:
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

    storage = doc.pdf_file.storage
    path = doc.pdf_file.name
    if storage.exists(path):
        try:
            fh = doc.pdf_file.open("rb")
        except FileNotFoundError:
            logger.warning(
                "El almacenamiento indicÃ³ archivo existente pero no se pudo abrir; se regenera (doc_id=%s).",
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
    from docs.expediente_docs import docs_list as _docs_list

    return _docs_list(request)


@login_required
def docs_cliente(request: HttpRequest) -> HttpResponse:
    from docs.expediente_docs import docs_cliente as _docs_cliente

    return _docs_cliente(request)
