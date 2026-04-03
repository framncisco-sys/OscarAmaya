from __future__ import annotations

import uuid

from django.http import HttpRequest, HttpResponse

from .context import RequestContext, set_request_context


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            user_id = getattr(getattr(request, "user", None), "id", None)
        except Exception:
            user_id = None

        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get(
            "REMOTE_ADDR"
        )
        ua = request.META.get("HTTP_USER_AGENT")
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

        set_request_context(
            RequestContext(user_id=user_id, ip_address=ip, user_agent=ua, request_id=request_id)
        )
        try:
            return self.get_response(request)
        finally:
            set_request_context(None)

