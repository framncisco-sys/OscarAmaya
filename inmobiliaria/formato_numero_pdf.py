"""Validar que el Nº de formato ingresado aparezca en el PDF del formato físico."""

from __future__ import annotations

import base64
import io
import re
from typing import BinaryIO

TOKEN_QR_PREFIX = "PBR-FA-"


def _normalizar_texto_pdf(texto: str) -> str:
    t = (texto or "").replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t


def token_qr_formato(numero: int) -> str:
    """Payload del QR impreso en el formato (legible también como texto)."""
    return f"{TOKEN_QR_PREFIX}{int(numero):04d}"


def numero_desde_token_qr(texto: str | None) -> int | None:
    """Extrae el Nº de formulario de un token QR o texto similar."""
    raw = (texto or "").strip()
    if not raw:
        return None
    m = re.search(rf"(?i){re.escape(TOKEN_QR_PREFIX)}(\d{{1,6}})", raw)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def qr_png_data_uri_formato(numero: int) -> str:
    """PNG en data URI para incrustar el QR en el PDF del sistema."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=6,
        border=1,
    )
    qr.add_data(token_qr_formato(numero))
    qr.make(fit=True)
    img = qr.make_image(fill_color="#003366", back_color="white")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _leer_bytes_archivo(archivo) -> bytes:
    if archivo is None:
        return b""
    if hasattr(archivo, "read"):
        pos = None
        if hasattr(archivo, "tell") and hasattr(archivo, "seek"):
            try:
                pos = archivo.tell()
            except Exception:
                pos = None
        try:
            data = archivo.read()
        finally:
            if pos is not None:
                try:
                    archivo.seek(pos)
                except Exception:
                    pass
            elif hasattr(archivo, "seek"):
                try:
                    archivo.seek(0)
                except Exception:
                    pass
        return data or b""
    if isinstance(archivo, (bytes, bytearray)):
        return bytes(archivo)
    return b""


def extraer_texto_pdf(archivo) -> str:
    """Lee texto de un PDF (UploadedFile, FieldFile o bytes). Vacío si no hay capa de texto."""
    from pypdf import PdfReader

    data = _leer_bytes_archivo(archivo)
    if not data:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""
    partes: list[str] = []
    for page in reader.pages:
        try:
            partes.append(page.extract_text() or "")
        except Exception:
            continue
    return _normalizar_texto_pdf("\n".join(partes))


def _objeto_pdf(obj):
    if obj is None:
        return None
    if hasattr(obj, "get_object"):
        try:
            return obj.get_object()
        except Exception:
            return obj
    return obj


def iter_imagenes_embebidas_pdf(data: bytes, *, max_paginas: int = 2):
    """Genera bytes de imágenes embebidas (escaneos suelen ser JPEG en la 1.ª página)."""
    from pypdf import PdfReader

    if not data:
        return
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return
    for page in reader.pages[:max_paginas]:
        resources = _objeto_pdf(page.get("/Resources"))
        if not resources:
            continue
        xobjects = _objeto_pdf(resources.get("/XObject"))
        if not xobjects:
            continue
        for _name, ref in xobjects.items():
            obj = _objeto_pdf(ref)
            if not obj or obj.get("/Subtype") != "/Image":
                continue
            try:
                yield obj.get_data()
            except Exception:
                continue


def _numero_desde_qr_imagen(img_bytes: bytes) -> int | None:
    if not img_bytes:
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        try:
            from PIL import Image

            pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    det = cv2.QRCodeDetector()
    try:
        data, _, _ = det.detectAndDecode(img)
    except Exception:
        return None
    if not data:
        return None
    return numero_desde_token_qr(data)


def numero_desde_qr_en_pdf(archivo, *, max_paginas: int = 2) -> int | None:
    """Intenta leer el QR del formato en las primeras páginas del PDF escaneado."""
    data = _leer_bytes_archivo(archivo)
    if not data:
        return None
    for chunk in iter_imagenes_embebidas_pdf(data, max_paginas=max_paginas):
        n = _numero_desde_qr_imagen(chunk)
        if n is not None:
            return n
    return None


def variantes_numero_formulario(numero: int) -> list[str]:
    """Formas habituales del número en el impreso (1, 01, 001, 0001, …)."""
    n = int(numero)
    out: list[str] = [str(n)]
    for width in (2, 3, 4, 5, 6):
        padded = f"{n:0{width}d}"
        if padded not in out:
            out.append(padded)
    return out


def numero_en_nombre_archivo(nombre: str | None, numero: int) -> bool:
    """
    True si el nombre del archivo incluye el Nº del formulario.
    Ej.: «Formato de aceptación 18.pdf», «formato_aceptacion_0018.pdf».
    """
    base = (nombre or "").strip()
    if not base:
        return False
    base = re.sub(r"\.[^.]+$", "", base, flags=re.IGNORECASE)
    base_norm = re.sub(r"[_\-]+", " ", base.lower())
    compact = re.sub(r"\s+", "", base_norm)
    for v in variantes_numero_formulario(numero):
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", base_norm):
            return True
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", compact):
            return True
    return False


def _nombre_archivo(archivo, nombre_archivo: str | None) -> str | None:
    if nombre_archivo:
        return nombre_archivo
    if archivo is not None and hasattr(archivo, "name"):
        return getattr(archivo, "name", None)
    return None


def _texto_contiene_numero(texto: str, numero: int) -> bool:
    if not texto.strip():
        return False
    variantes = variantes_numero_formulario(numero)
    for v in variantes:
        patrones = [
            rf"(?i)\b(?:n[ºo°\.]*|no\.?|numero|número)\s*[:.]?\s*{re.escape(v)}\b",
            rf"(?i)\bformulario\s*[:.]?\s*{re.escape(v)}\b",
            rf"(?i)\baceptaci[oó]n\s*[:.]?\s*{re.escape(v)}\b",
        ]
        for pat in patrones:
            if re.search(pat, texto):
                return True
    for v in variantes:
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", texto):
            return True
    return False


def pdf_contiene_numero_formulario(
    archivo,
    numero: int,
    *,
    nombre_archivo: str | None = None,
) -> tuple[bool, str]:
    """
    True si el PDF corresponde al número de formulario.

    Orden de verificación:
    1. Texto dentro del PDF (PDF digital u OCR).
    2. Código QR impreso en el formato (escaneo sin OCR).
    3. Nombre del archivo (p. ej. «Formato de aceptación 18.pdf»).
    """
    nombre = _nombre_archivo(archivo, nombre_archivo)
    num = int(numero)
    mostrado = f"{num:04d}"

    texto = extraer_texto_pdf(archivo)
    qr_num = numero_desde_qr_en_pdf(archivo)
    nombre_ok = numero_en_nombre_archivo(nombre, num)

    if texto.strip() and _texto_contiene_numero(texto, num):
        return True, ""

    if qr_num is not None:
        if qr_num == num:
            return True, ""
        return (
            False,
            f"El código QR del PDF corresponde al formato #{qr_num:04d}, "
            f"pero ingresó el Nº {mostrado}. Revise el número o suba el archivo correcto.",
        )

    if nombre_ok:
        return True, ""

    if not texto.strip():
        return (
            False,
            "El PDF parece un escaneo sin texto legible. "
            f"Renombre el archivo con el número (ej. «Formato de aceptación {num}.pdf») "
            "o suba un escaneo donde se vea el código QR junto al Nº del formato. "
            "No hace falta OCR si el QR o el nombre del archivo coinciden.",
        )

    return (
        False,
        f"El número ingresado ({mostrado}) no coincide con el PDF. "
        f"Renombre el archivo (ej. «Formato de aceptación {num}.pdf») "
        "o verifique que el escaneo muestre el Nº o el código QR del encabezado.",
    )


def archivo_es_pdf(nombre: str | None, content_type: str | None = None) -> bool:
    name = (nombre or "").lower()
    if name.endswith(".pdf"):
        return True
    ct = (content_type or "").lower()
    return "pdf" in ct
