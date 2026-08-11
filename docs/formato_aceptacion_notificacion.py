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

from .recibo_notificacion import (
    _correo_entrega_a_bandejas_reales,
    _url_archivo_field_absoluta_o_ruta,
)

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
        em = (getattr(c.cliente, "email", None) or "").strip()
        if em:
            return em
    from inmobiliaria.credito_contrato import _norm_dui, _norm_nombre
    from inmobiliaria.models import Cliente

    dui = _norm_dui(formato.dui_numero)
    if dui:
        for cli in Cliente.objects.exclude(email="").only("dui", "email")[:800]:
            if _norm_dui(cli.dui) == dui and (cli.email or "").strip():
                return cli.email.strip()
    nombre = _norm_nombre(formato.nombre_cliente)
    if nombre:
        for cli in Cliente.objects.exclude(email="").only(
            "nombres", "apellidos", "email"
        )[:800]:
            cn = _norm_nombre(f"{cli.nombres or ''} {cli.apellidos or ''}")
            if cn == nombre and (cli.email or "").strip():
                return cli.email.strip()
    return ""


def _correo_configurado() -> bool:
    if getattr(settings, "BREVO_API_KEY", "").strip():
        return True
    backend = (getattr(settings, "EMAIL_BACKEND", "") or "").lower()
    if "console" in backend or "locmem" in backend or "dummy" in backend:
        return False
    return bool((getattr(settings, "EMAIL_HOST", "") or "").strip())


def _intentara_envio_automatico(formato: "FormatoAceptacion") -> bool:
    """True si hay destino y canal configurado (correo o WhatsApp Meta)."""
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_AL_GUARDAR", True):
        return False
    tiene_email = bool(_email_destino_formato(formato)) and getattr(
        settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True
    )
    tiene_tel = bool(digitos_telefono_e164_sv(_telefono_destino_formato(formato)))
    if tiene_email and _correo_configurado():
        return True
    if tiene_tel and _whatsapp_meta_activo_formato():
        return True
    return False


def _empresa_nombre() -> str:
    return (
        (getattr(settings, "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR", "") or "").strip()
        or "Paredes Bienes Raíces"
    )


def construir_url_whatsapp_promesa_formato(formato: "FormatoAceptacion") -> str | None:
    """Enlace wa.me con texto sobre la promesa escaneada (el archivo va por correo o WhatsApp API)."""
    tel = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    if not tel:
        return None
    nombre = (formato.nombre_cliente or "").strip() or "estimado cliente"
    n = formato.numero_formulario
    partes = [
        f"Hola {nombre}, le enviamos su promesa de venta escaneada (formato Nº {n:04d}) — {_empresa_nombre()}.",
        "",
        "Si usa solo este chat, el archivo puede ir por correo o como documento según la configuración de la inmobiliaria.",
        "",
        f"— {_empresa_nombre()}",
    ]
    texto = "\n".join(partes)
    return f"https://wa.me/{tel}?text={urllib.parse.quote(texto)}"


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


def enviar_formato_pdf_por_email(
    formato: "FormatoAceptacion", pdf_bytes: bytes
) -> tuple[bool, str | None]:
    """
    Intenta enviar el PDF por correo.
    Retorna (éxito, mensaje de error breve para mostrar al usuario si falló el envío SMTP).
    """
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True):
        return False, None
    destino = _email_destino_formato(formato)
    if not destino:
        logger.warning(
            "Formato Nº %s: sin correo del cliente (vincule contrato con email); no se envía PDF por correo.",
            formato.numero_formulario,
        )
        return False, None
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
        return True, None
    except Exception as e:
        logger.exception("Formato Nº %s: fallo al enviar correo: %s", formato.numero_formulario, e)
        err = (str(e) or type(e).__name__).strip()
        if len(err) > 380:
            err = err[:377] + "…"
        return False, err


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
    wa_url = construir_url_whatsapp_promesa_formato(formato)
    body = render_to_string(
        "docs/email_promesa_venta_escaneada.txt",
        {
            "formato": formato,
            "numero_fmt": f"{formato.numero_formulario:04d}",
            "nombre_cliente": (formato.nombre_cliente or "").strip(),
            "empresa_nombre": _empresa_nombre(),
            "whatsapp_url": wa_url,
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


def _enviar_promesa_whatsapp_twilio(formato: "FormatoAceptacion", media_url: str | None) -> bool:
    """Twilio con MediaUrl HTTPS público (misma configuración que recibos)."""
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "") or ""
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    from_wa = getattr(settings, "TWILIO_WHATSAPP_FROM", "") or ""
    if not (sid and token and from_wa):
        return False
    to = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    if not to:
        return False
    to_wa = f"whatsapp:+{to}"
    try:
        import base64
        import urllib.request

        body = (
            f"Promesa de venta escaneada — Formato Nº {formato.numero_formulario:04d} — "
            f"{_empresa_nombre()}."
        )
        data: dict[str, str] = {"From": from_wa, "To": to_wa, "Body": body}
        if media_url:
            data["MediaUrl"] = media_url
        post = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=post,
            method="POST",
        )
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 201):
                logger.info("Promesa formato %s: Twilio WhatsApp → %s", formato.pk, to_wa)
                return True
    except Exception as e:
        logger.warning("Promesa formato %s: Twilio no enviado: %s", formato.pk, e)
    return False


def _whatsapp_meta_activo_formato() -> bool:
    """
    WhatsApp Cloud para formato de aceptación: independiente de RECIBO_ENVIAR_WHATSAPP_META.
    Basta WHATSAPP_CLOUD_ENABLED, credenciales válidas y FORMATO_ACEPTACION_ENVIAR_WHATSAPP_META.
    """
    if not getattr(settings, "WHATSAPP_CLOUD_ENABLED", False):
        return False
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_WHATSAPP_META", True):
        return False
    try:
        from core.whatsapp_cloud import is_configured

        return is_configured()
    except Exception:
        return False


def notificar_formato_pdf_tras_guardado(
    request: "HttpRequest",
    formato: "FormatoAceptacion",
    prev_firmas_completas: bool,
) -> None:
    """
    Tras guardar el formulario: si hay documentos adjuntos y la política lo permite, genera el PDF
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
            "No se pudo generar el PDF para enviar al cliente. Revise los documentos adjuntos y el almacenamiento.",
        )
        return

    correo_ok, correo_err = enviar_formato_pdf_por_email(formato, pdf_bytes)
    to = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    wa_ok = False
    wa_adjunto = False
    wa_detalle: str | None = None
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
                wa_detalle = (r.detalle or "").strip() or "Meta rechazó el envío (revise logs)."
                logger.warning("Formato Nº %s WhatsApp: %s", formato.numero_formulario, wa_detalle)
        except Exception as e:
            logger.exception("Formato Nº %s: WhatsApp Meta: %s", formato.numero_formulario, e)
            err = (str(e) or type(e).__name__).strip()
            wa_detalle = err[:400] if err else "Error al llamar a la API de WhatsApp."

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
                "PDF del formato generado correctamente. "
                "No se envió al cliente porque no hay correo ni teléfono en el formato o cliente vinculado. "
                "Use «Descargar PDF» o compártalo manualmente.",
            )
        elif not _intentara_envio_automatico(formato):
            messages.info(
                request,
                "PDF del formato generado correctamente. "
                "El envío automático por correo/WhatsApp no está activo o falta el correo del cliente. "
                "Puede descargarlo con «Descargar PDF».",
            )
        elif not correo_ok and not wa_ok:
            hints: list[str] = []
            if correo_err:
                hints.append(f"Correo: {correo_err}")
            elif _email_destino_formato(formato) and getattr(
                settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True
            ):
                hints.append(
                    "Correo: revise Brevo/SMTP (EMAIL_HOST, credenciales) y el remitente autorizado."
                )
            if wa_detalle:
                hints.append(f"WhatsApp (Meta): {wa_detalle}")
            elif to and getattr(settings, "WHATSAPP_CLOUD_ENABLED", False):
                if not _whatsapp_meta_activo_formato():
                    hints.append(
                        "WhatsApp: complete WHATSAPP_CLOUD_ACCESS_TOKEN y WHATSAPP_CLOUD_PHONE_NUMBER_ID "
                        "o desactive WHATSAPP_CLOUD_ENABLED si no usará Meta."
                    )
            msg_txt = (
                "PDF del formato generado; el envío automático al cliente no se completó. "
                "Revise Brevo/SMTP o WhatsApp Cloud (Meta)."
            )
            if hints:
                msg_txt += " " + " · ".join(hints)
            messages.warning(request, msg_txt)


def notificar_promesa_escaneada_tras_subir(
    request: "HttpRequest",
    formato: "FormatoAceptacion",
) -> None:
    from inmobiliaria.models import FormatoAceptacion as FormatoAceptacionModel

    formato = FormatoAceptacionModel.objects.select_related("contrato", "contrato__cliente").get(
        pk=formato.pk
    )

    correo_ok = enviar_promesa_escaneada_por_email(formato)
    to = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    wa_ok = False
    wa_adjunto = False
    twilio_ok = False
    raw, ctype, fname = _archivo_promesa_bytes_y_tipo(formato)
    ct_lower = (ctype or "").lower()
    es_pdf = bool(
        raw
        and (
            fname.lower().endswith(".pdf")
            or ct_lower in ("application/pdf", "application/x-pdf")
            or raw[:4] == b"%PDF"
        )
    )

    if _whatsapp_meta_activo_formato() and to and raw:
        try:
            from core.whatsapp_cloud import enviar_recibo_whatsapp_cloud, send_text_message

            if es_pdf:
                cap = (
                    f"Promesa de venta escaneada — Formato Nº {formato.numero_formulario:04d} — "
                    f"{_empresa_nombre()}"
                )
                fn = (fname or "").strip() or f"promesa_{formato.numero_formulario:04d}.pdf"
                if not fn.lower().endswith(".pdf"):
                    fn = f"{fn}.pdf"
                r = enviar_recibo_whatsapp_cloud(
                    to_digits=to,
                    filename=fn,
                    caption=cap,
                    document_url=None,
                    pdf_bytes=raw,
                )
                wa_ok = bool(r.ok)
                wa_adjunto = bool(r.adjunto_pdf)
                if not r.ok:
                    logger.warning("Promesa formato %s WhatsApp Meta: %s", formato.pk, r.detalle)
            else:
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
            logger.exception("Promesa formato %s: WhatsApp Meta: %s", formato.pk, e)

    if getattr(settings, "RECIBO_ENVIAR_WHATSAPP_TWILIO", False) and to:
        rel_or_abs = _url_archivo_field_absoluta_o_ruta(formato.promesa_venta_escaneada)
        media_url = None
        if rel_or_abs:
            if rel_or_abs.lower().startswith("https://"):
                media_url = rel_or_abs
            else:
                base = getattr(settings, "PUBLIC_BASE_URL", "").strip().rstrip("/")
                if base:
                    cand = f"{base}{rel_or_abs}"
                    if cand.lower().startswith("https://"):
                        media_url = cand
        if media_url:
            twilio_ok = _enviar_promesa_whatsapp_twilio(formato, media_url)

    partes: list[str] = []
    if correo_ok:
        partes.append("correo" + (" (entrega real)" if _correo_entrega_a_bandejas_reales() else ""))
    if wa_ok and wa_adjunto:
        partes.append("WhatsApp (Meta) con PDF")
    elif wa_ok:
        partes.append("WhatsApp (Meta, texto o sin adjunto PDF)")
    if twilio_ok:
        partes.append("WhatsApp (Twilio)")
    if partes:
        messages.success(
            request,
            "Promesa guardada. Se notificó al cliente por: " + ", ".join(partes) + ".",
        )
    else:
        messages.success(request, "Promesa guardada.")
        if not _email_destino_formato(formato) and not to:
            messages.info(
                request,
                "No se pudo notificar: registre correo y teléfono del cliente en el contrato vinculado "
                "o teléfonos en el formato (notificación / domicilio). Revise SMTP y WhatsApp (Meta/Twilio) en el servidor.",
            )
        elif not correo_ok and not wa_ok and not twilio_ok:
            messages.info(
                request,
                "Promesa guardada; el envío por correo o WhatsApp no se completó (revise datos del cliente y la configuración de correo/WhatsApp).",
            )
