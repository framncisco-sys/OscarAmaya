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

from inmobiliaria.phone_sv import digitos_telefono_e164_sv

from .recibo_text import format_monto_sv

logger = logging.getLogger(__name__)


def _url_archivo_field_absoluta_o_ruta(file_field) -> str | None:
    """
    URL del archivo: absoluta (https://…) con S3/Spaces o ruta relativa (/media/…) en disco local.
    """
    if not file_field or not file_field.name:
        return None
    u = str(file_field.url)
    if u.lower().startswith(("http://", "https://")):
        return u
    return u if u.startswith("/") else f"/{u}"


@dataclass(frozen=True)
class ReciboNotificacionInfo:
    """Resultado de notificar un recibo (para mensajes en la interfaz)."""

    correo_enviado: bool
    """True si se llamó a send() sin excepción (puede ser solo consola / dummy)."""
    correo_entrega_real: bool
    """True solo si hay SMTP/API real y el backend no es consola/dummy."""
    whatsapp_pdf_por_api: bool
    meta_configurado: bool
    meta_solo_texto: bool
    twilio_pdf: bool
    correo_destinos: tuple[str, ...] = ()
    """Bandejas a las que se intentó enviar (cliente y/o oficina)."""
    whatsapp_manual_url: str | None = None
    """Enlace wa.me para abrir el chat del cliente (si hay teléfono)."""


def _correo_entrega_a_bandejas_reales() -> bool:
    """Sin EMAIL_HOST/API o con QuietConsole el mensaje no llega a bandejas reales."""
    be = (getattr(settings, "EMAIL_BACKEND", "") or "").strip()
    if "QuietConsole" in be or be.endswith("console.EmailBackend") or "dummy" in be.lower():
        return False
    if "brevo" in be.lower():
        return True
    if not (getattr(settings, "EMAIL_HOST", "") or "").strip():
        return False
    return True


def _formato_vinculado_pago(pago: "Pago"):
    fmt = getattr(pago, "formato_aceptacion", None)
    if fmt is not None:
        return fmt
    contrato = getattr(pago, "contrato", None)
    if contrato is None:
        return None
    rel = getattr(contrato, "formatos_aceptacion", None)
    if rel is None:
        return None
    return rel.order_by("-id").first()


def telefono_para_recibo(pago: "Pago") -> str:
    """Teléfono del cliente o, si falta, el del formato de aceptación vinculado."""
    cliente = pago.contrato.cliente
    t = (getattr(cliente, "telefono", "") or "").strip()
    if t:
        return t
    fmt = _formato_vinculado_pago(pago)
    if fmt is None:
        return ""
    for raw in (
        getattr(fmt, "telefono_notificacion", None),
        getattr(fmt, "telefono_domicilio", None),
        getattr(fmt, "telefono_trabajo", None),
    ):
        s = (raw or "").strip()
        if s:
            return s
    return ""


def email_cliente_para_recibo(pago: "Pago") -> str:
    return (getattr(pago.contrato.cliente, "email", None) or "").strip()


def email_oficina_recibo() -> str:
    fallback = (getattr(settings, "RECIBO_EMAIL_FALLBACK", "") or "").strip()
    return fallback or "paredesinmobi@gmail.com"


def url_pdf_publica_https(doc: "DocumentoEmitido") -> str | None:
    """
    URL absoluta HTTPS al PDF (S3/Spaces o /media/... con PUBLIC_BASE_URL).
    """
    rel_or_abs = _url_archivo_field_absoluta_o_ruta(doc.pdf_file)
    if not rel_or_abs:
        return None
    if rel_or_abs.lower().startswith("https://"):
        return rel_or_abs
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not base:
        return None
    url = f"{base}{rel_or_abs}"
    if not url.lower().startswith("https://"):
        return None
    return url


def url_pdf_enlace_absoluto(doc: "DocumentoEmitido") -> str | None:
    """
    URL al PDF (https directo desde Spaces o http(s) con PUBLIC_BASE_URL + /media/...).
    """
    rel_or_abs = _url_archivo_field_absoluta_o_ruta(doc.pdf_file)
    if not rel_or_abs:
        return None
    if rel_or_abs.lower().startswith(("http://", "https://")):
        return rel_or_abs
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}{rel_or_abs}"


def _telefono_a_whatsapp(telefono: str) -> str | None:
    return digitos_telefono_e164_sv(telefono)


def construir_mensaje_whatsapp_recibo(
    cliente,
    doc: "DocumentoEmitido",
    pago: "Pago",
    *,
    incluir_enlace_pdf: bool = True,
) -> str:
    """Texto del recibo para WhatsApp (el mismo mensaje que ya usábamos)."""
    nombre = (getattr(cliente, "nombres", "") or "").strip() or "estimado cliente"
    partes = [
        f"Hola {nombre}, le informamos que su recibo *{doc.numero}* "
        f"por *${pago.monto}* (contrato {pago.contrato.numero}) fue registrado.",
        "",
    ]
    if incluir_enlace_pdf:
        pdf_url = url_pdf_enlace_absoluto(doc) or url_pdf_publica_https(doc)
        if pdf_url:
            partes.append("Descargue su recibo en PDF aquí:")
            partes.append(pdf_url)
            partes.append("")
        else:
            partes.append("El PDF del recibo va adjunto en este mensaje.")
            partes.append("")
    else:
        # Al compartir con archivo adjunto no hace falta el enlace.
        partes.append("Le compartimos el PDF del recibo adjunto en este mensaje.")
        partes.append("")
    empresa_wa = (getattr(settings, "RECIBO_NOTIFICACION_EMPRESA_NOMBRE", "") or "").strip()
    if not empresa_wa:
        empresa_wa = "Paredes Desarrollos Inmobiliarios"
    partes.append(f"— {empresa_wa}")
    return "\n".join(partes)


def construir_url_whatsapp_recibo(cliente, doc: "DocumentoEmitido", pago: "Pago") -> str | None:
    """
    URL wa.me con mensaje prellenado.

    El enlace wa.me solo abre el chat con texto; no adjunta archivos.
    Para PDF + mensaje juntos use la pantalla de compartir (teléfono) o Meta Cloud API.
    """
    tel_raw = telefono_para_recibo(pago) or (getattr(cliente, "telefono", "") or "")
    tel = _telefono_a_whatsapp(tel_raw)
    if not tel:
        return None
    texto = construir_mensaje_whatsapp_recibo(cliente, doc, pago, incluir_enlace_pdf=True)
    return f"https://wa.me/{tel}?text={urllib.parse.quote(texto)}"


def datos_envio_whatsapp_personal(
    cliente, doc: "DocumentoEmitido", pago: "Pago"
) -> dict | None:
    """
    Datos para que el vendedor envíe con su WhatsApp personal:
    URL wa.me + mensaje (con y sin enlace) para compartir PDF+texto de un solo.
    """
    tel_raw = telefono_para_recibo(pago) or (getattr(cliente, "telefono", "") or "")
    tel = _telefono_a_whatsapp(tel_raw)
    if not tel:
        return None
    msg_con_enlace = construir_mensaje_whatsapp_recibo(
        cliente, doc, pago, incluir_enlace_pdf=True
    )
    msg_con_adjunto = construir_mensaje_whatsapp_recibo(
        cliente, doc, pago, incluir_enlace_pdf=False
    )
    return {
        "telefono": tel,
        "wa_url": f"https://wa.me/{tel}?text={urllib.parse.quote(msg_con_enlace)}",
        "mensaje": msg_con_adjunto,
        "mensaje_con_enlace": msg_con_enlace,
        "pdf_nombre": f"{doc.numero.replace('/', '-')}.pdf",
    }


def destinos_email_recibo(pago: "Pago") -> tuple[list[str], bool]:
    """
    Destinos del recibo: siempre la bandeja de oficina (RECIBO_EMAIL_FALLBACK)
    y, si existe, también el correo del cliente.

    Returns: (lista_emails, solo_oficina)
    """
    cliente_email = email_cliente_para_recibo(pago)
    oficina = email_oficina_recibo()
    destinos: list[str] = []
    if cliente_email:
        destinos.append(cliente_email)
    if oficina and oficina.lower() not in {d.lower() for d in destinos}:
        destinos.append(oficina)
    solo_oficina = bool(destinos) and (not cliente_email)
    return destinos, solo_oficina


def enviar_recibo_por_email(doc: "DocumentoEmitido", pago: "Pago") -> tuple[bool, tuple[str, ...]]:
    """
    Envía el PDF del recibo por correo.
    Returns: (ok, destinos intentados)
    """
    if not getattr(settings, "RECIBO_ENVIAR_EMAIL", True):
        return False, ()
    cliente = pago.contrato.cliente
    destinos, solo_oficina = destinos_email_recibo(pago)
    if not destinos:
        logger.warning(
            "Recibo %s: sin email de cliente ni RECIBO_EMAIL_FALLBACK; no se envía correo.",
            doc.numero,
        )
        return False, ()
    if solo_oficina:
        logger.info(
            "Recibo %s: cliente sin email; se envía a bandeja de oficina %s",
            doc.numero,
            destinos[0],
        )
    else:
        logger.info(
            "Recibo %s: se envía a %s",
            doc.numero,
            ", ".join(destinos),
        )
    if not doc.pdf_file or not doc.pdf_file.name:
        return False, tuple(destinos)

    try:
        doc.pdf_file.open("rb")
        pdf_bytes = doc.pdf_file.read()
    except OSError as e:
        logger.warning("Recibo %s: no se pudo leer PDF: %s", doc.numero, e)
        return False, tuple(destinos)
    finally:
        try:
            doc.pdf_file.close()
        except Exception:
            pass

    wa_url = construir_url_whatsapp_recibo(cliente, doc, pago)

    nombre_completo = f"{cliente.nombres} {cliente.apellidos}".strip()
    empresa = (getattr(settings, "RECIBO_NOTIFICACION_EMPRESA_NOMBRE", "") or "").strip()
    if not empresa:
        empresa = "Paredes Desarrollos Inmobiliarios"
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
            "email_es_fallback": solo_oficina,
        },
    ).strip()
    if solo_oficina:
        body = (
            f"[Aviso interno] El cliente «{nombre_completo}» no tiene correo registrado. "
            f"Este recibo llegó a la bandeja de oficina ({', '.join(destinos)}).\n\n"
            + body
        )
    elif len(destinos) > 1:
        body = (
            f"[Copia oficina] Recibo del cliente «{nombre_completo}». "
            f"Destinatarios: {', '.join(destinos)}.\n\n"
            + body
        )

    nombre_archivo = f"recibo_{doc.numero.replace('/', '-')}.pdf"
    msg = EmailMessage(
        subject=getattr(
            settings,
            "RECIBO_EMAIL_ASUNTO",
            "Constancia de pago registrada — Paredes Desarrollos Inmobiliarios (PDF adjunto)",
        ),
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=destinos,
    )
    msg.attach(nombre_archivo, pdf_bytes, "application/pdf")

    try:
        msg.send(fail_silently=False)
        logger.info(
            "Recibo %s: mensaje pasado al backend de correo → %s",
            doc.numero,
            ", ".join(destinos),
        )
        be = getattr(settings, "EMAIL_BACKEND", "") or ""
        if (
            "QuietConsole" in be
            or be == "django.core.mail.backends.console.EmailBackend"
            or be == "django.core.mail.backends.dummy.EmailBackend"
        ):
            logger.warning(
                "Recibo %s: EMAIL_BACKEND no usa SMTP/API real; nadie recibirá el correo en bandeja. "
                "Configure EMAIL_BACKEND (Brevo/SMTP) y credenciales en .env.",
                doc.numero,
            )
        return True, tuple(destinos)
    except Exception as e:
        logger.exception("Recibo %s: fallo al enviar email: %s", doc.numero, e)
        return False, tuple(destinos)


def _enviar_whatsapp_twilio(doc: "DocumentoEmitido", pago: "Pago", media_url: str | None) -> bool:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "") or ""
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    from_wa = getattr(settings, "TWILIO_WHATSAPP_FROM", "") or ""
    if not (sid and token and from_wa):
        return False
    to = _telefono_a_whatsapp(telefono_para_recibo(pago))
    if not to:
        return False
    to_wa = f"whatsapp:+{to}"
    try:
        import urllib.request
        import base64

        em = (getattr(settings, "RECIBO_NOTIFICACION_EMPRESA_NOMBRE", "") or "").strip()
        if not em:
            em = "Paredes Desarrollos Inmobiliarios"
        body = (
            f"Recibo {doc.numero} por ${pago.monto} — Contrato {pago.contrato.numero}. "
            f"{em}."
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
    # Opt-out: RECIBO_ENVIAR_WHATSAPP_META=0. Por defecto, si Meta Cloud está activo, se envía.
    if not getattr(settings, "RECIBO_ENVIAR_WHATSAPP_META", True):
        return None
    to = _telefono_a_whatsapp(telefono_para_recibo(pago))
    if not to:
        logger.info(
            "Recibo %s: sin teléfono (cliente/formato); no se envía WhatsApp Meta.",
            doc.numero,
        )
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
        em = (getattr(settings, "RECIBO_NOTIFICACION_EMPRESA_NOMBRE", "") or "").strip()
        if not em:
            em = "Paredes Desarrollos Inmobiliarios"
        cap = f"Recibo {doc.numero} — ${pago.monto} — Contrato {pago.contrato.numero} — {em}"
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
    Tras generar el PDF: envía automáticamente
    - correo con PDF adjunto a la bandeja de oficina y, si existe, al cliente;
    - WhatsApp (Meta Cloud o Twilio) si hay teléfono y la API está configurada;
      si no hay API, se deja enlace wa.me para abrir el chat con el mensaje.
    """
    correo_ok, destinos = enviar_recibo_por_email(doc, pago)

    rel_or_abs = _url_archivo_field_absoluta_o_ruta(doc.pdf_file) if doc.pdf_file else None
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

    twilio_pdf = False
    if media_url and getattr(settings, "RECIBO_ENVIAR_WHATSAPP_TWILIO", False):
        twilio_pdf = bool(_enviar_whatsapp_twilio(doc, pago, media_url))

    meta_r = None
    meta_on = getattr(settings, "WHATSAPP_CLOUD_ENABLED", False) and getattr(
        settings, "RECIBO_ENVIAR_WHATSAPP_META", True
    )
    if meta_on:
        meta_r = _enviar_whatsapp_meta_cloud(doc, pago, media_url)

    meta_pdf = bool(meta_r and meta_r.ok and meta_r.adjunto_pdf)
    meta_solo_texto = bool(meta_r and meta_r.ok and not meta_r.adjunto_pdf)

    wa = construir_url_whatsapp_recibo(pago.contrato.cliente, doc, pago)
    if wa:
        logger.info("Recibo %s: enlace WhatsApp (manual o seguimiento): %s", doc.numero, wa)
    elif not (meta_pdf or twilio_pdf):
        logger.warning(
            "Recibo %s: sin teléfono del cliente/formato; no se puede abrir WhatsApp.",
            doc.numero,
        )

    return ReciboNotificacionInfo(
        correo_enviado=correo_ok,
        correo_entrega_real=bool(correo_ok and _correo_entrega_a_bandejas_reales()),
        whatsapp_pdf_por_api=meta_pdf or twilio_pdf,
        meta_configurado=meta_on,
        meta_solo_texto=meta_solo_texto,
        twilio_pdf=twilio_pdf,
        correo_destinos=destinos,
        whatsapp_manual_url=wa,
    )
