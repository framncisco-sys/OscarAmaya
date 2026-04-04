"""Envío automático del PDF del formato de aceptación y de la promesa escaneada (correo + WhatsApp Meta)."""

from __future__ import annotations

import logging
import mimetypes
import urllib.parse
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from inmobiliaria.phone_sv import digitos_telefono_e164_sv

from .recibo_notificacion import _correo_entrega_a_bandejas_reales

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _telefono_destino_formato(formato: "FormatoAceptacion") -> str:
    c = formato.contrato
    if c is not None and c.cliente_id:
        t = (getattr(c.cliente, "telefono", None) or "").strip()
        if t:
            return t
    for raw in (formato.telefono_notificacion, formato.telefono_domicilio):
        s = (raw or "").strip()
        if s:
            return s
    return ""


def _email_destino_formato(formato: "FormatoAceptacion") -> str:
    c = formato.contrato
    if c is not None and c.cliente_id:
        return (getattr(c.cliente, "email", None) or "").strip()
    return ""


def _empresa_nombre() -> str:
    return (
        (getattr(settings, "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR", "") or "").strip()
        or "Paredes Bienes Raíces"
    )


def construir_url_whatsapp_formato_pdf(
    formato: "FormatoAceptacion", public_pdf_url: str | None
) -> str | None:
    tel = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    if not tel:
        return None
    nombre = (formato.nombre_cliente or "").strip() or "estimado cliente"
    n = formato.numero_formulario
    partes = [
        f"Hola {nombre}, le enviamos su formato de aceptación Nº {n:04d} — {_empresa_nombre()}.",
        "",
        "Por este enlace de WhatsApp no se adjunta el archivo; use el enlace de descarga o revise su correo.",
    ]
    if public_pdf_url:
        partes.append("Descargue el PDF aquí (toque el enlace):")
        partes.append(public_pdf_url)
    partes.extend(["", f"— {_empresa_nombre()}"])
    texto = "\n".join(partes)
    return f"https://wa.me/{tel}?text={urllib.parse.quote(texto)}"


def enviar_formato_pdf_por_email(formato: "FormatoAceptacion", pdf_bytes: bytes) -> bool:
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True):
        return False
    destino = _email_destino_formato(formato)
    if not destino:
        logger.warning(
            "Formato Nº %s: sin correo del cliente (vincule contrato con email); no se envía PDF por correo.",
            formato.numero_formulario,
        )
        return False
    wa_url = construir_url_whatsapp_formato_pdf(formato, None)
    body = render_to_string(
        "docs/email_formato_aceptacion_pdf.txt",
        {
            "formato": formato,
            "numero_fmt": f"{formato.numero_formulario:04d}",
            "nombre_cliente": (formato.nombre_cliente or "").strip(),
            "empresa_nombre": _empresa_nombre(),
            "whatsapp_url": wa_url,
        },
    ).strip()
    nombre_archivo = f"formato_aceptacion_{formato.numero_formulario:04d}.pdf"
    msg = EmailMessage(
        subject=getattr(
            settings,
            "FORMATO_ACEPTACION_EMAIL_ASUNTO",
            "Su formato de aceptación (PDF) — Paredes Bienes Raíces",
        ),
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=[destino],
    )
    msg.attach(nombre_archivo, pdf_bytes, "application/pdf")
    try:
        msg.send(fail_silently=False)
        logger.info(
            "Formato Nº %s: correo con PDF → %s",
            formato.numero_formulario,
            destino,
        )
        return True
    except Exception as e:
        logger.exception("Formato Nº %s: fallo al enviar correo: %s", formato.numero_formulario, e)
        return False


def _archivo_promesa_bytes_y_tipo(
    formato: "FormatoAceptacion",
) -> tuple[bytes | None, str, str]:
    """(bytes, content_type, nombre sugerido)."""
    field = formato.promesa_venta_escaneada
    if not field or not field.name:
        return None, "application/octet-stream", "promesa"
    name = field.name.split("/")[-1] or "promesa"
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    try:
        field.open("rb")
        raw = field.read()
    except OSError as e:
        logger.warning("Promesa formato %s: no se pudo leer archivo: %s", formato.pk, e)
        return None, ctype, name
    finally:
        try:
            field.close()
        except Exception:
            pass
    return raw if raw else None, ctype, name


def enviar_promesa_escaneada_por_email(formato: "FormatoAceptacion") -> bool:
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True):
        return False
    destino = _email_destino_formato(formato)
    if not destino:
        logger.warning(
            "Formato Nº %s: sin correo del cliente; no se envía promesa por correo.",
            formato.numero_formulario,
        )
        return False
    raw, ctype, fname = _archivo_promesa_bytes_y_tipo(formato)
    if not raw:
        return False
    body = render_to_string(
        "docs/email_promesa_venta_escaneada.txt",
        {
            "formato": formato,
            "numero_fmt": f"{formato.numero_formulario:04d}",
            "nombre_cliente": (formato.nombre_cliente or "").strip(),
            "empresa_nombre": _empresa_nombre(),
        },
    ).strip()
    msg = EmailMessage(
        subject=getattr(
            settings,
            "FORMATO_ACEPTACION_PROMESA_EMAIL_ASUNTO",
            "Su promesa de venta escaneada — Paredes Bienes Raíces",
        ),
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=[destino],
    )
    msg.attach(fname, raw, ctype)
    try:
        msg.send(fail_silently=False)
        logger.info(
            "Formato Nº %s: promesa escaneada por correo → %s",
            formato.numero_formulario,
            destino,
        )
        return True
    except Exception as e:
        logger.exception(
            "Formato Nº %s: fallo al enviar promesa por correo: %s",
            formato.numero_formulario,
            e,
        )
        return False


def _whatsapp_meta_activo_formato() -> bool:
    return bool(
        getattr(settings, "WHATSAPP_CLOUD_ENABLED", False)
        and getattr(settings, "RECIBO_ENVIAR_WHATSAPP_META", False)
        and getattr(settings, "FORMATO_ACEPTACION_ENVIAR_WHATSAPP_META", True)
    )


def notificar_formato_pdf_tras_guardado(
    request: "HttpRequest",
    formato: "FormatoAceptacion",
    prev_firmas_completas: bool,
) -> None:
    """
    Tras guardar el formulario: si hay tres firmas y la política lo permite, genera el PDF
    y lo envía por correo y WhatsApp (Meta) como en recibos.
    """
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_AL_GUARDAR", True):
        return
    if not formato.firmas_completas:
        return
    if not getattr(settings, "FORMATO_ACEPTACION_NOTIFICAR_CADA_GUARDADO", True):
        if prev_firmas_completas:
            return

    from inmobiliaria.views_web import _generar_pdf_formato_aceptacion_bytes

    try:
        pdf_bytes = _generar_pdf_formato_aceptacion_bytes(formato)
    except Exception as e:
        logger.exception("Formato Nº %s: error al generar PDF para notificar: %s", formato.numero_formulario, e)
        messages.warning(
            request,
            "No se pudo generar el PDF para enviar al cliente. Revise las firmas y el almacenamiento.",
        )
        return

    correo_ok = enviar_formato_pdf_por_email(formato, pdf_bytes)
    to = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    wa_ok = False
    wa_adjunto = False
    if _whatsapp_meta_activo_formato() and to:
        try:
            from core.whatsapp_cloud import enviar_recibo_whatsapp_cloud

            fn = f"formato_aceptacion_{formato.numero_formulario:04d}.pdf"
            cap = (
                f"Formato de aceptación Nº {formato.numero_formulario:04d} — "
                f"{_empresa_nombre()}"
            )
            r = enviar_recibo_whatsapp_cloud(
                to_digits=to,
                filename=fn,
                caption=cap,
                document_url=None,
                pdf_bytes=pdf_bytes,
            )
            wa_ok = bool(r.ok)
            wa_adjunto = bool(r.adjunto_pdf)
            if not r.ok:
                logger.warning("Formato Nº %s WhatsApp: %s", formato.numero_formulario, r.detalle)
        except Exception as e:
            logger.exception("Formato Nº %s: WhatsApp Meta: %s", formato.numero_formulario, e)

    partes: list[str] = []
    if correo_ok:
        partes.append("correo" + (" (entrega real)" if _correo_entrega_a_bandejas_reales() else ""))
    if wa_ok and wa_adjunto:
        partes.append("WhatsApp con PDF")
    elif wa_ok:
        partes.append("WhatsApp (solo texto; revise configuración si esperaba el PDF)")
    if partes:
        messages.info(
            request,
            "Se notificó al cliente el PDF del formato de aceptación vía: " + ", ".join(partes) + ".",
        )
    else:
        if not _email_destino_formato(formato) and not to:
            messages.info(
                request,
                "PDF del formato listo; no se envió al cliente (sin correo ni teléfono registrados en contrato o formato).",
            )
        elif not correo_ok and not wa_ok:
            messages.info(
                request,
                "PDF del formato generado; el envío automático no se completó (revise SMTP y WhatsApp Meta).",
            )


def notificar_promesa_escaneada_tras_subir(
    request: "HttpRequest",
    formato: "FormatoAceptacion",
) -> None:
    correo_ok = enviar_promesa_escaneada_por_email(formato)
    to = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    wa_ok = False
    wa_adjunto = False
    raw, ctype, fname = _archivo_promesa_bytes_y_tipo(formato)
    if _whatsapp_meta_activo_formato() and to and raw:
        try:
            from core.whatsapp_cloud import enviar_recibo_whatsapp_cloud

            lower = fname.lower()
            if lower.endswith(".pdf") and ctype == "application/pdf":
                cap = f"Promesa de venta escaneada — Formato Nº {formato.numero_formulario:04d} — {_empresa_nombre()}"
                r = enviar_recibo_whatsapp_cloud(
                    to_digits=to,
                    filename=fname if lower.endswith(".pdf") else f"{fname}.pdf",
                    caption=cap,
                    document_url=None,
                    pdf_bytes=raw,
                )
                wa_ok = bool(r.ok)
                wa_adjunto = bool(r.adjunto_pdf)
            else:
                from core.whatsapp_cloud import send_text_message

                send_text_message(
                    to_digits=to,
                    body=(
                        f"Le enviamos la promesa de venta escaneada (formato Nº {formato.numero_formulario:04d}) "
                        f"por correo electrónico — {_empresa_nombre()}"
                    )[:4090],
                )
                wa_ok = True
                wa_adjunto = False
        except Exception as e:
            logger.exception("Promesa formato %s: WhatsApp: %s", formato.pk, e)

    partes: list[str] = []
    if correo_ok:
        partes.append("correo")
    if wa_ok and wa_adjunto:
        partes.append("WhatsApp con archivo PDF")
    elif wa_ok:
        partes.append("WhatsApp (mensaje; archivo por correo si no es PDF)")
    if partes:
        messages.success(
            request,
            "Promesa guardada. Se envió al cliente por: " + ", ".join(partes) + ".",
        )
    else:
        messages.success(request, "Promesa guardada.")
        if not _email_destino_formato(formato) and not to:
            messages.info(
                request,
                "No se pudo notificar: agregue correo o teléfono del cliente (contrato o datos del formato).",
            )
