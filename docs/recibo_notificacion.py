"""Envío de recibo de ingreso por correo y enlace de WhatsApp (y Twilio opcional)."""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from inmobiliaria.models import Pago

    from .models import DocumentoEmitido

from .recibo_text import format_monto_sv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReciboNotificacionInfo:
    """Resultado de notificar un recibo (para mensajes en la interfaz)."""

    correo_enviado: bool
    """True si se llamó a send() sin excepción (puede ser solo consola / dummy)."""
    correo_entrega_real: bool
    """True solo si hay SMTP configurado y el backend no es consola/dummy."""
    whatsapp_pdf_por_api: bool
    meta_configurado: bool
    meta_solo_texto: bool
    twilio_pdf: bool


def _correo_entrega_a_bandejas_reales() -> bool:
    """Sin EMAIL_HOST o con QuietConsole el mensaje no llega al cliente."""
    be = (getattr(settings, "EMAIL_BACKEND", "") or "").strip()
    if "QuietConsole" in be or be.endswith("console.EmailBackend") or "dummy" in be.lower():
        return False
    if not (getattr(settings, "EMAIL_HOST", "") or "").strip():
        return False
    return True


def url_pdf_publica_https(doc: "DocumentoEmitido") -> str | None:
    """
    URL absoluta HTTPS al PDF en /media/... Solo útil si PUBLIC_BASE_URL apunta a un sitio
    accesible desde internet (no localhost) y /media/ se sirve sin login.
    """
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not base or not doc.pdf_file or not doc.pdf_file.name:
        return None
    path = doc.pdf_file.url
    if not str(path).startswith("/"):
        path = "/" + str(path)
    url = f"{base}{path}"
    if not url.lower().startswith("https://"):
        return None
    return url


def url_pdf_enlace_absoluto(doc: "DocumentoEmitido") -> str | None:
    """
    URL al PDF con PUBLIC_BASE_URL (http o https) para texto en wa.me.
    Meta/Twilio para adjuntar archivo siguen requiriendo HTTPS público donde aplique.
    """
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not base or not doc.pdf_file or not doc.pdf_file.name:
        return None
    path = doc.pdf_file.url
    if not str(path).startswith("/"):
        path = "/" + str(path)
    return f"{base}{path}"


def _telefono_a_whatsapp(telefono: str) -> str | None:
    if not telefono or not str(telefono).strip():
        return None
    digits = "".join(c for c in str(telefono) if c.isdigit())
    if not digits:
        return None
    pais = getattr(settings, "RECIBO_WHATSAPP_PAIS", "503")
    if digits.startswith(pais) and len(digits) >= 10:
        return digits
    # El Salvador: móvil 8 dígitos sin prefijo
    if len(digits) == 8:
        return f"{pais}{digits}"
    if len(digits) == 9 and digits.startswith("0"):
        return f"{pais}{digits[1:]}"
    if len(digits) >= 10:
        return digits
    return None


def construir_url_whatsapp_recibo(cliente, doc: "DocumentoEmitido", pago: "Pago") -> str | None:
    """
    URL wa.me con mensaje prellenado.

    El enlace wa.me solo abre el chat con texto; no adjunta archivos (así funciona WhatsApp).
    Si PUBLIC_BASE_URL está definida, el texto puede incluir un enlace directo al PDF (http o https).
    Para que el cliente reciba el PDF como documento en WhatsApp, active Meta Cloud API o Twilio (ver .env.example).
    """
    tel = _telefono_a_whatsapp(getattr(cliente, "telefono", "") or "")
    if not tel:
        return None
    nombre = (getattr(cliente, "nombres", "") or "").strip() or "estimado cliente"
    pdf_url = url_pdf_enlace_absoluto(doc) or url_pdf_publica_https(doc)

    partes = [
        f"Hola {nombre}, le informamos que su recibo *{doc.numero}* "
        f"por *${pago.monto}* (contrato {pago.contrato.numero}) fue registrado.",
        "",
        "Por este enlace de WhatsApp no se adjunta el archivo; use el enlace de descarga abajo o revise su correo.",
    ]
    if pdf_url:
        partes.append("Descargue su recibo en PDF aquí (toque el enlace):")
        partes.append(pdf_url)
        partes.append("")
        partes.append("También puede habérselo enviado a su correo si tenemos su email.")
    else:
        partes.append(
            "Le enviamos el PDF a su correo si lo tenemos registrado. "
            "Si no, puede solicitarlo en oficina."
        )
    partes.append("")
    partes.append("— Paredes Bienes Raíces")
    texto = "\n".join(partes)
    return f"https://wa.me/{tel}?text={urllib.parse.quote(texto)}"


def enviar_recibo_por_email(doc: "DocumentoEmitido", pago: "Pago") -> bool:
    if not getattr(settings, "RECIBO_ENVIAR_EMAIL", True):
        return False
    cliente = pago.contrato.cliente
    destino = (getattr(cliente, "email", None) or "").strip()
    if not destino:
        logger.warning(
            "Recibo %s: el cliente no tiene email registrado; no se envía correo.",
            doc.numero,
        )
        return False
    if not doc.pdf_file or not doc.pdf_file.name:
        return False

    try:
        doc.pdf_file.open("rb")
        pdf_bytes = doc.pdf_file.read()
    except OSError as e:
        logger.warning("Recibo %s: no se pudo leer PDF: %s", doc.numero, e)
        return False
    finally:
        try:
            doc.pdf_file.close()
        except Exception:
            pass

    wa_url = construir_url_whatsapp_recibo(cliente, doc, pago)

    nombre_completo = f"{cliente.nombres} {cliente.apellidos}".strip()
    empresa = (getattr(settings, "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR", "") or "").strip() or "Paredes Bienes Raíces"
    body = render_to_string(
        "docs/email_recibo_ingreso.txt",
        {
            "cliente": cliente,
            "doc": doc,
            "pago": pago,
            "contrato": pago.contrato,
            "inmueble": pago.contrato.inmueble,
            "whatsapp_url": wa_url,
            "nombre_cliente_completo": nombre_completo,
            "monto_fmt": format_monto_sv(pago.monto),
            "empresa_nombre": empresa,
        },
    ).strip()

    nombre_archivo = f"recibo_{doc.numero.replace('/', '-')}.pdf"
    msg = EmailMessage(
        subject=getattr(settings, "RECIBO_EMAIL_ASUNTO", "Su recibo de pago — Paredes Bienes Raíces"),
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=[destino],
    )
    msg.attach(nombre_archivo, pdf_bytes, "application/pdf")

    try:
        msg.send(fail_silently=False)
        logger.info("Recibo %s: mensaje pasado al backend de correo → %s", doc.numero, destino)
        be = getattr(settings, "EMAIL_BACKEND", "") or ""
        if (
            "QuietConsole" in be
            or be == "django.core.mail.backends.console.EmailBackend"
            or be == "django.core.mail.backends.dummy.EmailBackend"
        ):
            logger.warning(
                "Recibo %s: EMAIL_BACKEND no usa SMTP; el cliente NO recibirá el correo en su bandeja. "
                "Configure en .env: EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend y "
                "EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL.",
                doc.numero,
            )
        return True
    except Exception as e:
        logger.exception("Recibo %s: fallo al enviar email: %s", doc.numero, e)
        return False


def _enviar_whatsapp_twilio(doc: "DocumentoEmitido", pago: "Pago", media_url: str | None) -> bool:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "") or ""
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    from_wa = getattr(settings, "TWILIO_WHATSAPP_FROM", "") or ""
    if not (sid and token and from_wa):
        return False
    to = _telefono_a_whatsapp(pago.contrato.cliente.telefono or "")
    if not to:
        return False
    to_wa = f"whatsapp:+{to}"
    try:
        import urllib.request
        import base64

        body = (
            f"Recibo {doc.numero} por ${pago.monto} — Contrato {pago.contrato.numero}. "
            f"Paredes Bienes Raíces."
        )
        data = {"From": from_wa, "To": to_wa, "Body": body}
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
                logger.info("Recibo %s: WhatsApp Twilio enviado a %s", doc.numero, to_wa)
                return True
    except Exception as e:
        logger.warning("Recibo %s: Twilio WhatsApp no enviado: %s", doc.numero, e)
    return False


def _enviar_whatsapp_meta_cloud(
    doc: "DocumentoEmitido", pago: "Pago", media_url: str | None
):
    from core.whatsapp_cloud import EnvioResultado

    if not getattr(settings, "WHATSAPP_CLOUD_ENABLED", False):
        return None
    if not getattr(settings, "RECIBO_ENVIAR_WHATSAPP_META", False):
        return None
    to = _telefono_a_whatsapp(pago.contrato.cliente.telefono or "")
    if not to:
        logger.info("Recibo %s: cliente sin teléfono; no se envía WhatsApp Meta.", doc.numero)
        return EnvioResultado(False, "Cliente sin teléfono.", adjunto_pdf=False)
    pdf_bytes: bytes | None = None
    if doc.pdf_file and doc.pdf_file.name:
        try:
            doc.pdf_file.open("rb")
            pdf_bytes = doc.pdf_file.read()
        except OSError as e:
            logger.warning("Recibo %s: no se pudo leer PDF para WhatsApp: %s", doc.numero, e)
        finally:
            try:
                doc.pdf_file.close()
            except Exception:
                pass

    try:
        from core.whatsapp_cloud import enviar_recibo_whatsapp_cloud

        nombre = f"recibo_{doc.numero.replace('/', '-')}.pdf"
        cap = (
            f"Recibo {doc.numero} — ${pago.monto} — Contrato {pago.contrato.numero} — Paredes Bienes Raíces"
        )
        r = enviar_recibo_whatsapp_cloud(
            to_digits=to,
            filename=nombre,
            caption=cap,
            document_url=media_url,
            pdf_bytes=pdf_bytes,
        )
        logger.info("Recibo %s WhatsApp Meta: %s — %s", doc.numero, r.ok, r.detalle)
        if r.ok and not r.adjunto_pdf:
            logger.warning(
                "Recibo %s: WhatsApp Meta envió solo texto (sin PDF). Detalle: %s",
                doc.numero,
                r.detalle,
            )
        return r
    except Exception as e:
        logger.warning("Recibo %s: WhatsApp Meta error: %s", doc.numero, e)
        return EnvioResultado(False, str(e), adjunto_pdf=False)


def notificar_recibo_emitido(doc: "DocumentoEmitido", pago: "Pago") -> ReciboNotificacionInfo:
    """
    Tras generar el PDF: correo con adjunto; WhatsApp Meta (sube el PDF a la API, sin URL pública)
    o Twilio si aplica; URL pública opcional como respaldo para Meta.
    """
    correo_ok = enviar_recibo_por_email(doc, pago)

    base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    path = doc.pdf_file.url if doc.pdf_file else ""
    if path and not str(path).startswith("/"):
        path = "/" + str(path)
    media_url = f"{base}{path}" if base and doc.pdf_file else None
    if media_url and not media_url.lower().startswith("https://"):
        media_url = None

    twilio_pdf = False
    if media_url and getattr(settings, "RECIBO_ENVIAR_WHATSAPP_TWILIO", False):
        twilio_pdf = bool(_enviar_whatsapp_twilio(doc, pago, media_url))

    meta_r = None
    meta_on = getattr(settings, "WHATSAPP_CLOUD_ENABLED", False) and getattr(
        settings, "RECIBO_ENVIAR_WHATSAPP_META", False
    )
    if meta_on:
        meta_r = _enviar_whatsapp_meta_cloud(doc, pago, media_url)

    meta_pdf = bool(meta_r and meta_r.ok and meta_r.adjunto_pdf)
    meta_solo_texto = bool(meta_r and meta_r.ok and not meta_r.adjunto_pdf)

    wa = construir_url_whatsapp_recibo(pago.contrato.cliente, doc, pago)
    if wa:
        logger.info("Recibo %s: enlace WhatsApp (manual o seguimiento): %s", doc.numero, wa)

    return ReciboNotificacionInfo(
        correo_enviado=correo_ok,
        correo_entrega_real=bool(correo_ok and _correo_entrega_a_bandejas_reales()),
        whatsapp_pdf_por_api=meta_pdf or twilio_pdf,
        meta_configurado=meta_on,
        meta_solo_texto=meta_solo_texto,
        twilio_pdf=twilio_pdf,
    )
