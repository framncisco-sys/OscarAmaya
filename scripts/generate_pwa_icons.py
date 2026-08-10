"""Genera iconos PWA/iOS desde los PNG maestros en static/icons/."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "static" / "icons"

ANY_SRC = ICONS / "pwa-512.png"
MASK_SRC = ICONS / "pwa-512-maskable.png"

PWA_ANY = (48, 72, 96, 144, 192, 384, 512)
PWA_MASK = (192, 512)
APPLE = (120, 152, 167, 180)


def _resize(src: Path, dest: Path, size: int) -> None:
    img = Image.open(src).convert("RGB")
    out = img.resize((size, size), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, format="PNG", optimize=True)
    print(f"  {dest.name} ({size}x{size})")


def main() -> int:
    if not ANY_SRC.is_file():
        print("Falta:", ANY_SRC, file=sys.stderr)
        return 1
    if not MASK_SRC.is_file():
        print("Falta:", MASK_SRC, file=sys.stderr)
        return 1

    print("PWA any <-", ANY_SRC.name)
    for sz in PWA_ANY:
        _resize(ANY_SRC, ICONS / f"pwa-{sz}.png", sz)

    print("PWA maskable <-", MASK_SRC.name)
    for sz in PWA_MASK:
        name = f"pwa-{sz}-maskable.png" if sz != 512 else "pwa-512-maskable.png"
        _resize(MASK_SRC, ICONS / name, sz)

    print("Apple touch <-", ANY_SRC.name)
    for sz in APPLE:
        name = "apple-touch-icon.png" if sz == 180 else f"apple-touch-icon-{sz}.png"
        _resize(ANY_SRC, ICONS / name, sz)

    print("OK - iconos en", ICONS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
