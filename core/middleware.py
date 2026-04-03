"""Middleware de diagnóstico: cabeceras en cada respuesta (incl. 404 DEBUG)."""

from __future__ import annotations

import sys

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
