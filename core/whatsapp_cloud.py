"""
Cliente de WhatsApp Cloud API (Meta).

Documentación: https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started

Envío de recibos PDF: subida a Meta (``/media``) o ``document.link`` con URL HTTPS alcanzable.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def _max_pdf_bytes() -> int:
    return int(getattr(settings, "WHATSAPP_MAX_PDF_BYTES", 100 * 1024 * 1024) or 100 * 1024 * 1024)


def _url_host_alcanzable_por_meta(url: str) -> bool:
    """
    True si el host no es obviamente localhost / solo RFC1918.
    Meta descarga ``document.link`` desde sus servidores; 127.0.0.1 o LAN no sirven.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            return False
        if host in ("localhost",) or host.endswith(".local"):
            return False
        try:
            ip = ipaddress.ip_address(host)
            return bool(ip.is_global)
        except ValueError:
            return True
    except Exception:
        return False


class WhatsAppCloudError(Exception):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _config() -> tuple[str, str, str]:
    token = (getattr(settings, "WHATSAPP_CLOUD_ACCESS_TOKEN", "") or "").strip()
    phone_id = (getattr(settings, "WHATSAPP_CLOUD_PHONE_NUMBER_ID", "") or "").strip()
    version = (getattr(settings, "WHATSAPP_CLOUD_API_VERSION", "v21.0") or "v21.0").strip()
    return token, phone_id, version


def is_configured() -> bool:
    token, phone_id, _ = _config()
    return bool(token and phone_id)


def _post_messages(payload: dict[str, Any]) -> dict[str, Any]:
    token, phone_id, version = _config()
    if not token or not phone_id:
        raise WhatsAppCloudError("WhatsApp Cloud no configurado (token o Phone Number ID vacíos).")

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("WhatsApp Cloud HTTP %s: %s", e.code, body)
        raise WhatsAppCloudError(f"Error {e.code}", status=e.code, body=body) from e


def upload_pdf_media(*, pdf_bytes: bytes, filename: str) -> str:
    """
    Sube el PDF a Meta y devuelve el id de medio (usar en seguida en el mensaje document).
    """
    limite = _max_pdf_bytes()
    if len(pdf_bytes) > limite:
        raise WhatsAppCloudError(
            f"PDF demasiado grande ({len(pdf_bytes)} bytes; máximo {limite}). WhatsApp rechazará el envío.",
        )

    token, phone_id, version = _config()
    if not token or not phone_id:
        raise WhatsAppCloudError("WhatsApp Cloud no configurado.")

    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    boundary = f"----PBRWA{uuid.uuid4().hex}"
    nl = b"\r\n"
    sep = f"--{boundary}".encode()
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename) or "recibo"
    base = base[-80:].strip("._") or "recibo"
    safe_name = base if base.lower().endswith(".pdf") else f"{base}.pdf"

    parts: list[bytes] = [
        sep,
        nl,
        b'Content-Disposition: form-data; name="messaging_product"',
        nl,
        nl,
        b"whatsapp",
        nl,
        sep,
        nl,
        b'Content-Disposition: form-data; name="type"',
        nl,
        nl,
        b"application/pdf",
        nl,
        sep,
        nl,
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"'.encode(),
        nl,
        b"Content-Type: application/pdf",
        nl,
        nl,
        pdf_bytes,
        nl,
        f"--{boundary}--".encode(),
        nl,
    ]
    body = b"".join(parts)

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        logger.warning("WhatsApp Cloud upload HTTP %s: %s", e.code, err_body)
        raise WhatsAppCloudError(f"Upload error {e.code}", status=e.code, body=err_body) from e

    mid = data.get("id")
    if not mid:
        raise WhatsAppCloudError(f"Upload sin id en respuesta: {raw[:800]}")
    return str(mid)


def send_text_message(*, to_digits: str, body: str) -> dict[str, Any]:
    """
    to_digits: número internacional sin + (ej. 50371234567).
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_digits,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    return _post_messages(payload)


def send_document_link(
    *,
    to_digits: str,
    document_url: str,
    filename: str,
    caption: str = "",
) -> dict[str, Any]:
    """Envía un documento por URL pública (HTTPS)."""
    doc: dict[str, Any] = {
        "link": document_url,
        "filename": filename[:240],
    }
    if caption:
        doc["caption"] = caption[:1024]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_digits,
        "type": "document",
        "document": doc,
    }
    return _post_messages(payload)


def send_document_by_media_id(
    *,
    to_digits: str,
    media_id: str,
    filename: str,
    caption: str = "",
) -> dict[str, Any]:
    """Envía un documento previamente subido a /media."""
    doc: dict[str, Any] = {
        "id": media_id,
        "filename": filename[:240],
    }
    if caption:
        doc["caption"] = caption[:1024]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_digits,
        "type": "document",
        "document": doc,
    }
    return _post_messages(payload)


@dataclass
class EnvioResultado:
    ok: bool
    detalle: str
    # True si el cliente recibió mensaje tipo documento (PDF), no solo texto.
    adjunto_pdf: bool = False


def enviar_recibo_whatsapp_cloud(
    *,
    to_digits: str,
    filename: str,
    caption: str,
    document_url: str | None = None,
    pdf_bytes: bytes | None = None,
) -> EnvioResultado:
    """
    Envía el PDF por WhatsApp: primero subiendo a Meta (recomendado), luego por URL HTTPS,
    y como último recurso solo texto.
    """
    if not is_configured():
        return EnvioResultado(False, "WhatsApp Cloud no configurado.", adjunto_pdf=False)

    limite = _max_pdf_bytes()
    if pdf_bytes and len(pdf_bytes) > limite:
        logger.warning(
            "WhatsApp: PDF de %s bytes supera WHATSAPP_MAX_PDF_BYTES (%s); no se sube a Meta.",
            len(pdf_bytes),
            limite,
        )
        pdf_bytes = None

    if pdf_bytes:
        try:
            mid = upload_pdf_media(pdf_bytes=pdf_bytes, filename=filename)
            send_document_by_media_id(
                to_digits=to_digits,
                media_id=mid,
                filename=filename,
                caption=caption,
            )
            return EnvioResultado(
                True, "PDF enviado por WhatsApp (subido a Meta).", adjunto_pdf=True
            )
        except WhatsAppCloudError as e:
            logger.warning(
                "WhatsApp: envío por subida a Meta falló (%s). Se probará URL pública si existe.",
                (e.body or str(e))[:500],
            )

    if document_url and document_url.lower().startswith("https://"):
        if not _url_host_alcanzable_por_meta(document_url):
            logger.warning(
                "WhatsApp: document.link omitido: la URL no es alcanzable desde internet "
                "(localhost/LAN). Use subida a Meta (bytes) o un dominio público HTTPS. URL: %s",
                document_url[:200],
            )
        else:
            try:
                send_document_link(
                    to_digits=to_digits,
                    document_url=document_url,
                    filename=filename,
                    caption=caption,
                )
                return EnvioResultado(
                    True,
                    "PDF enviado por URL pública (Meta descarga el archivo).",
                    adjunto_pdf=True,
                )
            except WhatsAppCloudError as e:
                logger.warning(
                    "WhatsApp: documento por URL falló (¿MIME application/pdf?, ¿401?, URL no pública?): %s",
                    (e.body or str(e))[:500],
                )

    try:
        extra = ""
        if document_url:
            extra = f"\n\nEnlace al PDF: {document_url}"
        elif not pdf_bytes:
            extra = "\n\n(No hay PDF ni URL pública HTTPS configurada.)"
        body = f"{caption}{extra}"[:4090]
        send_text_message(to_digits=to_digits, body=body)
        return EnvioResultado(
            True,
            "Solo texto: el PDF no pudo enviarse (causas habituales: URL no HTTPS pública, "
            "host localhost/LAN, PDF demasiado grande, token/permisos Meta, o servidor entrega "
            "el PDF con Content-Type distinto de application/pdf).",
            adjunto_pdf=False,
        )
    except WhatsAppCloudError as e2:
        return EnvioResultado(False, str(e2) or (e2.body or ""), adjunto_pdf=False)
