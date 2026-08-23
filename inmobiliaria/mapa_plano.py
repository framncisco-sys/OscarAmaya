"""Rasterización de planos y auto-delineación de lotes sobre imagen/PDF."""

from __future__ import annotations

import io
import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from PIL import Image

from inmobiliaria.lote_codigo import (
    codigos_lote_equivalentes,
    letra_desde_nombre_poligono,
    normalizar_codigo_lote,
    parse_codigo_lote_busqueda,
)

logger = logging.getLogger(__name__)

_LOTE_TEXTO = re.compile(r"^[A-Za-z]?\s*[-–.]?\s*0*\d{1,4}$")


def _cv2_np():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV no está instalado (opencv-python-headless). "
            "Instálelo para usar la delimitación automática del mapa."
        ) from exc
    return cv2, np


@dataclass
class TextHit:
    text: str
    x: float
    y: float
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class RegionHit:
    idx: int
    centroid: tuple[float, float]
    area: float
    bbox: tuple[float, float, float, float]
    contour: Any


def _leer_bytes_archivo(field) -> tuple[str, bytes] | tuple[None, None]:
    if not field or not field.name:
        return None, None
    try:
        with field.open("rb") as fh:
            return field.name, fh.read()
    except Exception:
        logger.exception("No se pudo leer archivo de plano: %s", field.name)
        return field.name, None


def _escala_imagen(img, max_px: int):
    cv2, _np = _cv2_np()
    h, w = img.shape[:2]
    lado = max(h, w)
    if lado <= max_px:
        return img, 1.0
    scale = max_px / lado
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    return resized, scale


def _pdf_a_bgr(data: bytes, *, max_px: int = 4096):
    cv2, np = _cv2_np()
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF (fitz) no instalado; no se puede rasterizar PDF.")
        return None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count < 1:
            return None
        page = doc[0]
        zoom = 2.0
        while True:
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = arr.copy()
            else:
                img = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            if max(img.shape[0], img.shape[1]) >= min(max_px, 800) or zoom >= 4.0:
                break
            zoom += 0.5
        doc.close()
        img, _ = _escala_imagen(img, max_px)
        return img
    except Exception:
        logger.exception("Error rasterizando PDF de plano")
        return None


def _imagen_a_bgr(data: bytes, *, max_px: int = 4096):
    cv2, np = _cv2_np()
    try:
        pil = Image.open(io.BytesIO(data))
        pil = pil.convert("RGB")
        arr = np.array(pil)
        img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        img, _ = _escala_imagen(img, max_px)
        return img
    except Exception:
        logger.exception("Error leyendo imagen de plano")
        return None


def rasterizar_plano(proyecto, *, max_px: int = 4096) -> tuple[np.ndarray | None, int, int]:
    """Devuelve imagen BGR y dimensiones (ancho, alto) en píxeles."""
    field = proyecto.plano_maestro
    nombre, data = _leer_bytes_archivo(field)
    if not data:
        return None, 0, 0
    name = (nombre or "").lower()
    img: np.ndarray | None
    if name.endswith(".pdf"):
        img = _pdf_a_bgr(data, max_px=max_px)
    else:
        img = _imagen_a_bgr(data, max_px=max_px)
    if img is None:
        return None, 0, 0
    h, w = img.shape[:2]
    return img, w, h


def plano_imagen_png_bytes(proyecto, *, max_px: int = 4096) -> tuple[bytes | None, int, int]:
    cv2, _np = _cv2_np()
    img, w, h = rasterizar_plano(proyecto, max_px=max_px)
    if img is None:
        return None, 0, 0
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return None, w, h
    return buf.tobytes(), w, h


def _textos_desde_pdf(data: bytes, img_w: int, img_h: int) -> list[TextHit]:
    try:
        import fitz
    except ImportError:
        return []
    out: list[TextHit] = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count < 1:
            return []
        page = doc[0]
        pr = page.rect
        sx = img_w / pr.width if pr.width else 1.0
        sy = img_h / pr.height if pr.height else 1.0
        for w in page.get_text("words"):
            if len(w) < 5:
                continue
            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
            t = (txt or "").strip()
            if not t or not _LOTE_TEXTO.fullmatch(t.replace(" ", "")):
                if not re.fullmatch(r"\d{1,4}", t):
                    continue
            cx = (x0 + x1) / 2 * sx
            cy = (y0 + y1) / 2 * sy
            out.append(
                TextHit(
                    text=t,
                    x=cx,
                    y=cy,
                    x0=x0 * sx,
                    y0=y0 * sy,
                    x1=x1 * sx,
                    y1=y1 * sy,
                )
            )
        doc.close()
    except Exception:
        logger.exception("Error extrayendo textos del PDF")
    return out


def _textos_desde_ocr(img) -> list[TextHit]:
    cv2, _np = _cv2_np()
    try:
        import pytesseract
    except ImportError:
        return []
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT, config="--psm 11")
        out: list[TextHit] = []
        n = len(data.get("text", []))
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            if not txt:
                continue
            conf = int(float(data["conf"][i])) if data["conf"][i] not in ("", "-1") else -1
            if conf >= 0 and conf < 40:
                continue
            if not (re.fullmatch(r"\d{1,4}", txt) or _LOTE_TEXTO.fullmatch(txt.replace(" ", ""))):
                continue
            x = float(data["left"][i])
            y = float(data["top"][i])
            w = float(data["width"][i])
            h = float(data["height"][i])
            out.append(
                TextHit(
                    text=txt,
                    x=x + w / 2,
                    y=y + h / 2,
                    x0=x,
                    y0=y,
                    x1=x + w,
                    y1=y + h,
                )
            )
        return out
    except Exception:
        logger.exception("OCR no disponible para plano")
        return []


def extraer_textos_plano(
    img: np.ndarray,
    archivo_nombre: str | None,
    archivo_bytes: bytes | None,
) -> list[TextHit]:
    hits: list[TextHit] = []
    if archivo_bytes and (archivo_nombre or "").lower().endswith(".pdf"):
        hits.extend(_textos_desde_pdf(archivo_bytes, img.shape[1], img.shape[0]))
    if not hits:
        hits.extend(_textos_desde_ocr(img))
    return hits


def detectar_regiones_lote(img) -> list[RegionHit]:
    cv2, np = _cv2_np()
    """Regiones cerradas (interiores de lotes) en el plano."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Líneas oscuras → blanco; interior claro → negro (para contornos de huecos)
    inv = 255 - binary
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hier = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    img_area = float(w * h)
    min_area = img_area * 0.00008
    max_area = img_area * 0.08
    regiones: list[RegionHit] = []
    idx = 0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_area or area > max_area:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 8 or bh < 8:
            continue
        aspect = bw / bh if bh else 0
        if aspect > 12 or aspect < 0.06:
            continue
        M = cv2.moments(cnt)
        if not M["m00"]:
            continue
        cx = float(M["m10"] / M["m00"])
        cy = float(M["m01"] / M["m00"])
        regiones.append(
            RegionHit(
                idx=idx,
                centroid=(cx, cy),
                area=area,
                bbox=(float(x), float(y), float(x + bw), float(y + bh)),
                contour=cnt,
            )
        )
        idx += 1
    regiones.sort(key=lambda r: (-r.area, r.centroid[1], r.centroid[0]))
    return regiones


def _contour_a_geojson(contour, w: int, h: int, *, simplify: float = 0.01) -> dict | None:
    cv2, _np = _cv2_np()
    if contour is None or w <= 0 or h <= 0:
        return None
    peri = cv2.arcLength(contour, True)
    eps = max(1.0, simplify * peri)
    approx = cv2.approxPolyDP(contour, eps, True)
    if len(approx) < 3:
        return None
    ring: list[list[float]] = []
    for pt in approx.reshape(-1, 2):
        x_pct = round(float(pt[0]) / w * 100, 4)
        y_pct = round(float(pt[1]) / h * 100, 4)
        x_pct = max(0.0, min(100.0, x_pct))
        y_pct = max(0.0, min(100.0, y_pct))
        ring.append([x_pct, y_pct])
    if ring[0] != ring[-1]:
        ring.append(ring[0][:])
    if len(ring) < 4:
        return None
    return {"type": "Polygon", "coordinates": [ring]}


def poligono_desde_region(region: RegionHit, w: int, h: int) -> dict | None:
    return _contour_a_geojson(region.contour, w, h)


def poligono_desde_semilla(img, sx: float, sy: float) -> dict | None:
    cv2, np = _cv2_np()
    """Flood-fill desde el centro del número del lote hasta las líneas del plano."""
    h, w = img.shape[:2]
    ix = int(max(0, min(w - 1, round(sx))))
    iy = int(max(0, min(h - 1, round(sy))))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Interior del lote suele ser claro
    if binary[iy, ix] < 128:
        binary = 255 - binary
    work = binary.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    try:
        cv2.floodFill(
            work,
            mask,
            (ix, iy),
            128,
            loDiff=(18, 18, 18),
            upDiff=(18, 18, 18),
            flags=flags,
        )
    except Exception:
        return None
    region = mask[1:-1, 1:-1]
    if not np.any(region):
        return None
    contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    if area < (w * h * 0.00005):
        return None
    return _contour_a_geojson(cnt, w, h, simplify=0.012)


def _variantes_texto_lote(lote) -> set[str]:
    letra = lote.poligono.letra_codigo if lote.poligono_id else ""
    cod = (lote.codigo or "").strip()
    disp = (lote.codigo_display or "").strip()
    variants: set[str] = set()
    for v in (cod, disp, normalizar_codigo_lote(cod, letra)):
        if v and v != "—":
            variants.add(re.sub(r"\s+", "", v.upper()))
    _, corr = parse_codigo_lote_busqueda(cod or disp)
    if corr:
        n = int(corr)
        variants.add(str(n))
        variants.add(f"{n:02d}")
        if letra:
            variants.add(f"{letra.upper()}{n}")
            variants.add(f"{letra.upper()}{n:02d}")
    return variants


def _texto_coincide_lote(texto: str, lote) -> bool:
    raw = (texto or "").strip()
    if not raw:
        return False
    compact = re.sub(r"\s+", "", raw.upper())
    if compact in _variantes_texto_lote(lote):
        return True
    letra = lote.poligono.letra_codigo if lote.poligono_id else ""
    return codigos_lote_equivalentes(raw, lote.codigo, letra)


def _punto_en_recorte_poligono(x_pct: float, y_pct: float, poligono) -> bool:
    if not poligono:
        return True
    if poligono.recorte_ancho_pct is None or poligono.recorte_alto_pct is None:
        return True
    L = float(poligono.recorte_izq_pct or 0)
    T = float(poligono.recorte_sup_pct or 0)
    W = float(poligono.recorte_ancho_pct)
    H = float(poligono.recorte_alto_pct)
    return L <= x_pct <= L + W and T <= y_pct <= T + H


def _grid_geometrias_poligono(poligono, lotes) -> dict[int, dict]:
    """Fallback: cuadrícula dentro del recorte del polígono."""
    if not lotes:
        return {}
    L = float(poligono.recorte_izq_pct if poligono and poligono.recorte_izq_pct is not None else 3)
    T = float(poligono.recorte_sup_pct if poligono and poligono.recorte_sup_pct is not None else 3)
    W = float(
        poligono.recorte_ancho_pct
        if poligono and poligono.recorte_ancho_pct is not None
        else 94
    )
    H = float(
        poligono.recorte_alto_pct
        if poligono and poligono.recorte_alto_pct is not None
        else 94
    )
    n = len(lotes)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = int(math.ceil(n / cols))
    cell_w = W / cols
    cell_h = H / rows
    pad = 0.08
    out: dict[int, dict] = {}
    ordenados = sorted(lotes, key=lambda l: (l.codigo or ""))
    for i, lote in enumerate(ordenados):
        row = i // cols
        col = i % cols
        x0 = L + col * cell_w + cell_w * pad * 0.5
        y0 = T + row * cell_h + cell_h * pad * 0.5
        x1 = x0 + cell_w * (1 - pad)
        y1 = y0 + cell_h * (1 - pad)
        out[lote.pk] = {
            "type": "Polygon",
            "coordinates": [
                [
                    [round(x0, 4), round(y0, 4)],
                    [round(x1, 4), round(y0, 4)],
                    [round(x1, 4), round(y1, 4)],
                    [round(x0, 4), round(y1, 4)],
                    [round(x0, 4), round(y0, 4)],
                ]
            ],
        }
    return out


def _emparejar_por_regiones(
    img,
    w: int,
    h: int,
    lotes: list,
    regiones: list[RegionHit],
    poligono,
) -> dict[int, dict]:
    """Asigna regiones a lotes por orden espacial dentro del recorte."""
    if not lotes or not regiones:
        return {}
    candidatas: list[RegionHit] = []
    for reg in regiones:
        cx_pct = reg.centroid[0] / w * 100
        cy_pct = reg.centroid[1] / h * 100
        if _punto_en_recorte_poligono(cx_pct, cy_pct, poligono):
            candidatas.append(reg)
    if len(candidatas) < len(lotes):
        candidatas = list(regiones)
    candidatas.sort(key=lambda r: (r.centroid[1], r.centroid[0]))
    lotes_ord = sorted(lotes, key=lambda l: (l.codigo or ""))
    out: dict[int, dict] = {}
    for reg, lote in zip(candidatas, lotes_ord):
        geom = poligono_desde_region(reg, w, h)
        if geom:
            out[lote.pk] = geom
    return out


def auto_geometrias_plano(
    proyecto,
    lotes,
    *,
    poligono_id: int | None = None,
    sobrescribir: bool = False,
) -> dict[str, Any]:
    """
    Detecta polígonos sobre el plano maestro y devuelve GeoJSON por inmueble_id.
    Estrategia: textos del PDF/OCR + flood-fill; fallback por regiones o cuadrícula.
    """
    try:
        img, w, h = rasterizar_plano(proyecto)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    if img is None or w <= 0 or h <= 0:
        return {"ok": False, "error": "No hay plano maestro o no se pudo convertir a imagen."}

    nombre, archivo_bytes = _leer_bytes_archivo(proyecto.plano_maestro)
    textos = extraer_textos_plano(img, nombre, archivo_bytes)
    regiones = detectar_regiones_lote(img)

    lotes_work = [
        l
        for l in lotes
        if (sobrescribir or not l.geometria_json)
    ]
    if poligono_id:
        lotes_work = [l for l in lotes_work if l.poligono_id == poligono_id]

    if not lotes_work:
        return {
            "ok": True,
            "asignados": 0,
            "total_lotes": 0,
            "geometrias": {},
            "metodo": "ninguno",
            "textos_detectados": len(textos),
            "regiones_detectadas": len(regiones),
        }

    geometrias: dict[int, dict] = {}
    usados_textos: set[int] = set()

    # 1) Emparejar por número/letra visible en el plano
    for lote in lotes_work:
        for i, th in enumerate(textos):
            if i in usados_textos:
                continue
            if not _texto_coincide_lote(th.text, lote):
                continue
            x_pct = th.x / w * 100
            y_pct = th.y / h * 100
            if not _punto_en_recorte_poligono(x_pct, y_pct, lote.poligono):
                continue
            geom = poligono_desde_semilla(img, th.x, th.y)
            if not geom:
                # Buscar región que contenga el texto
                for reg in regiones:
                    x0, y0, x1, y1 = reg.bbox
                    if x0 <= th.x <= x1 and y0 <= th.y <= y1:
                        geom = poligono_desde_region(reg, w, h)
                        break
            if geom:
                geometrias[lote.pk] = geom
                usados_textos.add(i)
            break

    metodo = "texto" if geometrias else ""

    # 2) Fallback por polígono lógico: regiones detectadas
    restantes = [l for l in lotes_work if l.pk not in geometrias]
    if restantes:
        from collections import defaultdict

        por_pol: dict[int | None, list] = defaultdict(list)
        for l in restantes:
            por_pol[l.poligono_id].append(l)
        region_asig = 0
        for _pol_id, grupo in por_pol.items():
            pol = grupo[0].poligono if grupo else None
            asig = _emparejar_por_regiones(img, w, h, grupo, regiones, pol)
            geometrias.update(asig)
            region_asig += len(asig)
        if region_asig:
            metodo = metodo or "regiones"

    # 3) Último recurso: cuadrícula en recorte del polígono
    restantes = [l for l in lotes_work if l.pk not in geometrias]
    if restantes:
        from collections import defaultdict

        por_pol = defaultdict(list)
        for l in restantes:
            por_pol[l.poligono_id].append(l)
        for _pol_id, grupo in por_pol.items():
            pol = grupo[0].poligono if grupo else None
            geometrias.update(_grid_geometrias_poligono(pol, grupo))
        metodo = metodo or "grid"

    return {
        "ok": True,
        "asignados": len(geometrias),
        "total_lotes": len(lotes_work),
        "geometrias": geometrias,
        "metodo": metodo or "grid",
        "textos_detectados": len(textos),
        "regiones_detectadas": len(regiones),
        "imagen_ancho": w,
        "imagen_alto": h,
    }
