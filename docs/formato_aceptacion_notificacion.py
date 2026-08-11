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
from django.utils.html import format_html

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
    destinos, _ = _destinos_email_formato(formato)
    tiene_email = bool(destinos) and getattr(
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


def _email_oficina_formato() -> str:
    return (getattr(settings, "RECIBO_EMAIL_FALLBACK", "") or "").strip()


def _destinos_email_formato(formato: "FormatoAceptacion") -> tuple[list[str], bool]:
    """
    Destinatarios del PDF: cliente (si tiene correo) + bandeja de oficina.
    Devuelve (lista, solo_oficina).
    """
    cliente_email = _email_destino_formato(formato)
    oficina = _email_oficina_formato()
    destinos: list[str] = []
    if cliente_email:
        destinos.append(cliente_email)
    if oficina and oficina.lower() not in {d.lower() for d in destinos}:
        destinos.append(oficina)
    solo_oficina = bool(destinos) and not cliente_email
    return destinos, solo_oficina


def enviar_formato_pdf_por_email(
    formato: "FormatoAceptacion", pdf_bytes: bytes, *, public_pdf_url: str | None = None
) -> tuple[bool, str | None]:
    """
    Envía el PDF por correo (cliente y/o bandeja de oficina vía Brevo/SMTP).
    Retorna (éxito, mensaje de error breve para mostrar al usuario si falló el envío).
    """
    if not getattr(settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True):
        return False, None
    destinos, solo_oficina = _destinos_email_formato(formato)
    if not destinos:
        logger.warning(
            "Formato Nº %s: sin correo del cliente ni RECIBO_EMAIL_FALLBACK; no se envía PDF.",
            formato.numero_formulario,
        )
        return False, None
    if solo_oficina:
        logger.info(
            "Formato Nº %s: cliente sin correo; PDF a bandeja de oficina %s",
            formato.numero_formulario,
            destinos[0],
        )
    wa_url = construir_url_whatsapp_formato_pdf(formato, public_pdf_url)
    nombre = (formato.nombre_cliente or "").strip() or "cliente"
    body = render_to_string(
        "docs/email_formato_aceptacion_pdf.txt",
        {
            "formato": formato,
            "numero_fmt": f"{formato.numero_formulario:04d}",
            "nombre_cliente": nombre,
            "empresa_nombre": _empresa_nombre(),
            "whatsapp_url": wa_url,
        },
    ).strip()
    if solo_oficina:
        body = (
            f"[Aviso interno] El cliente «{nombre}» no tiene correo registrado. "
            f"Este PDF llegó a la bandeja de oficina ({', '.join(destinos)}). "
            f"Reenvíelo al cliente por WhatsApp si aplica.\n\n"
            + body
        )
    elif len(destinos) > 1:
        body = (
            f"[Copia oficina] Formato del cliente «{nombre}». "
            f"Destinatarios: {', '.join(destinos)}.\n\n"
            + body
        )
    nombre_archivo = f"formato_aceptacion_{formato.numero_formulario:04d}.pdf"
    msg = EmailMessage(
        subject=getattr(
            settings,
            "FORMATO_ACEPTACION_EMAIL_ASUNTO",
            "Su formato de aceptación (PDF) — Paredes Bienes Raíces",
        ),
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=destinos,
    )
    msg.attach(nombre_archivo, pdf_bytes, "application/pdf")
    try:
        msg.send(fail_silently=False)
        logger.info(
            "Formato Nº %s: correo con PDF → %s",
            formato.numero_formulario,
            ", ".join(destinos),
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

    dest_email = _email_destino_formato(formato)
    to = digitos_telefono_e164_sv(_telefono_destino_formato(formato))
    destinos_correo, solo_oficina = _destinos_email_formato(formato)
    puede_correo = bool(destinos_correo) and getattr(
        settings, "FORMATO_ACEPTACION_ENVIAR_EMAIL", True
    ) and _correo_configurado()
    puede_wa = bool(to) and _whatsapp_meta_activo_formato()

    if not puede_correo and not puede_wa:
        return

    from inmobiliaria.views_web import _generar_pdf_formato_aceptacion_bytes

    try:
        pdf_bytes = _generar_pdf_formato_aceptacion_bytes(formato)
    except Exception as e:
        logger.exception(
            "Formato Nº %s: error al generar PDF para notificar: %s",
            formato.numero_formulario,
            e,
        )
        messages.warning(
            request,
            "No se pudo generar el PDF. Revise los documentos adjuntos y el almacenamiento.",
        )
        return

    correo_ok, correo_err = (False, None)
    if puede_correo:
        correo_ok, correo_err = enviar_formato_pdf_por_email(formato, pdf_bytes)

    wa_ok = False
    wa_adjunto = False
    wa_detalle: str | None = None
    if puede_wa:
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
        partes.append("WhatsApp (solo texto)")

    wa_url = construir_url_whatsapp_formato_pdf(formato, None)

    if correo_ok:
        if solo_oficina:
            txt = (
                "PDF del formato enviado a la bandeja de oficina "
                f"({', '.join(destinos_correo)}). "
                "El cliente no tiene correo registrado."
            )
        else:
            txt = (
                "PDF del formato enviado por correo a "
                + ", ".join(destinos_correo)
                + "."
            )
        if partes:
            txt = "PDF del formato generado y enviado vía: " + ", ".join(partes) + "."
        if wa_url and to and not wa_ok:
            messages.success(
                request,
                format_html(
                    '{} <a href="{}" target="_blank" rel="noopener noreferrer">'
                    "Abrir WhatsApp al cliente</a> para compartir el PDF.",
                    txt,
                    wa_url,
                ),
            )
        else:
            messages.success(request, txt)
        return

    if partes:
        messages.success(
            request,
            "PDF del formato generado y enviado al cliente vía: " + ", ".join(partes) + ".",
        )
        return

    # PDF generado pero envío falló: no mostrar error rojo al usuario (el guardado ya fue exitoso).
    logger.warning(
        "Formato Nº %s: PDF generado pero envío automático falló (correo=%s wa=%s). correo_err=%s wa_detalle=%s",
        formato.numero_formulario,
        correo_ok,
        wa_ok,
        correo_err,
        wa_detalle,
    )
    messages.info(
        request,
        "PDF del formato generado correctamente. "
        "Puede descargarlo con «Descargar PDF» y compartirlo al cliente "
        "(correo o WhatsApp manual si el envío automático no aplicó).",
    )


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
