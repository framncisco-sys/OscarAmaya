import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse


from inmobiliaria.contratos_acceso import aplica_restriccion_contratos_por_vendedor
from usuarios.roles import (
    marcas_permitidas,
    puede_acceder_marca,
    puede_gestionar_vendedores,
    slug_unica_permitida,
)

from .dashboard_data import build_dashboard_bienes_raices_context, build_dashboard_context
from .forms import LoginForm
from .marcas import SESSION_KEY, es_bienes_raices, marca_from_session, set_marca


class PortalLoginView(LoginView):
    """Tras Entrar: si solo tiene una empresa, entra directo; si no, elige marca."""

    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        # Nueva sesión de trabajo: debe resolver marca otra vez.
        self.request.session.pop(SESSION_KEY, None)
        return super().form_valid(form)

    def get_success_url(self):
        unica = slug_unica_permitida(self.request.user)
        if unica:
            set_marca(self.request, unica)
            return reverse("dashboard")
        return reverse("elegir_marca")


def home(request: HttpRequest) -> HttpResponse:
    """La raíz solo muestra el login (misma pantalla que /login/)."""
    if request.user.is_authenticated:
        marca = marca_from_session(request)
        if marca is None:
            unica = slug_unica_permitida(request.user)
            if unica:
                set_marca(request, unica)
                return redirect("dashboard")
            return redirect("elegir_marca")
        if not puede_acceder_marca(request.user, marca.get("slug")):
            request.session.pop(SESSION_KEY, None)
            return redirect("elegir_marca")
        return redirect("dashboard")
    return PortalLoginView.as_view()(request)


@login_required
def elegir_marca(request: HttpRequest) -> HttpResponse:
    """Después del login: elegir empresa permitida (admin: ambas; resto: solo la asignada)."""
    permitidas = marcas_permitidas(request.user)
    if len(permitidas) == 1:
        set_marca(request, permitidas[0]["slug"])
        return redirect("dashboard")
    if not permitidas:
        return redirect("dashboard")
    return render(
        request,
        "core/elegir_marca.html",
        {"marcas": permitidas},
    )


@login_required
def portal_marca(request: HttpRequest, slug: str) -> HttpResponse:
    """Guarda la marca elegida y entra al sistema (solo si el usuario tiene permiso)."""
    if not puede_acceder_marca(request.user, slug):
        return redirect("elegir_marca")
    marca = set_marca(request, slug)
    if marca is None:
        return redirect("elegir_marca")
    return redirect("dashboard")


def admin_login_to_web(request: HttpRequest) -> HttpResponse:
    """Bookmarks viejos: /admin/login/ -> nuestro /login/ (no el login del admin)."""
    url = f"{reverse('login')}?next={reverse('elegir_marca')}"
    return redirect(url)

def admin_legacy_redirect(request: HttpRequest) -> HttpResponse:
    """Cualquier otra ruta bajo /admin/... -> app web o login."""
    if request.user.is_authenticated:
        if marca_from_session(request) is None:
            return redirect("elegir_marca")
        return redirect("dashboard")
    return redirect(f"{reverse('login')}?next={reverse('elegir_marca')}")


def ping(request: HttpRequest) -> HttpResponse:
    """Comprueba que el servidor usa ESTE proyecto y esta URLconf."""
    from django.urls import get_resolver

    if request.GET.get("db") == "1" and (
        settings.DEBUG or os.environ.get("PBR_ALLOW_DB_PING") == "1"
    ):
        db = settings.DATABASES["default"]
        payload = {
            "db_engine": db.get("ENGINE"),
            "db_host": db.get("HOST"),
            "db_port": db.get("PORT"),
            "db_name": db.get("NAME"),
            "db_user": db.get("USER"),
            "db_has_password": bool(db.get("PASSWORD")),
            "env_has_DATABASE_URL": bool(os.environ.get("DATABASE_URL")),
            "hint": (
                "Si db_host es localhost en App Platform, defina DATABASE_URL o POSTGRES_* "
                "en el Web Service (deploy/DIGITALOCEAN.md)."
            ),
        }
        return HttpResponse(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )

    r = get_resolver()
    names = [getattr(p, "name", None) for p in r.url_patterns]
    return HttpResponse(
        f"PBR_OK rutas_superiores={len(r.url_patterns)} nombres={names}",
        content_type="text/plain; charset=utf-8",
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    from inmobiliaria.vendedor_acceso import es_vendedor_restringido

    marca = marca_from_session(request)
    if marca is None:
        unica = slug_unica_permitida(request.user)
        if unica:
            set_marca(request, unica)
            marca = marca_from_session(request)
        else:
            return redirect("elegir_marca")
    elif not puede_acceder_marca(request.user, marca.get("slug")):
        request.session.pop(SESSION_KEY, None)
        unica = slug_unica_permitida(request.user)
        if unica:
            set_marca(request, unica)
            marca = marca_from_session(request)
        else:
            return redirect("elegir_marca")

    # Vendedor de campo: no ve el dashboard completo, solo el flujo de venta.
    if es_vendedor_restringido(request.user):
        return redirect("app:index")

    kwargs = dict(
        user=request.user,
        incluir_vendedores=puede_gestionar_vendedores(request.user),
        contratos_restringidos=aplica_restriccion_contratos_por_vendedor(request.user),
    )
    if es_bienes_raices(marca):
        context = build_dashboard_bienes_raices_context(**kwargs)
        return render(request, "core/dashboard_bienes_raices.html", context)

    context = build_dashboard_context(**kwargs)
    return render(request, "core/dashboard.html", context)


def pbr_service_worker(_request: HttpRequest) -> HttpResponse:
    """Service Worker en la raíz del sitio (alcance /) para caché y modo sin conexión."""
    path = Path(settings.BASE_DIR) / "static" / "pbr-sw.js"
    body = path.read_text(encoding="utf-8")
    resp = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    resp["Cache-Control"] = "no-store, max-age=0"
    return resp


def pbr_web_manifest(_request: HttpRequest) -> HttpResponse:
    """Manifest PWA (instalable); iconos vía estáticos si existen."""
    payload = {
        "name": "Paredes Bienes Raíces",
        "short_name": "PBR",
        "description": "Gestión inmobiliaria, contratos y cartera.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": "#1a2d42",
        "lang": "es-SV",
        "icons": [
            {
                "src": "/static/favicon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            }
        ],
    }
    return HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        content_type="application/manifest+json; charset=utf-8",
    )
