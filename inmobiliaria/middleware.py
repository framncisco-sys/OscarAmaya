"""Restricción de rutas para vendedores de campo (solo flujo de venta)."""

from __future__ import annotations

from django.utils.deprecation import MiddlewareMixin


class VendedorFlujoMiddleware(MiddlewareMixin):
    """
    Bloquea URLs del namespace `app` fuera del allowlist del vendedor.
    Cubre vistas basadas en función que no usan AppLoginRequiredMixin.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        from inmobiliaria.vendedor_acceso import redirigir_vendedor_si_fuera_de_flujo

        return redirigir_vendedor_si_fuera_de_flujo(request)
