"""Iconos PWA / pantalla de inicio — versión única para cache-bust en todo el sitio."""

from __future__ import annotations

# Versión global de caché (CSS, JS, SW, iconos). Subir tras cada despliegue importante.
PBR_CACHE_VERSION = "46"

# Alias usado por iconos PWA
PBR_ICON_VERSION = PBR_CACHE_VERSION

# Android / manifest (purpose=any)
PBR_PWA_SIZES_ANY = (48, 72, 96, 144, 192, 384, 512)

# Android adaptive / maskable
PBR_PWA_SIZES_MASKABLE = (192, 512)

# iOS «Añadir a pantalla de inicio»
PBR_APPLE_TOUCH_SIZES = (120, 152, 167, 180)


def pwa_icon_url(size: int, *, maskable: bool = False) -> str:
    v = PBR_ICON_VERSION
    if maskable:
        return f"/static/icons/pwa-{size}-maskable.png?v={v}"
    return f"/static/icons/pwa-{size}.png?v={v}"


def apple_touch_icon_url(size: int) -> str:
    v = PBR_ICON_VERSION
    if size == 180:
        return f"/static/icons/apple-touch-icon.png?v={v}"
    return f"/static/icons/apple-touch-icon-{size}.png?v={v}"


def manifest_icons() -> list[dict[str, str]]:
    icons: list[dict[str, str]] = []
    for sz in PBR_PWA_SIZES_ANY:
        icons.append(
            {
                "src": pwa_icon_url(sz),
                "sizes": f"{sz}x{sz}",
                "type": "image/png",
                "purpose": "any",
            }
        )
    for sz in PBR_PWA_SIZES_MASKABLE:
        icons.append(
            {
                "src": pwa_icon_url(sz, maskable=True),
                "sizes": f"{sz}x{sz}",
                "type": "image/png",
                "purpose": "maskable",
            }
        )
    return icons
