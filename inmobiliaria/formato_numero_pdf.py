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


def _nombre_archivo(archivo) -> str:
    if archivo is None:
        return ""
    return (getattr(archivo, "name", None) or "").strip()


def extraer_numero_desde_nombre_archivo(nombre: str) -> int | None:
    """
    Extrae el Nº de formulario del nombre del archivo (p. ej. «FORMATO DE ACEPTACION 18.pdf»).
    Útil cuando el PDF es escaneo sin capa de texto.
    """
    base = (nombre or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    base = base.strip()
    if not base:
        return None

    patrones = [
        r"(?i)formato(?:\s|[_-])*de(?:\s|[_-])*aceptaci[oó]n(?:\s|[_-])*(\d+)",
        r"(?i)formato(?:\s|[_-])*aceptaci[oó]n(?:\s|[_-])*(\d+)",
        r"(?i)formulario(?:\s|[_-])*(\d+)",
    ]
    for pat in patrones:
        m = re.search(pat, base)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue

    # Número al final del nombre: «… 0018»
    m = re.search(r"(?<!\d)(\d{1,6})(?!\d)\s*$", base)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def pdf_contiene_numero_formulario(archivo, numero: int) -> tuple[bool, str]:
    """
    True si el PDF incluye el número de formulario.
    Busca en el texto del PDF; si es escaneo sin texto, acepta el mismo Nº en el nombre del archivo.
    """
    texto = extraer_texto_pdf(archivo)
    n = int(numero)
    nombre = _nombre_archivo(archivo)

    if not texto.strip():
        num_nombre = extraer_numero_desde_nombre_archivo(nombre)
        if num_nombre is not None and num_nombre == n:
            return True, ""
        mostrado = f"{n:04d}"
        if num_nombre is not None and num_nombre != n:
            return (
                False,
                f"El PDF es escaneo sin texto legible. En el nombre del archivo aparece el Nº "
                f"{num_nombre:04d}, pero usted ingresó {mostrado}. Corrija el número o renombre el PDF.",
            )
        return (
            False,
            "El PDF no tiene texto legible (escaneo sin OCR). "
            "Renombre el archivo incluyendo el mismo Nº del formulario, por ejemplo "
            f"«FORMATO DE ACEPTACION {mostrado}.pdf», o use un PDF con texto seleccionable.",
        )

    variantes = variantes_numero_formulario(n)
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

    mostrado = f"{n:04d}"
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
