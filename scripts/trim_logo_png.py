"""Recorta márgenes casi blancos alrededor del logo (mejor uso del espacio en cabecera/PDF)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def _content_bbox_rgba(img: Image.Image, white: int = 248, alpha_floor: int = 28) -> tuple[int, int, int, int] | None:
    w, h = img.size
    raw = img.tobytes()
    left, top, right, bottom = w, h, -1, -1
    for y in range(h):
        row = y * w * 4
        for x in range(w):
            i = row + x * 4
            r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
            if a < alpha_floor:
                continue
            if r > white and g > white and b > white:
                continue
            if left > x:
                left = x
            if right < x:
                right = x
            if top > y:
                top = y
            if bottom < y:
                bottom = y
    if right < 0:
        return None
    return (left, top, right + 1, bottom + 1)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    path = root / "static" / "logo_paredes_desarrollos.png"
    if not path.is_file():
        print("No existe:", path, file=sys.stderr)
        return 1
    img = Image.open(path).convert("RGBA")
    bbox = _content_bbox_rgba(img)
    if not bbox:
        print("Sin bbox, sin cambios")
        return 0
    pad = 10
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(img.width, bbox[2] + pad)
    bottom = min(img.height, bbox[3] + pad)
    out = img.crop((left, top, right, bottom))
    out.save(path, optimize=True)
    print(f"{img.size} -> {out.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
