"""
Webhook de WhatsApp Cloud API (Meta): verificación GET y recepción POST en la misma URL.

En Meta Developers → WhatsApp → Configuration:
  - Callback URL: https://SU_DOMINIO/webhooks/whatsapp/
  - Verify token: el mismo valor que WHATSAPP_WEBHOOK_VERIFY_TOKEN en .env

Referencia: https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)


def _verify_get(request: HttpRequest) -> HttpResponse:
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token")
    challenge = request.GET.get("hub.challenge")

    expected = (getattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "") or "").strip()
    if mode == "subscribe" and token and expected and token == expected and challenge:
        return HttpResponse(challenge, content_type="text/plain")

    return HttpResponse("Forbidden", status=403)


def _receive_post(request: HttpRequest) -> HttpResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)

    try:
        logger.info("WhatsApp webhook payload: %s", json.dumps(payload)[:2000])
    except Exception:
        pass

    return HttpResponse(status=200)


@csrf_exempt
def whatsapp_webhook(request: HttpRequest) -> HttpResponse:
    """Un solo endpoint: GET verificación Meta, POST eventos."""
    if request.method == "GET":
        return _verify_get(request)
    if request.method == "POST":
        return _receive_post(request)
    return HttpResponseNotAllowed(["GET", "POST"])
