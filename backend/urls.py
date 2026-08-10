"""
URLconf principal (única fuente de rutas: ping, login, dashboard, interno, admin legacy).
"""
import sys

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.views import LogoutView
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from core.pbr_icons import PBR_ICON_VERSION
from core.views import (
    PortalLoginView,
    admin_legacy_redirect,
    admin_login_to_web,
    dashboard,
    elegir_marca,
    home,
    ping,
    portal_marca,
    pbr_service_worker,
    pbr_web_manifest,
)
from core.views_whatsapp import whatsapp_webhook

urlpatterns = [
    path("pbr-sw.js", pbr_service_worker, name="pbr_service_worker"),
    path("site.webmanifest", pbr_web_manifest, name="pbr_web_manifest"),
    path(
        "favicon.ico",
        RedirectView.as_view(
            url=f"/static/icons/pwa-192.png?v={PBR_ICON_VERSION}",
            permanent=True,
        ),
    ),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp_webhook"),
    path("ping/", ping, name="ping"),
    path("", home, name="home"),
    path("elegir/", elegir_marca, name="elegir_marca"),
    path("portal/<slug:slug>/", portal_marca, name="portal_marca"),
    path("catalogo/", include("inmobiliaria.urls_catalogo")),
    path("app/", include("inmobiliaria.urls_web")),
    path("dashboard/", dashboard, name="dashboard"),
    path(
        "login/",
        PortalLoginView.as_view(),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("admin/login/", admin_login_to_web, name="legacy_admin_login"),
    path("interno/", admin.site.urls),
    re_path(r"^admin(?:/.*)?$", admin_legacy_redirect),
]

# Con media en S3/Spaces los archivos no viven en MEDIA_ROOT del contenedor.
_use_s3_media = getattr(settings, "DJANGO_USE_S3_MEDIA", False)
if settings.DEBUG and not _use_s3_media:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif (
    not _use_s3_media
    and getattr(settings, "DJANGO_SERVE_MEDIA_PUBLIC", False)
):
    _media_prefix = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").strip("/")
    if _media_prefix:
        urlpatterns += [
            re_path(
                rf"^{_media_prefix}/(?P<path>.*)$",
                serve,
                {"document_root": settings.MEDIA_ROOT},
            ),
        ]

if settings.DEBUG:
    print(
        f"[PBR] backend.urls cargado: {__file__} | rutas={len(urlpatterns)}",
        file=sys.stderr,
    )
