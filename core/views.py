import json
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from django.db.models import Count, Q
from django.utils import timezone

from inmobiliaria.models import Cliente, Contrato, Inmueble, Poligono, Proyecto, Vendedor

from usuarios.roles import puede_gestionar_vendedores


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboard")
    # Pagina de entrada con enlaces claros (evita pegar texto extra en la URL).
    return render(request, "core/entrada.html")


def admin_login_to_web(request: HttpRequest) -> HttpResponse:
    """Bookmarks viejos: /admin/login/ -> nuestro /login/ (no el login del admin)."""
    url = f"{reverse('login')}?next=/dashboard/"
    return redirect(url)


def admin_legacy_redirect(request: HttpRequest) -> HttpResponse:
    """Cualquier otra ruta bajo /admin/... -> app web o login."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect(f"{reverse('login')}?next=/dashboard/")


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
    poligonos = (
        Poligono.objects.select_related("proyecto")
        .annotate(
            total_lotes=Count("lotes", distinct=True),
            vendidos=Count("lotes", filter=Q(lotes__estado=Inmueble.Estado.VENDIDO), distinct=True),
            reservados=Count("lotes", filter=Q(lotes__estado=Inmueble.Estado.RESERVADO), distinct=True),
            disponibles=Count("lotes", filter=Q(lotes__estado=Inmueble.Estado.DISPONIBLE), distinct=True),
        )
        .order_by("-vendidos", "-reservados", "proyecto__nombre", "orden", "nombre")[:20]
    )
    hoy = timezone.localdate()
    limite = hoy + timedelta(days=7)
    reservas_por_vencer = (
        Inmueble.objects.filter(
            estado=Inmueble.Estado.RESERVADO,
            reserva_hasta__gte=hoy,
            reserva_hasta__lte=limite,
        )
        .select_related("proyecto", "cliente_reserva")
        .order_by("reserva_hasta")[:12]
    )
    reservas_vencidas_ct = Inmueble.objects.filter(
        estado=Inmueble.Estado.RESERVADO,
        reserva_hasta__isnull=False,
        reserva_hasta__lt=hoy,
    ).count()

    context = {
        "total_proyectos": Proyecto.objects.count(),
        "total_inmuebles": Inmueble.objects.count(),
        "total_clientes": Cliente.objects.count(),
        "total_contratos": Contrato.objects.count(),
        "ultimos_inmuebles": Inmueble.objects.select_related("proyecto").order_by("-id")[:8],
        "poligono_stats": poligonos,
        "reservas_por_vencer": reservas_por_vencer,
        "reservas_vencidas_ct": reservas_vencidas_ct,
    }
    if puede_gestionar_vendedores(request.user):
        context["total_vendedores"] = Vendedor.objects.count()
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
