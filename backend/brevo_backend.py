"""Backend de correo vía API HTTPS de Brevo (Sendinblue).

Evita los puertos SMTP 25/465/587 bloqueados en DigitalOcean Droplets.
Documentación: https://developers.brevo.com/docs/send-a-transactional-email
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def _solo_email(valor: str) -> str:
    nombre, addr = parseaddr((valor or "").strip())
    return (addr or valor or "").strip()


def _partir_from(valor: str) -> tuple[str, str]:
    nombre, addr = parseaddr((valor or "").strip())
    addr = (addr or "").strip()
    nombre = (nombre or "").strip()
    if not addr and valor:
        m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", valor)
        if m:
            addr = m.group(0)
    return nombre, addr


class BrevoAPIEmailBackend(BaseEmailBackend):
    """Envía con la API transaccional de Brevo (plan Free, HTTPS)."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
        if not api_key:
            if not self.fail_silently:
                raise RuntimeError(
                    "Falta BREVO_API_KEY en el entorno (.env). "
                    "Créela en Brevo → SMTP & API → API keys."
                )
            return 0

        enviados = 0
        for message in email_messages:
            try:
                self._enviar_uno(message, api_key)
                enviados += 1
            except Exception:
                logger.exception("Brevo: fallo al enviar correo")
                if not self.fail_silently:
                    raise
        return enviados

    def _enviar_uno(self, message, api_key: str) -> None:
        from_email = message.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        from_name, from_addr = _partir_from(from_email)
        if not from_addr:
            from_addr = _solo_email(getattr(settings, "EMAIL_HOST_USER", "") or "")
        if not from_name:
            from_name = (
                getattr(settings, "DEFAULT_FROM_EMAIL_NAME", "") or ""
            ).strip() or "Paredes Desarrollos Inmobiliarios"

        to_list = []
        for raw in message.to or []:
            n, a = _partir_from(raw)
            if a:
                item = {"email": a}
                if n:
                    item["name"] = n
                to_list.append(item)
        if not to_list:
            raise ValueError("El mensaje no tiene destinatarios")

        payload: dict = {
            "sender": {"name": from_name, "email": from_addr},
            "to": to_list,
            "subject": message.subject or "(sin asunto)",
        }

        body = message.body or ""
        subtype = getattr(message, "content_subtype", "plain") or "plain"
        if subtype == "html":
            payload["htmlContent"] = body
        else:
            payload["textContent"] = body

        # CC / BCC
        for attr, key in (("cc", "cc"), ("bcc", "bcc")):
            raws = getattr(message, attr, None) or []
            items = []
            for raw in raws:
                n, a = _partir_from(raw)
                if a:
                    it = {"email": a}
                    if n:
                        it["name"] = n
                    items.append(it)
            if items:
                payload[key] = items

        # Adjuntos (PDF de recibos, etc.)
        attachments = []
        for filename, content, mimetype in getattr(message, "attachments", []) or []:
            if hasattr(content, "read"):
                content = content.read()
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not isinstance(content, (bytes, bytearray)):
                continue
            attachments.append(
                {
                    "name": filename or "adjunto.bin",
                    "content": base64.b64encode(bytes(content)).decode("ascii"),
                }
            )
        if attachments:
            payload["attachment"] = attachments

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            BREVO_SEND_URL,
            data=data,
            method="POST",
            headers={
                "api-key": api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if resp.status not in (200, 201, 202):
                    raise RuntimeError(f"Brevo HTTP {resp.status}: {raw[:500]}")
                logger.info("Brevo: correo enviado OK (%s)", raw[:200])
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"Brevo HTTP {e.code}: {detail}") from e
