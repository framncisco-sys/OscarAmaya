"""Middleware de diagnóstico y zona horaria El Salvador."""

from __future__ import annotations

import sys

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin


class UrlConfProbeMiddleware(MiddlewareMixin):
    """Expone qué `backend.urls` cargó el proceso (útil si hay otro servidor en el puerto)."""

    def __init__(self, get_response):
        super().__init__(get_response)
        import backend.urls as u

        self._routes = str(len(u.urlpatterns))
        self._file = u.__file__
        print(
            f"[PBR] UrlConfProbeMiddleware activo rutas={self._routes} file={self._file}",
            file=sys.stderr,
        )

    def process_response(self, request, response):
        response.headers["X-PBR-URLconf-Routes"] = self._routes
        response.headers["X-PBR-URLconf-File"] = self._file
        return response


class ElSalvadorTimezoneMiddleware:
    """Activa America/El_Salvador en cada request (fechas/horas locales SV)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate("America/El_Salvador")
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
