"""Validar que el Nº de formato ingresado aparezca en el PDF del formato físico."""

from __future__ import annotations

import io
import re
from typing import BinaryIO


def _normalizar_texto_pdf(texto: str) -> str:
    # Quitar espacios raros entre dígitos (p. ej. "0 0 4 2" → "0042") no agresivo:
    # solo colapsar espacios múltiples y unificar.
    t = (texto or "").replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t


def extraer_texto_pdf(archivo) -> str:
    """Lee texto de un PDF (UploadedFile, FieldFile o bytes). Vacío si no hay capa de texto."""
    from pypdf import PdfReader

    if archivo is None:
        return ""
    data: bytes
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
    elif isinstance(archivo, (bytes, bytearray)):
        data = bytes(archivo)
    else:
        return ""

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


def variantes_numero_formulario(numero: int) -> list[str]:
    """Formas habituales del número en el impreso (1, 01, 001, 0001, …)."""
    n = int(numero)
    out: list[str] = [str(n)]
    for width in (2, 3, 4, 5, 6):
        padded = f"{n:0{width}d}"
        if padded not in out:
            out.append(padded)
    return out


def pdf_contiene_numero_formulario(archivo, numero: int) -> tuple[bool, str]:
    """
    True si el PDF incluye el número de formulario.
    Busca el número solo y junto a etiquetas No. / Nº / N° / formulario.
    """
    texto = extraer_texto_pdf(archivo)
    if not texto.strip():
        return (
            False,
            "El PDF no tiene texto legible (puede ser solo imagen escaneada). "
            "Use un PDF con el número visible como texto, o vuelva a generar/escanear con OCR.",
        )

    variantes = variantes_numero_formulario(numero)
    # Coincidencia con etiqueta típica del encabezado
    for v in variantes:
        patrones = [
            rf"(?i)\b(?:n[ºo°\.]*|no\.?|numero|número)\s*[:.]?\s*{re.escape(v)}\b",
            rf"(?i)\bformulario\s*[:.]?\s*{re.escape(v)}\b",
            rf"(?i)\baceptaci[oó]n\s*[:.]?\s*{re.escape(v)}\b",
        ]
        for pat in patrones:
            if re.search(pat, texto):
                return True, ""

    # Fallback: el número aparece como token aislado (evita coincidir 12 dentro de 1234)
    for v in variantes:
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", texto):
            return True, ""

    mostrado = f"{int(numero):04d}"
    return (
        False,
        f"El número ingresado ({mostrado}) no aparece en el PDF del formato físico. "
        "Revise el Nº del formulario o suba el PDF correcto.",
    )


def archivo_es_pdf(nombre: str | None, content_type: str | None = None) -> bool:
    name = (nombre or "").lower()
    if name.endswith(".pdf"):
        return True
    ct = (content_type or "").lower()
    return "pdf" in ct
