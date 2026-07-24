"""Catálogo público de solo lectura: inmuebles disponibles e imágenes de marketing."""

from __future__ import annotations

import io
from urllib.parse import urlencode

from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .models import Inmueble, InmuebleImagen, Proyecto


def _inmuebles_publicos_qs():
    """
    Catálogo público del sistema Paredes Bienes Raíces:
    alquileres + venta de casas/locales (no lotes de lotificación de Desarrollos).
    """
    return (
        Inmueble.objects.filter(
            estado=Inmueble.Estado.DISPONIBLE,
            proyecto__activo=True,
        )
        .filter(
            Q(en_alquiler=True)
            | Q(
                tipo__in=(
                    Inmueble.Tipo.CASA_NUEVA,
                    Inmueble.Tipo.CASA_SEGUNDA,
                    Inmueble.Tipo.LOCAL,
                )
            )
        )
        .select_related("proyecto", "poligono")
        .prefetch_related(
            Prefetch(
                "imagenes",
                queryset=InmuebleImagen.objects.order_by("-es_portada", "orden", "id"),
            )
        )
        .order_by("proyecto__nombre", "codigo")
    )


def _portada_url(inmueble: Inmueble) -> str:
    for img in inmueble.imagenes.all():
        url = img.url_visual
        if url:
            return url
    return ""


def _qr_png_bytes(data: str) -> bytes:
    """Genera un PNG nuevo cada vez (no es un QR estático del manual)."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#003366", back_color="white")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _absolute_catalog_url(request: HttpRequest, *, pk: int | None = None) -> str:
    if pk is not None:
        path = reverse("catalogo:detalle", kwargs={"pk": pk})
    else:
        path = reverse("catalogo:list")
    return request.build_absolute_uri(path)


def catalogo_list(request: HttpRequest) -> HttpResponse:
    """Listado público agrupado por proyecto."""
    inmuebles = list(_inmuebles_publicos_qs())
    for inm in inmuebles:
        inm.catalogo_portada = _portada_url(inm)
        inm.catalogo_n_fotos = sum(1 for img in inm.imagenes.all() if img.url_visual)

    proyectos = (
        Proyecto.objects.filter(
            activo=True,
            pk__in={inm.proyecto_id for inm in inmuebles},
        )
        .order_by("nombre")
    )

    por_proyecto: dict[int, list[Inmueble]] = {}
    for inm in inmuebles:
        por_proyecto.setdefault(inm.proyecto_id, []).append(inm)

    bloques = [
        {"proyecto": p, "inmuebles": por_proyecto.get(p.pk, [])}
        for p in proyectos
        if por_proyecto.get(p.pk)
    ]

    share_url = _absolute_catalog_url(request)
    qr_url = reverse("catalogo:qr") + "?" + urlencode({"v": request.GET.get("v") or "1"})

    return render(
        request,
        "catalogo/list.html",
        {
            "bloques": bloques,
            "total_inmuebles": len(inmuebles),
            "catalogo_share_url": share_url,
            "catalogo_qr_url": qr_url,
        },
    )


def catalogo_detalle(request: HttpRequest, pk: int) -> HttpResponse:
    """Galería pública de un inmueble disponible."""
    inmueble = get_object_or_404(_inmuebles_publicos_qs(), pk=pk)
    imagenes = [img for img in inmueble.imagenes.all() if img.url_visual]
    share_url = _absolute_catalog_url(request, pk=pk)
    qr_url = (
        reverse("catalogo:qr_detalle", kwargs={"pk": pk})
        + "?"
        + urlencode({"v": request.GET.get("v") or "1"})
    )
    return render(
        request,
        "catalogo/detalle.html",
        {
            "inmueble": inmueble,
            "imagenes": imagenes,
            "catalogo_share_url": share_url,
            "catalogo_qr_url": qr_url,
        },
    )


def catalogo_qr(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    """
    PNG del código QR para la URL pública actual.

    Se regenera en cada petición según el host real (local, dominio de producción, etc.),
    así el QR no queda fijo a localhost del manual PDF.
    """
    if pk is not None:
        get_object_or_404(_inmuebles_publicos_qs(), pk=pk)
        target = _absolute_catalog_url(request, pk=pk)
        filename = f"catalogo-inmueble-{pk}.png"
    else:
        target = _absolute_catalog_url(request)
        filename = "catalogo-paredes.png"

    if not target.startswith(("http://", "https://")):
        return HttpResponseBadRequest("URL no válida para QR.")

    png = _qr_png_bytes(target)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = "no-store, max-age=0"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["X-Catalogo-QR-URL"] = target
    return response
