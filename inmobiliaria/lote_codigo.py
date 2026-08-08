"""Código de lote con letra de polígono (A01, B01, …)."""

from __future__ import annotations

import re
from typing import Optional

# "POLIGONO A", "Polígono-B", "A"
_LETRA_FINAL = re.compile(r"(?:^|[\s\-_/])([A-Za-z])\s*$")
_CODIGO_CON_LETRA = re.compile(r"^([A-Za-z])\s*[-–.]?\s*0*(\d+)$")
_SOLO_DIGITOS = re.compile(r"^0*(\d+)$")


def letra_desde_nombre_poligono(nombre: str) -> str:
    """Extrae la letra del polígono: 'POLIGONO A' → 'A'."""
    nom = (nombre or "").strip()
    if not nom:
        return ""
    m = _LETRA_FINAL.search(nom)
    if m:
        return m.group(1).upper()
    letters = re.findall(r"[A-Za-z]", nom)
    return letters[-1].upper() if letters else ""


def normalizar_codigo_lote(codigo: str, letra_poligono: str = "") -> str:
    """
    Display estable tipo A01 / B12.
    - correlativo '1' + polígono A → A01
    - 'A01', 'A-01', 'a1' → A01
    - sin letra usable → correlativo con 2 dígitos o el texto original
    """
    raw = (codigo or "").strip()
    if not raw:
        return "—"
    m = _CODIGO_CON_LETRA.fullmatch(raw)
    if m:
        return f"{m.group(1).upper()}{int(m.group(2)):02d}"
    m2 = _SOLO_DIGITOS.fullmatch(raw)
    if m2:
        n = int(m2.group(1))
        letra = (letra_poligono or "").strip().upper()[:1]
        if letra.isalpha():
            return f"{letra}{n:02d}"
        return f"{n:02d}"
    return raw


def parse_codigo_lote_busqueda(texto: str) -> tuple[Optional[str], Optional[str]]:
    """'A01' → ('A', '1'); '01' → (None, '1'); otro → (None, None)."""
    raw = (texto or "").strip()
    if not raw:
        return None, None
    m = _CODIGO_CON_LETRA.fullmatch(raw)
    if m:
        return m.group(1).upper(), str(int(m.group(2)))
    m2 = _SOLO_DIGITOS.fullmatch(raw)
    if m2:
        return None, str(int(m2.group(1)))
    return None, None


def variantes_codigo_bd(num_lote: str) -> list[str]:
    """Posibles valores guardados en Inmueble.codigo para un texto de búsqueda."""
    raw = (num_lote or "").strip()
    if not raw:
        return []
    out: list[str] = [raw]
    letra, corr = parse_codigo_lote_busqueda(raw)
    if corr is not None:
        n = int(corr)
        out.extend([corr, str(n), f"{n:02d}", f"{n:03d}"])
        if letra:
            out.extend(
                [
                    f"{letra}{n}",
                    f"{letra}{n:02d}",
                    f"{letra}-{n}",
                    f"{letra}-{n:02d}",
                    f"{letra} {n}",
                ]
            )
    # únicos preservando orden
    seen: set[str] = set()
    uniq: list[str] = []
    for v in out:
        key = v.casefold()
        if key not in seen:
            seen.add(key)
            uniq.append(v)
    return uniq


def resolver_inmueble_por_codigo_lote(
    *,
    num_lote: str,
    proyecto_nombre: str = "",
    proyecto_id: int | None = None,
):
    """
    Localiza un Inmueble por código crudo ('1') o display ('A01').
    Prioriza coincidencia de proyecto y letra de polígono.
    """
    from django.db.models import Q

    from .models import Inmueble

    raw = (num_lote or "").strip()
    if not raw:
        return None

    letra, _corr = parse_codigo_lote_busqueda(raw)
    variants = variantes_codigo_bd(raw)
    q = Q()
    for v in variants:
        q |= Q(codigo__iexact=v)

    qs = Inmueble.objects.filter(q).select_related("proyecto", "poligono").order_by("id")
    if proyecto_id:
        qs = qs.filter(proyecto_id=proyecto_id)

    candidates = list(qs[:80])
    if not candidates:
        return None

    nom = (proyecto_nombre or "").strip().lower()
    if nom:
        by_proj = [
            c
            for c in candidates
            if c.proyecto_id and (c.proyecto.nombre or "").strip().lower() == nom
        ]
        if by_proj:
            candidates = by_proj

    if letra:
        by_letra = [
            c
            for c in candidates
            if (c.poligono_id and c.poligono.letra_codigo == letra)
            or normalizar_codigo_lote(
                c.codigo, c.poligono.letra_codigo if c.poligono_id else ""
            ).upper().startswith(letra)
        ]
        if by_letra:
            candidates = by_letra

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and letra:
        exact_disp = [
            c
            for c in candidates
            if normalizar_codigo_lote(
                c.codigo, c.poligono.letra_codigo if c.poligono_id else ""
            ).upper()
            == normalizar_codigo_lote(raw, letra).upper()
        ]
        if len(exact_disp) == 1:
            return exact_disp[0]
    return None
