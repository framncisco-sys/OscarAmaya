from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class AppUsuarioActivoMiddleware:
    """Bloquea /app/ si el perfil existe y está marcado inactivo para la gestión web."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if path.startswith("/app/") and request.user.is_authenticated:
            from django.contrib.auth import logout

            from .roles import puede_acceder_app

            if not puede_acceder_app(request.user):
                logout(request)
                messages.warning(
                    request,
                    "Su usuario no está habilitado para la gestión web. Consulte a un administrador.",
                )
                return redirect(reverse("login"))

        return self.get_response(request)
