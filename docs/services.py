from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from inmobiliaria.models import Contrato, Inmueble

from .models import CorrelativoDocumento, DocumentoEmitido, DocumentoTipo
from .recibo_notificacion import ReciboNotificacionInfo
from .recibo_text import format_monto_sv, monto_usd_letras_es

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorrelativoConfig:
    usar_mes: bool = True
    prefijo: str = "PBR"


def _next_correlativo(*, tipo: str, cfg: CorrelativoConfig) -> str:
    hoy = timezone.localdate()
    anio = hoy.year
    mes = hoy.month if cfg.usar_mes else None

    # No usar select_for_update().get_or_create(): en Django 6 get_or_create hace get()
    # antes de atomic(), y SELECT ... FOR UPDATE exige transacción abierta.
    with transaction.atomic():
        while True:
            obj = (
                CorrelativoDocumento.objects.select_for_update()
                .filter(tipo=tipo, anio=anio, mes=mes)
                .first()
            )
            if obj is not None:
                obj.ultimo_numero += 1
                obj.save(update_fields=["ultimo_numero", "actualizado_en"])
                nro = obj.ultimo_numero
                break
            try:
                obj = CorrelativoDocumento.objects.create(
                    tipo=tipo,
                    anio=anio,
                    mes=mes,
                    ultimo_numero=0,
                )
            except IntegrityError:
                continue
            obj.ultimo_numero += 1
            obj.save(update_fields=["ultimo_numero", "actualizado_en"])
            nro = obj.ultimo_numero
            break

    if cfg.usar_mes:
        return f"{cfg.prefijo}-{tipo}-{anio}{mes:02d}-{nro:05d}"
    return f"{cfg.prefijo}-{tipo}-{anio}-{nro:05d}"


def _lugar_emision_republica(proyecto) -> str:
    """Lugar tipo acto jurídico para documentos PDF (promesa, recibo)."""
    mun = (getattr(proyecto, "municipio", None) or "").strip()
    dep = (getattr(proyecto, "departamento", None) or "").strip()
    if mun and dep:
        return f"{mun}, departamento de {dep}, República de El Salvador"
    if mun:
        return f"{mun}, República de El Salvador"
    return "San Salvador, República de El Salvador"


def _razon_social_negocio_pdf() -> str:
    return getattr(
        settings,
        "PBR_PROMESA_RAZON_SOCIAL_VENDEDOR",
        "PAREDES BIENES RAÍCES",
    )


def _marca_slug_para_pdf(
    *,
    user=None,
    marca_slug: str | None = None,
    default_slug: str | None = None,
) -> str:
    """
    Empresa/marca del PDF: sesión o perfil del usuario.
    Comisión de venta → Desarrollos; alquiler → Bienes Raíces (default_slug).
    """
    from core.marcas import (
        MARCAS,
        SLUG_BIENES_RAICES,
        SLUG_DESARROLLOS,
        get_marca,
    )
    from usuarios.models import PerfilUsuario

    if marca_slug and get_marca(marca_slug):
        return marca_slug
    if user is not None:
        perfil = getattr(user, "perfil_app", None)
        if perfil is None:
            try:
                perfil = PerfilUsuario.objects.filter(user_id=user.pk).first()
            except Exception:
                perfil = None
        if perfil is not None:
            emp = (perfil.empresa or "").strip()
            if emp in MARCAS:
                return emp
    if default_slug and default_slug in MARCAS:
        return default_slug
    return SLUG_DESARROLLOS if default_slug != SLUG_BIENES_RAICES else SLUG_BIENES_RAICES


def _branding_empresa_pdf(
    *,
    user=None,
    marca_slug: str | None = None,
    default_slug: str | None = None,
) -> tuple[str, str]:
    """(archivo logo estático, nombre comercial) según empresa."""
    from core.marcas import MARCAS, SLUG_DESARROLLOS

    slug = _marca_slug_para_pdf(
        user=user, marca_slug=marca_slug, default_slug=default_slug
    )
    marca = MARCAS.get(slug) or MARCAS[SLUG_DESARROLLOS]
    return str(marca["logo"]), str(marca["nombre"])


def _pdf_static_base_url() -> str:
    """Directorio de estáticos donde están los logos (cualquiera sirve como ancla)."""
    for fname in (
        "logo_paredes_bienes_raices.png",
        "logo_paredes_desarrollos.png",
        "logo_paredes_desarrollos_pie.png",
        "logo_valle_alegre.png",
    ):
        found = finders.find(fname)
        if found:
            return Path(found).parent.as_uri() + "/"
    return Path(settings.BASE_DIR).as_uri() + "/"


def _proyecto_logo_path(proyecto) -> Path | None:
    """Ruta de archivo del logo del proyecto, o del fallback Valle Alegre."""
    if proyecto is not None:
        logo = getattr(proyecto, "logo", None)
        if logo and getattr(logo, "name", None):
            try:
                path = Path(logo.path)
                if path.is_file():
                    return path
            except (ValueError, OSError):
                pass
    found = finders.find("logo_valle_alegre.png")
    return Path(found) if found else None


def _proyecto_logo_src_para_pdf(proyecto) -> str:
    """
    Logo del proyecto subido (ruta absoluta) o fallback estático Valle Alegre.
    WeasyPrint/xhtml2pdf resuelven file: o nombre en STATIC.
    """
    path = _proyecto_logo_path(proyecto)
    if path is not None:
        return path.as_uri()
    return "logo_valle_alegre.png"


PDF_HEADER_LOGO_WIDTH = 320
PDF_HEADER_LOGO_HEIGHT = 100


def _logo_content_bbox_rgba(
    img, *, white: int = 248, alpha_floor: int = 28
) -> tuple[int, int, int, int] | None:
    """Recorta márgenes casi blancos / transparentes alrededor del logo."""
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


def _path_desde_logo_src(src: str | Path | None) -> Path | None:
    if src is None:
        return None
    if isinstance(src, Path):
        return src if src.is_file() else None
    raw = str(src).strip()
    if not raw:
        return None
    if raw.lower().startswith("file:"):
        parsed = urlparse(raw)
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        p = Path(path)
        return p if p.is_file() else None
    found = finders.find(raw)
    if found:
        p = Path(found)
        return p if p.is_file() else None
    p = Path(settings.BASE_DIR) / "static" / raw
    return p if p.is_file() else None


def _logo_en_caja_para_pdf(
    src: str | Path | None,
    *,
    ancho: int = PDF_HEADER_LOGO_WIDTH,
    alto: int = PDF_HEADER_LOGO_HEIGHT,
) -> str:
    """
    Escala el logo para llenar una caja fija (mismo tamaño visual en cabecera PDF).
    Recorta márgenes blancos, centra en canvas transparente y cachea en disco.
    """
    path = _path_desde_logo_src(src)
    if path is None:
        return str(src or "")
    try:
        from PIL import Image

        cache_dir = Path(tempfile.gettempdir()) / "pbr-pdf-logos"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        key = hashlib.sha256(
            f"{path.resolve()}:{mtime}:{ancho}x{alto}".encode("utf-8", errors="replace")
        ).hexdigest()[:28]
        out = cache_dir / f"hdr_{key}.png"
        if out.is_file():
            return out.as_uri()

        img = Image.open(path).convert("RGBA")
        bbox = _logo_content_bbox_rgba(img)
        if bbox:
            pad = 4
            left = max(0, bbox[0] - pad)
            top = max(0, bbox[1] - pad)
            right = min(img.width, bbox[2] + pad)
            bottom = min(img.height, bbox[3] + pad)
            img = img.crop((left, top, right, bottom))
        w, h = img.size
        if w < 1 or h < 1:
            return path.as_uri()
        scale = min(ancho / w, alto / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (ancho, alto), (255, 255, 255, 0))
        canvas.paste(img, ((ancho - nw) // 2, (alto - nh) // 2), img)
        canvas.save(out, format="PNG", optimize=True)
        return out.as_uri()
    except Exception:
        logger.exception("No se pudo normalizar logo PDF: %s", path)
        return path.as_uri()


def _watermark_faded_src(proyecto, *, opacity: float = 0.11) -> str:
    """
    Marca de agua atenuada (PNG con alfa).
    xhtml2pdf no respeta opacity CSS ni position:fixed: sin esto el logo
    del proyecto aparece opaco y encima del contenido.
    """
    src = _proyecto_logo_path(proyecto)
    if src is None:
        return "logo_valle_alegre.png"
    try:
        from PIL import Image

        cache_dir = Path(tempfile.gettempdir()) / "pbr-pdf-watermark"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            mtime = src.stat().st_mtime_ns
        except OSError:
            mtime = 0
        key = hashlib.sha256(
            f"{src.resolve()}:{mtime}:{opacity}".encode("utf-8", errors="replace")
        ).hexdigest()[:28]
        out = cache_dir / f"wm_{key}.png"
        if not out.is_file():
            img = Image.open(src).convert("RGBA")
            # Limitar tamaño para PDF (evita logos enormes en cabecera).
            max_side = 900
            w, h = img.size
            if max(w, h) > max_side:
                ratio = max_side / float(max(w, h))
                img = img.resize(
                    (max(1, int(w * ratio)), max(1, int(h * ratio))),
                    Image.Resampling.LANCZOS,
                )
            pixels = img.getdata()
            faded = []
            for r, g, b, a in pixels:
                # Fondo blanco / casi blanco → totalmente transparente
                if r >= 248 and g >= 248 and b >= 248:
                    faded.append((r, g, b, 0))
                    continue
                faded.append((r, g, b, int(a * opacity)))
            img.putdata(faded)
            img.save(out, format="PNG", optimize=True)
        return out.as_uri()
    except Exception:
        logger.exception("No se pudo atenuar marca de agua del proyecto")
        return src.as_uri()


def branding_pdf_context(proyecto=None, *, empresa_default: str = "desarrollos") -> dict:
    """
    Logos estándar para todos los PDF (visibles, sin marca de agua):
    - Paredes Desarrollos + logo del proyecto + Paredes Bienes Raíces
    """
    from core.marcas import MARCAS, SLUG_BIENES_RAICES, SLUG_DESARROLLOS

    des = MARCAS[SLUG_DESARROLLOS]
    br = MARCAS[SLUG_BIENES_RAICES]
    empresa_logo, empresa_nombre = _branding_empresa_pdf(default_slug=empresa_default)
    proy_path = _proyecto_logo_path(proyecto)
    proy_logo_raw = proy_path.as_uri() if proy_path is not None else "logo_valle_alegre.png"
    slot = dict(ancho=PDF_HEADER_LOGO_WIDTH, alto=PDF_HEADER_LOGO_HEIGHT)
    return {
        "logo_desarrollos_src": _logo_en_caja_para_pdf(str(des["logo"]), **slot),
        "logo_bienes_src": _logo_en_caja_para_pdf(str(br["logo"]), **slot),
        "empresa_logo_src": _logo_en_caja_para_pdf("logo_paredes_desarrollos.png", **slot),
        "empresa_logo_alt": str(des["nombre"]),
        "empresa_nombre": str(des["nombre"]),
        "razon_social_desarrollos": "Paredes Desarrollos Inmobiliarios, S.A.S. de C.V.",
        "proyecto_logo_src": _logo_en_caja_para_pdf(proy_logo_raw, **slot),
        "pdf_header_logo_width": PDF_HEADER_LOGO_WIDTH,
        "pdf_header_logo_height": PDF_HEADER_LOGO_HEIGHT,
        # Sombra atenuada (solo para recibo / fondo). No usar como logo de cabecera.
        "watermark_logo_src": _watermark_faded_src(proyecto, opacity=0.18),
        "proyecto_nombre": (proyecto.nombre if proyecto is not None else "") or "",
        "recibo_contacto_nombre": "Karen Patricia Vásquez Merlos",
        "formato_aceptacion_direccion": (
            getattr(settings, "PBR_FORMATO_ACEPTACION_DIRECCION", "") or ""
        ).strip(),
    }


def _fecha_espanol_larga(d) -> str:
    if d is None:
        return ""
    meses = (
        "",
        "ENERO",
        "FEBRERO",
        "MARZO",
        "ABRIL",
        "MAYO",
        "JUNIO",
        "JULIO",
        "AGOSTO",
        "SEPTIEMBRE",
        "OCTUBRE",
        "NOVIEMBRE",
        "DICIEMBRE",
    )
    return f"{d.day} DE {meses[d.month]} DE {d.year}"


def _numero_recibo_corto(numero: str) -> str:
    """Últimos dígitos del correlativo para caja 'No. 0003'."""
    digits = "".join(c for c in str(numero or "") if c.isdigit())
    if not digits:
        return "0000"
    return digits[-4:].zfill(4)


def _saldos_desde_calendario(pago, *, capital_este):
    """
    Saldo según cuotas aún pendientes del plan.
    Si la suma de pagos supera el precio pero el calendario sigue abierto,
    evita mostrar $0,00.
    """
    from decimal import Decimal

    from django.db.models import Sum

    from inmobiliaria.models import CuotaProgramada
    from inmobiliaria.pago_desglose import desglose_para_recibo

    monto_pend = (
        CuotaProgramada.objects.filter(
            contrato_id=pago.contrato_id,
            estado__in=[
                CuotaProgramada.Estado.PENDIENTE,
                CuotaProgramada.Estado.VENCIDA,
            ],
        ).aggregate(t=Sum("monto"))["t"]
        or Decimal("0")
    )
    monto_pend = Decimal(monto_pend).quantize(Decimal("0.01"))
    desglose = desglose_para_recibo(pago)
    abono = Decimal(desglose.monto_abono_capital or 0).quantize(Decimal("0.01"))
    if abono < 0:
        abono = Decimal("0.00")

    # Tras liquidar cuota(s), el pendiente ya no las incluye.
    # El abono a capital (excedente) también baja el saldo mostrado.
    nuevo = (monto_pend - abono).quantize(Decimal("0.01"))
    if nuevo < 0:
        nuevo = Decimal("0.00")
    # Reserva / prima / contado / abono puro: no quitan filas del calendario.
    if (
        pago.concepto
        in {
            pago.Concepto.RESERVA,
            pago.Concepto.PRIMA,
            pago.Concepto.CONTADO,
            pago.Concepto.ABONO_CAPITAL,
        }
        and desglose.monto_cuotas <= 0
    ):
        nuevo = (monto_pend - capital_este).quantize(Decimal("0.01"))
        if nuevo < 0:
            nuevo = Decimal("0.00")

    saldo_anterior = (nuevo + capital_este).quantize(Decimal("0.01"))
    return saldo_anterior, nuevo


def _saldos_recibo(pago) -> dict:
    """
    Saldo anterior / recibido / nuevo saldo para el pie del recibo digital.

    1) Preferente: precio del inmueble − capital pagado antes de este movimiento.
    2) Si eso da 0/negativo pero aún hay cuotas pendientes, usa el saldo del
       calendario (no mostrar $0 cuando el plan sigue abierto).
    """
    from decimal import Decimal

    from django.db.models import Q, Sum

    from inmobiliaria.models import CuotaProgramada, Pago

    contrato = pago.contrato
    precio = Decimal(contrato.precio_final or 0).quantize(Decimal("0.01"))

    conceptos_capital = {
        Pago.Concepto.RESERVA,
        Pago.Concepto.PRIMA,
        Pago.Concepto.CONTADO,
        Pago.Concepto.CUOTA,
        Pago.Concepto.ABONO_CAPITAL,
    }
    qs = contrato.pagos.filter(concepto__in=conceptos_capital).filter(
        Q(fecha__lt=pago.fecha) | Q(fecha=pago.fecha, pk__lt=pago.pk)
    )
    bruto = qs.aggregate(t=Sum("monto"))["t"] or Decimal("0")
    rec_inc = qs.aggregate(t=Sum("monto_recargo_incluido"))["t"] or Decimal("0")
    if rec_inc < 0:
        rec_inc = Decimal("0")
    capital_antes = (bruto - rec_inc).quantize(Decimal("0.01"))
    if capital_antes < 0:
        capital_antes = Decimal("0.00")

    saldo_por_precio = (precio - capital_antes).quantize(Decimal("0.01"))

    rec_este = Decimal(pago.monto_recargo_incluido or 0).quantize(Decimal("0.01"))
    if rec_este < 0:
        rec_este = Decimal("0.00")
    if pago.concepto == Pago.Concepto.MORA:
        capital_este = Decimal("0.00")
    elif pago.concepto in conceptos_capital:
        capital_este = (Decimal(pago.monto) - rec_este).quantize(Decimal("0.01"))
        if capital_este < 0:
            capital_este = Decimal("0.00")
    else:
        capital_este = Decimal("0.00")

    usar_calendario = saldo_por_precio <= 0 and CuotaProgramada.objects.filter(
        contrato_id=pago.contrato_id,
        estado__in=[
            CuotaProgramada.Estado.PENDIENTE,
            CuotaProgramada.Estado.VENCIDA,
        ],
    ).exists()

    if usar_calendario:
        saldo_anterior, nuevo_saldo = _saldos_desde_calendario(
            pago, capital_este=capital_este
        )
    else:
        saldo_anterior = saldo_por_precio if saldo_por_precio > 0 else Decimal("0.00")
        nuevo_saldo = (saldo_anterior - capital_este).quantize(Decimal("0.01"))
        if nuevo_saldo < 0:
            nuevo_saldo = Decimal("0.00")

    return {
        "saldo_anterior": saldo_anterior,
        "saldo_anterior_fmt": format_monto_sv(saldo_anterior),
        "recibido_fmt": format_monto_sv(pago.monto),
        "nuevo_saldo": nuevo_saldo,
        "nuevo_saldo_fmt": format_monto_sv(nuevo_saldo),
    }


def _html_to_pdf_bytes_weasyprint(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, base_url=_pdf_static_base_url()).write_pdf()


def _xhtml2pdf_data_uri_to_temp_file(uri: str) -> str | None:
    """xhtml2pdf no incorpora bien data: en <img>; volcamos a un PNG temporal."""
    comma = uri.find(",")
    if comma == -1:
        return None
    header = uri[:comma].lower()
    if "base64" not in header:
        return None
    try:
        raw = base64.b64decode(uri[comma + 1 :], validate=False)
    except (ValueError, TypeError):
        return None
    if len(raw) < 8:
        return None
    fd, path = tempfile.mkstemp(prefix="pbr-pdfimg-", suffix=".png")
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    return path


def _xhtml2pdf_resolve_resource(uri: str, rel: str) -> str:
    """Resuelve imágenes y recursos locales para xhtml2pdf (Windows / sin WeasyPrint)."""
    del rel  # API de xhtml2pdf; no usado aquí
    if uri.startswith(("http://", "https://")):
        return uri
    if uri.startswith("file:"):
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    # Media subida (ruta absoluta Windows / Unix)
    if len(uri) >= 2 and uri[1] == ":" and uri[0].isalpha():
        if Path(uri).is_file():
            return uri
    found = finders.find(uri)
    if found:
        return found
    name = uri.rsplit("/", 1)[-1]
    found = finders.find(name)
    if found:
        return found
    return uri


def _html_to_pdf_bytes_xhtml2pdf(html: str) -> bytes:
    from xhtml2pdf import pisa

    temp_files: list[str] = []

    def link_callback(uri: str, rel: str) -> str:
        if uri.startswith("data:"):
            path = _xhtml2pdf_data_uri_to_temp_file(uri)
            if path:
                temp_files.append(path)
                return path
        return _xhtml2pdf_resolve_resource(uri, rel)

    # @page y algunas propiedades avanzadas pueden confundir al parser; lo básico se conserva.
    html = re.sub(r"@page\s*\{[^}]*\}", "", html, flags=re.DOTALL)

    out = BytesIO()
    try:
        pdf = pisa.pisaDocument(
            src=BytesIO(html.encode("utf-8")),
            dest=out,
            encoding="utf-8",
            link_callback=link_callback,
        )
        if pdf.err:
            raise RuntimeError("xhtml2pdf reportó errores al generar el PDF.")
        data = out.getvalue()
        if not data:
            raise RuntimeError("xhtml2pdf devolvió un PDF vacío.")
        return data
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass


def _html_to_pdf_bytes(html: str) -> bytes:
    """
    Preferimos WeasyPrint (mejor CSS; típico en Linux con GTK).
    En Windows suele faltar libgobject/cairo: se usa xhtml2pdf como respaldo.
    """
    try:
        return _html_to_pdf_bytes_weasyprint(html)
    except (OSError, ImportError) as exc:
        logger.info(
            "WeasyPrint no disponible en este entorno (%s); usando xhtml2pdf.",
            exc,
        )
        return _html_to_pdf_bytes_xhtml2pdf(html)


def _ruta_local_desde_src_pdf(src: str) -> Path | None:
    """Convierte file://, ruta absoluta o nombre estático a Path local."""
    s = (src or "").strip()
    if not s:
        return None
    if s.startswith("file:"):
        parsed = urlparse(s)
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        p = Path(path)
        return p if p.is_file() else None
    p = Path(s)
    if p.is_file():
        return p
    found = finders.find(s) or finders.find(s.rsplit("/", 1)[-1])
    return Path(found) if found else None


def _aplicar_marca_agua_recibo(pdf_bytes: bytes, watermark_src: str) -> bytes:
    """
    Estampa el logo del proyecto (atenuado) detrás del cuadro central del recibo.
    Se hace en una capa PDF aparte para no abrir huecos en el HTML (xhtml2pdf).
    """
    if not pdf_bytes or not (watermark_src or "").strip():
        return pdf_bytes
    wm_path = _ruta_local_desde_src_pdf(watermark_src)
    if wm_path is None:
        return pdf_bytes
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return pdf_bytes

    # Posición: zona del cliente + tabla (debajo del encabezado).
    wm_html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 0; }}
  html, body {{ margin: 0; padding: 0; }}
  .wm {{
    width: 100%;
    text-align: center;
    padding-top: 270px;
  }}
  .wm img {{
    width: 240px;
    max-width: 55%;
    height: auto;
  }}
</style>
</head><body>
  <div class="wm"><img src="{wm_path.as_uri()}" alt=""></div>
</body></html>"""
    try:
        wm_pdf = _html_to_pdf_bytes(wm_html)
        content = PdfReader(BytesIO(pdf_bytes))
        stamp = PdfReader(BytesIO(wm_pdf))
        if not stamp.pages:
            return pdf_bytes
        stamp_page = stamp.pages[0]
        writer = PdfWriter()
        for page in content.pages:
            try:
                # under=True visual: logo detrás del texto del cuadro
                page.merge_page(stamp_page, over=False)
            except Exception:
                logger.exception("No se pudo fusionar marca de agua en una página del recibo")
            writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        return out.getvalue() or pdf_bytes
    except Exception:
        logger.exception("Fallo al estampar logo del proyecto en el recibo PDF")
        return pdf_bytes


def _sincronizar_recargo_incluido_pago(pago) -> None:
    """
    Ajusta monto_recargo_incluido según la regla: el atraso de una cuota
    se cobra en la siguiente (no en la misma cuota atrasada).
    """
    from decimal import Decimal

    from inmobiliaria.models import Pago
    from inmobiliaria.pago_desglose import cuotas_del_pago
    from inmobiliaria.recargo_administrativo import monto_recargo_para_liquidacion

    if pago.concepto != Pago.Concepto.CUOTA or not pago.contrato_id:
        return
    cuotas = cuotas_del_pago(pago)
    if not cuotas:
        return
    correcto = monto_recargo_para_liquidacion(
        pago.contrato,
        fecha=pago.fecha,
        cuotas_a_liquidar=cuotas,
        excluir_pago_id=pago.pk,
    )
    stored = Decimal(pago.monto_recargo_incluido or 0).quantize(Decimal("0.01"))
    if correcto == stored:
        return
    # No inventar dinero: el recargo guardado no puede superar el excedente sobre cuotas.
    from inmobiliaria.pago_desglose import _suma_cuotas

    disponible = (Decimal(pago.monto) - _suma_cuotas(cuotas)).quantize(Decimal("0.01"))
    if disponible < 0:
        disponible = Decimal("0.00")
    nuevo = min(correcto, disponible).quantize(Decimal("0.01"))
    if nuevo == stored:
        return
    Pago.objects.filter(pk=pago.pk).update(monto_recargo_incluido=nuevo)
    pago.monto_recargo_incluido = nuevo


def _pdf_recibo_ingreso_bytes(*, doc, pago) -> bytes:
    _sincronizar_recargo_incluido_pago(pago)
    ctx = _contexto_recibo_ingreso(doc=doc, pago=pago)
    html = render_to_string("docs/recibo_ingreso.html", ctx)
    pdf_bytes = _html_to_pdf_bytes(html)
    return _aplicar_marca_agua_recibo(
        pdf_bytes,
        ctx.get("watermark_logo_src") or ctx.get("proyecto_logo_src") or "",
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _nombre_recibido_por_recibo(*, doc, pago) -> str:
    """
    Texto bajo «RECIBIDO POR» en el recibo digital.
    - Administrador / superusuario → OSCAR RENE PAREDES
    - Gerente (u otro usuario que emite/valida) → nombre registrado en el sistema
    """
    from usuarios.roles import es_superusuario_o_admin_app

    user = getattr(pago, "validado_por", None) or getattr(doc, "emitido_por", None)
    if user is not None and es_superusuario_o_admin_app(user):
        return "OSCAR RENE PAREDES"
    if user is None:
        return "OSCAR RENE PAREDES"
    nombre = (user.get_full_name() or "").strip()
    if not nombre:
        nombre = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    if not nombre:
        nombre = (getattr(user, "username", "") or "").strip()
    return (nombre or "—").upper()


def _contexto_recibo_ingreso(*, doc, pago) -> dict:
    from inmobiliaria.pago_desglose import desglose_para_recibo
    from inmobiliaria.signals import aplicar_cuotas_programadas_del_pago

    # Asegura cuotas vinculadas antes del PDF (excedente = abono a capital en el mismo recibo).
    if pago.concepto == pago.Concepto.CUOTA and pago.puede_emitir_recibo_cliente:
        if not pago.cuotas_aplicadas.exists():
            aplicar_cuotas_programadas_del_pago(pago)
            pago.refresh_from_db()

    contrato = pago.contrato
    inmueble = contrato.inmueble
    proyecto = inmueble.proyecto
    desglose = desglose_para_recibo(pago)
    lineas_fmt = [
        (etiqueta, format_monto_sv(monto), f"{float(cantidad):.1f}")
        for etiqueta, monto, cantidad in desglose.lineas
    ]
    poligono = ""
    if getattr(inmueble, "poligono_id", None) and inmueble.poligono_id:
        poligono = (inmueble.poligono.nombre or "").strip()
    concepto_detalle = pago.get_concepto_display()
    if lineas_fmt:
        concepto_detalle = " / ".join(et for et, _monto, _cant in lineas_fmt)
    concepto_detalle = (
        f"{concepto_detalle} / VALOR DEL INMUEBLE {format_monto_sv(contrato.precio_final)}"
    )
    vendedor = ""
    if hasattr(contrato, "nombre_vendedor_documentos"):
        vendedor = (contrato.nombre_vendedor_documentos() or "").strip()

    ctx = {
        "doc": doc,
        "pago": pago,
        "contrato": contrato,
        "cliente": contrato.cliente,
        "proyecto": proyecto,
        "inmueble": inmueble,
        "poligono_nombre": poligono,
        "lugar_emision": _lugar_emision_republica(proyecto),
        "razon_social_receptor": "Paredes Desarrollos Inmobiliarios, S.A.S. de C.V.",
        "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
        "monto_fmt": format_monto_sv(pago.monto),
        "monto_letras": monto_usd_letras_es(pago.monto),
        "desglose": desglose,
        "desglose_lineas_fmt": lineas_fmt,
        "monto_abono_capital_fmt": (
            format_monto_sv(desglose.monto_abono_capital)
            if desglose.monto_abono_capital > 0
            else ""
        ),
        "recargo_no_cobrado_fmt": (
            format_monto_sv(desglose.monto_recargo_debido - desglose.monto_recargo)
            if desglose.monto_recargo_debido > desglose.monto_recargo
            else ""
        ),
        "concepto_detalle": concepto_detalle,
        "recibo_numero_corto": _numero_recibo_corto(doc.numero),
        "fecha_emision_larga": _fecha_espanol_larga(
            timezone.localtime(doc.emitido_en).date()
            if getattr(doc, "emitido_en", None)
            else pago.fecha
        ),
        "fecha_contrato_fmt": (
            contrato.fecha_firma.strftime("%d / %m / %Y") if contrato.fecha_firma else "—"
        ),
        "vendedor_nombre": vendedor,
        "precio_inmueble_fmt": format_monto_sv(contrato.precio_final),
        "recibido_por_nombre": _nombre_recibido_por_recibo(doc=doc, pago=pago),
        "logo_pie_empresa_src": "logo_paredes_desarrollos_pie.png",
        **_saldos_recibo(pago),
        **branding_pdf_context(proyecto),
    }
    return ctx


def emitir_recibo_ingreso(*, pago, emitido_por=None) -> tuple[DocumentoEmitido, ReciboNotificacionInfo]:
    if not pago.puede_emitir_recibo_cliente:
        raise ValueError(
            "El abono (reserva, prima, cuota o abono a capital) debe ser validado por gerencia antes de emitir el recibo."
        )
    # Garantiza lote/polígono/proyecto para el PDF estilo RECIBO DIGITAL.
    from inmobiliaria.models import Pago

    pago = (
        Pago.objects.select_related(
            "contrato",
            "contrato__cliente",
            "contrato__inmueble",
            "contrato__inmueble__proyecto",
            "contrato__inmueble__poligono",
            "contrato__vendedor_perfil",
            "formato_aceptacion",
            "validado_por",
        )
        .filter(pk=pago.pk)
        .first()
        or pago
    )

    # Si ya hay recibo de este pago: actualizar PDF (mismo número, sin duplicar).
    existente = (
        DocumentoEmitido.objects.filter(
            tipo=DocumentoTipo.RECIBO_INGRESO,
            pago_id=pago.pk,
        )
        .order_by("-id")
        .first()
    )
    if existente is not None:
        regenerar_pdf_y_persistir(existente)
        notif = ReciboNotificacionInfo(
            correo_enviado=False,
            correo_entrega_real=False,
            whatsapp_pdf_por_api=False,
            meta_configurado=False,
            meta_solo_texto=False,
            twilio_pdf=False,
        )
        try:
            from .recibo_notificacion import notificar_recibo_emitido

            notif = notificar_recibo_emitido(existente, pago)
        except Exception:
            logger.exception(
                "Fallo al notificar recibo existente %s (correo/WhatsApp); el PDF sí se actualizó.",
                existente.numero,
            )
        return existente, notif

    numero = _next_correlativo(tipo=DocumentoTipo.RECIBO_INGRESO, cfg=CorrelativoConfig())
    doc = DocumentoEmitido.objects.create(
        tipo=DocumentoTipo.RECIBO_INGRESO,
        numero=numero,
        pago=pago,
        contrato=pago.contrato,
        inmueble=pago.contrato.inmueble if pago.contrato_id else None,
        emitido_por=emitido_por,
    )

    pdf_bytes = _pdf_recibo_ingreso_bytes(doc=doc, pago=pago)
    doc.hash_sha256 = _sha256(pdf_bytes)
    doc.pdf_file.save(f"{numero}.pdf", ContentFile(pdf_bytes), save=False)
    doc.save(update_fields=["hash_sha256", "pdf_file"])

    notif = ReciboNotificacionInfo(
        correo_enviado=False,
        correo_entrega_real=False,
        whatsapp_pdf_por_api=False,
        meta_configurado=False,
        meta_solo_texto=False,
        twilio_pdf=False,
    )
    try:
        from .recibo_notificacion import notificar_recibo_emitido

        notif = notificar_recibo_emitido(doc, pago)
    except Exception:
        logger.exception(
            "Fallo al notificar recibo %s (correo/WhatsApp); el PDF sí se guardó.",
            doc.numero,
        )

    return doc, notif


def emitir_promesa_venta(*, contrato, emitido_por=None) -> DocumentoEmitido:
    numero = _next_correlativo(tipo=DocumentoTipo.PROMESA_VENTA, cfg=CorrelativoConfig())
    doc = DocumentoEmitido.objects.create(
        tipo=DocumentoTipo.PROMESA_VENTA,
        numero=numero,
        contrato=contrato,
        inmueble=contrato.inmueble,
        emitido_por=emitido_por,
    )

    html = render_to_string(
        "docs/promesa_venta.html",
        {
            "doc": doc,
            "contrato": contrato,
            "cliente": contrato.cliente,
            "inmueble": contrato.inmueble,
            "proyecto": contrato.inmueble.proyecto,
            "poligono": contrato.inmueble.poligono,
            "hoy": timezone.localdate(),
            "lugar_emision": _lugar_emision_republica(contrato.inmueble.proyecto),
            "razon_social_vendedor": _razon_social_negocio_pdf(),
            "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
            **branding_pdf_context(contrato.inmueble.proyecto),
        },
    )
    pdf_bytes = _html_to_pdf_bytes(html)
    doc.hash_sha256 = _sha256(pdf_bytes)
    doc.pdf_file.save(f"{numero}.pdf", ContentFile(pdf_bytes), save=False)
    doc.save(update_fields=["hash_sha256", "pdf_file"])
    return doc


def _pct_txt_comision(pct) -> str:
    if pct is None:
        return ""
    return f"{pct.normalize()} %"


def _monto_comision_documento(doc: DocumentoEmitido, contrato: Contrato):
    from decimal import Decimal

    if doc.monto_comision_usd is not None and doc.monto_comision_usd > Decimal("0"):
        return doc.monto_comision_usd
    return contrato.monto_comision_efectivo()


def _liquidacion_comision_para_doc(doc: "DocumentoEmitido", contrato: Contrato, monto):
    """Snapshot guardado o recálculo desde tipo de vendedor / monto bruto."""
    from decimal import Decimal

    from inmobiliaria.retencion_comision_sv import liquidar_comision_vendedor

    vp = getattr(contrato, "vendedor_perfil", None)
    tipo = (doc.comision_tipo_persona or "").strip().upper()
    if not tipo and vp is not None:
        tipo = (vp.tipo_persona or "").strip().upper()

    # Si el documento ya tiene desglose fiscal, úselo (auditoría).
    if (
        doc.comision_neto_usd is not None
        and doc.comision_retencion_renta_usd is not None
        and monto is not None
    ):
        from inmobiliaria.retencion_comision_sv import LiquidacionComisionVendedor
        from inmobiliaria.models import Vendedor

        bruto = Decimal(monto).quantize(Decimal("0.01"))
        iva = Decimal(doc.comision_iva_usd or 0).quantize(Decimal("0.01"))
        ret_r = Decimal(doc.comision_retencion_renta_usd or 0).quantize(Decimal("0.01"))
        ret_i = Decimal(doc.comision_retencion_iva_usd or 0).quantize(Decimal("0.01"))
        neto = Decimal(doc.comision_neto_usd).quantize(Decimal("0.01"))
        tipo_ok = tipo or Vendedor.TipoPersona.NATURAL
        label = (
            "Contribuyente"
            if tipo_ok == Vendedor.TipoPersona.CONTRIBUYENTE
            else "Natural"
        )
        return LiquidacionComisionVendedor(
            tipo_persona=tipo_ok,
            tipo_persona_label=label,
            bruto=bruto,
            iva=iva,
            retencion_renta=ret_r,
            retencion_iva=ret_i,
            total_con_iva=(bruto + iva).quantize(Decimal("0.01")),
            neto=neto,
            pct_renta=Decimal("10"),
            pct_iva=Decimal("13"),
            pct_retencion_iva=Decimal("1"),
            notas=(),
        )

    return liquidar_comision_vendedor(monto, tipo_persona=tipo or None, vendedor=vp)


def _contexto_recibo_comision_vendedor(
    *,
    doc: DocumentoEmitido,
    contrato: Contrato,
    monto,
    comision_porcentaje=None,
    concepto: str = "",
    marca_slug: str | None = None,
    liquidacion=None,
) -> dict:
    nombre_v = contrato.nombre_vendedor_documentos()
    proyecto = contrato.inmueble.proyecto
    pct = comision_porcentaje
    if pct is None and doc.comision_porcentaje_recibo is not None:
        pct = doc.comision_porcentaje_recibo
    concepto_txt = (concepto or doc.comision_concepto or "").strip()
    if not concepto_txt:
        from .forms import _concepto_comision_default

        concepto_txt = _concepto_comision_default(contrato)

    liq = liquidacion or _liquidacion_comision_para_doc(doc, contrato, monto)
    vp = getattr(contrato, "vendedor_perfil", None)
    poligono = getattr(contrato.inmueble, "poligono", None)
    from decimal import Decimal

    retenciones_total = (liq.retencion_renta + liq.retencion_iva).quantize(Decimal("0.01"))
    concepto_detalle = concepto_txt.upper()
    if pct is not None:
        concepto_detalle = (
            f"{concepto_detalle} / {(_pct_txt_comision(pct) or '').upper()} "
            f"SOBRE {format_monto_sv(contrato.precio_final)}"
        )
    vendedor_direccion = "—"
    if vp is not None:
        partes_dir = []
        if (vp.email or "").strip():
            partes_dir.append(vp.email.strip())
        if (vp.telefono or "").strip():
            partes_dir.append(f"Tel. {vp.telefono.strip()}")
        if (vp.notas or "").strip():
            partes_dir.append(vp.notas.strip()[:120])
        if partes_dir:
            vendedor_direccion = " · ".join(partes_dir)

    return {
        "doc": doc,
        "contrato": contrato,
        "cliente": contrato.cliente,
        "proyecto": proyecto,
        "inmueble": contrato.inmueble,
        "poligono_nombre": poligono.nombre if poligono else "",
        "vendedor_nombre": nombre_v,
        "vendedor": vp,
        "vendedor_direccion": vendedor_direccion,
        "monto": liq.bruto,
        "monto_fmt": format_monto_sv(liq.neto),
        "monto_letras": monto_usd_letras_es(liq.neto),
        "comision_porcentaje": pct,
        "comision_porcentaje_txt": _pct_txt_comision(pct),
        "comision_concepto": concepto_txt,
        "concepto_detalle": concepto_detalle,
        "precio_final_fmt": format_monto_sv(contrato.precio_final),
        "lugar_emision": _lugar_emision_republica(proyecto),
        "razon_social_emisor": _razon_social_negocio_pdf(),
        "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
        "recibo_numero_corto": _numero_recibo_corto(doc.numero),
        "fecha_emision_larga": _fecha_espanol_larga(
            timezone.localtime(doc.emitido_en).date()
            if getattr(doc, "emitido_en", None)
            else timezone.localdate()
        ),
        "fecha_contrato_fmt": contrato.fecha_firma.strftime("%d/%m/%Y")
        if contrato.fecha_firma
        else "—",
        "liq": liq,
        "bruto_fmt": format_monto_sv(liq.bruto),
        "iva_fmt": format_monto_sv(liq.iva),
        "retencion_renta_fmt": format_monto_sv(liq.retencion_renta),
        "retencion_iva_fmt": format_monto_sv(liq.retencion_iva),
        "total_con_iva_fmt": format_monto_sv(liq.total_con_iva),
        "neto_fmt": format_monto_sv(liq.neto),
        "recibido_fmt": format_monto_sv(liq.neto),
        "saldo_anterior_fmt": format_monto_sv(liq.bruto),
        "nuevo_saldo_fmt": format_monto_sv(retenciones_total),
        **branding_pdf_context(proyecto),
    }


def _pdf_recibo_comision_vendedor_bytes(
    *,
    doc: DocumentoEmitido,
    contrato: Contrato,
    monto,
    comision_porcentaje=None,
    concepto: str = "",
    marca_slug: str | None = None,
    liquidacion=None,
) -> bytes:
    """Mismo pipeline visual que el recibo del cliente (HTML + marca de agua)."""
    ctx = _contexto_recibo_comision_vendedor(
        doc=doc,
        contrato=contrato,
        monto=monto,
        comision_porcentaje=comision_porcentaje,
        concepto=concepto,
        marca_slug=marca_slug,
        liquidacion=liquidacion,
    )
    html = render_to_string("docs/recibo_comision_vendedor.html", ctx)
    pdf_bytes = _html_to_pdf_bytes(html)
    return _aplicar_marca_agua_recibo(
        pdf_bytes,
        ctx.get("watermark_logo_src") or ctx.get("proyecto_logo_src") or "",
    )


def emitir_recibo_comision_vendedor(
    *,
    contrato: Contrato,
    emitido_por=None,
    monto_comision=None,
    comision_porcentaje=None,
    concepto: str = "",
    marca_slug: str | None = None,
) -> DocumentoEmitido:
    """PDF de comisión al vendedor (mismo formato visual del recibo digital del cliente)."""
    from decimal import Decimal

    from inmobiliaria.comision_vendedor import requisitos_comision_venta
    from inmobiliaria.retencion_comision_sv import liquidar_comision_vendedor

    req = requisitos_comision_venta(contrato)
    if not req.puede_emitir:
        raise ValueError(
            "No se puede emitir la comisión de venta todavía: " + " ".join(req.motivos)
        )

    if monto_comision is not None:
        monto = monto_comision
    else:
        monto = contrato.monto_comision_efectivo()
    if monto is None or monto <= Decimal("0"):
        raise ValueError("Indique un monto de comisión mayor a cero.")

    nombre_v = contrato.nombre_vendedor_documentos()
    if not (nombre_v or "").strip():
        raise ValueError("Indique el asesor de ventas en el contrato (catálogo o nombre).")

    vp = getattr(contrato, "vendedor_perfil", None)
    liq = liquidar_comision_vendedor(monto, vendedor=vp)

    numero = _next_correlativo(
        tipo=DocumentoTipo.RECIBO_COMISION_VENDEDOR, cfg=CorrelativoConfig()
    )
    doc = DocumentoEmitido.objects.create(
        tipo=DocumentoTipo.RECIBO_COMISION_VENDEDOR,
        numero=numero,
        contrato=contrato,
        inmueble=contrato.inmueble,
        vendedor=contrato.vendedor_perfil,
        emitido_por=emitido_por,
        monto_comision_usd=liq.bruto,
        comision_porcentaje_recibo=comision_porcentaje,
        comision_concepto=(concepto or "").strip(),
        comision_tipo_persona=liq.tipo_persona,
        comision_iva_usd=liq.iva,
        comision_retencion_renta_usd=liq.retencion_renta,
        comision_retencion_iva_usd=liq.retencion_iva,
        comision_neto_usd=liq.neto,
    )

    pdf_bytes = _pdf_recibo_comision_vendedor_bytes(
        doc=doc,
        contrato=contrato,
        monto=liq.bruto,
        comision_porcentaje=comision_porcentaje,
        concepto=concepto,
        marca_slug=marca_slug,
        liquidacion=liq,
    )
    doc.hash_sha256 = _sha256(pdf_bytes)
    doc.pdf_file.save(f"{numero}.pdf", ContentFile(pdf_bytes), save=False)
    doc.save(
        update_fields=[
            "hash_sha256",
            "pdf_file",
            "monto_comision_usd",
            "comision_porcentaje_recibo",
            "comision_concepto",
            "comision_tipo_persona",
            "comision_iva_usd",
            "comision_retencion_renta_usd",
            "comision_retencion_iva_usd",
            "comision_neto_usd",
        ]
    )
    if getattr(settings, "VENDEDOR_NOTIFICAR_RECIBO_COMISION_EMAIL", True):
        doc_id = doc.pk

        def _correo_comision():
            from .vendedor_notificacion import enviar_recibo_comision_vendedor_correo

            enviar_recibo_comision_vendedor_correo(doc_id)

        transaction.on_commit(_correo_comision)
    return doc


def _contexto_recibo_comision_alquiler(
    *,
    doc: DocumentoEmitido,
    inmueble: Inmueble,
    monto,
    vendedor_nombre: str = "",
    comision_porcentaje=None,
    concepto: str = "",
) -> dict:
    from inmobiliaria.forms_recibo_alquiler import concepto_comision_alquiler, renta_mensual_alquiler

    proyecto = inmueble.proyecto
    pct = comision_porcentaje
    if pct is None and doc.comision_porcentaje_recibo is not None:
        pct = doc.comision_porcentaje_recibo
    nombre = (vendedor_nombre or doc.recibo_beneficiario_nombre or "").strip()
    concepto_txt = (concepto or doc.comision_concepto or "").strip()
    if not concepto_txt:
        concepto_txt = concepto_comision_alquiler(inmueble)
    renta = renta_mensual_alquiler(inmueble)
    renta_fmt = format_monto_sv(renta) if renta is not None else "—"
    return {
        "doc": doc,
        "inmueble": inmueble,
        "proyecto": proyecto,
        "vendedor_nombre": nombre,
        "monto": monto,
        "monto_fmt": format_monto_sv(monto),
        "monto_letras": monto_usd_letras_es(monto),
        "comision_porcentaje": pct,
        "comision_porcentaje_txt": _pct_txt_comision(pct),
        "comision_concepto": concepto_txt,
        "renta_mensual_fmt": renta_fmt,
        "lugar_emision": _lugar_emision_republica(proyecto),
        "razon_social_emisor": _razon_social_negocio_pdf(),
        "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
        **branding_pdf_context(proyecto, empresa_default="bienes-raices"),
    }


def emitir_recibo_comision_alquiler(
    *,
    inmueble: Inmueble,
    emitido_por=None,
    vendedor_nombre: str,
    asesor_alquiler=None,
    monto_comision=None,
    comision_porcentaje=None,
    concepto: str = "",
) -> DocumentoEmitido:
    """PDF de comisión — solo módulo de alquileres (inmuebles con en_alquiler=True)."""
    from decimal import Decimal

    monto = monto_comision
    if monto is None or monto <= Decimal("0"):
        raise ValueError("Indique un monto de comisión mayor a cero.")
    nombre = (vendedor_nombre or "").strip()
    if not nombre:
        raise ValueError("Indique el nombre del asesor beneficiario.")

    numero = _next_correlativo(
        tipo=DocumentoTipo.RECIBO_COMISION_ARRENDAMIENTO, cfg=CorrelativoConfig()
    )
    doc = DocumentoEmitido.objects.create(
        tipo=DocumentoTipo.RECIBO_COMISION_ARRENDAMIENTO,
        numero=numero,
        inmueble=inmueble,
        asesor_alquiler=asesor_alquiler,
        emitido_por=emitido_por,
        monto_comision_usd=monto,
        comision_porcentaje_recibo=comision_porcentaje,
        comision_concepto=(concepto or "").strip(),
        recibo_beneficiario_nombre=nombre,
    )

    if not inmueble.en_alquiler:
        raise ValueError("El recibo de alquiler solo aplica a inmuebles marcados en alquiler.")

    html = render_to_string(
        "docs/recibo_comision_alquiler.html",
        _contexto_recibo_comision_alquiler(
            doc=doc,
            inmueble=inmueble,
            monto=monto,
            vendedor_nombre=nombre,
            comision_porcentaje=comision_porcentaje,
            concepto=concepto,
        ),
    )
    pdf_bytes = _html_to_pdf_bytes(html)
    doc.hash_sha256 = _sha256(pdf_bytes)
    doc.pdf_file.save(f"{numero}.pdf", ContentFile(pdf_bytes), save=False)
    doc.save(
        update_fields=[
            "hash_sha256",
            "pdf_file",
            "monto_comision_usd",
            "comision_porcentaje_recibo",
            "comision_concepto",
            "recibo_beneficiario_nombre",
        ]
    )
    return doc


def regenerar_pdf_documento(doc: DocumentoEmitido) -> bytes:
    """Reconstruye el PDF desde la BD si el fichero en MEDIA desapareció (p. ej. disco efímero)."""
    from decimal import Decimal

    if doc.tipo == DocumentoTipo.RECIBO_INGRESO:
        pago = doc.pago
        if pago is None:
            raise ValueError(
                "Este recibo ya no tiene el pago vinculado; no se puede regenerar el PDF."
            )
        contrato = pago.contrato
        if contrato is None or contrato.inmueble_id is None:
            raise ValueError("Datos del contrato incompletos; no se puede regenerar el recibo.")
        return _pdf_recibo_ingreso_bytes(doc=doc, pago=pago)

    if doc.tipo == DocumentoTipo.PROMESA_VENTA:
        contrato = doc.contrato
        if contrato is None:
            raise ValueError("Este documento no tiene contrato; no se puede regenerar la promesa.")
        html = render_to_string(
            "docs/promesa_venta.html",
            {
                "doc": doc,
                "contrato": contrato,
                "cliente": contrato.cliente,
                "inmueble": contrato.inmueble,
                "proyecto": contrato.inmueble.proyecto,
                "poligono": contrato.inmueble.poligono,
                "hoy": timezone.localdate(),
                "lugar_emision": _lugar_emision_republica(contrato.inmueble.proyecto),
                "razon_social_vendedor": _razon_social_negocio_pdf(),
                "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
                **branding_pdf_context(contrato.inmueble.proyecto),
            },
        )
        return _html_to_pdf_bytes(html)

    if doc.tipo == DocumentoTipo.RECIBO_COMISION_VENDEDOR:
        if doc.contrato_id is None:
            raise ValueError("Este recibo no tiene contrato; no se puede regenerar el PDF.")
        contrato = (
            Contrato.objects.select_related(
                "cliente",
                "inmueble",
                "inmueble__proyecto",
                "inmueble__poligono",
                "vendedor_perfil",
            )
            .filter(pk=doc.contrato_id)
            .first()
        )
        if contrato is None:
            raise ValueError("Este recibo no tiene contrato; no se puede regenerar el PDF.")
        monto = _monto_comision_documento(doc, contrato)
        if monto is None or monto <= Decimal("0"):
            raise ValueError(
                "No hay monto de comisión guardado en el documento; no se puede regenerar este PDF."
            )
        if not (contrato.nombre_vendedor_documentos() or "").strip():
            raise ValueError("Falta el asesor de ventas en el contrato; no se puede regenerar el PDF.")
        return _pdf_recibo_comision_vendedor_bytes(
            doc=doc, contrato=contrato, monto=monto
        )

    if doc.tipo == DocumentoTipo.RECIBO_COMISION_ARRENDAMIENTO:
        inmueble = doc.inmueble
        if inmueble is None:
            raise ValueError("Este recibo no tiene inmueble; no se puede regenerar el PDF.")
        monto = doc.monto_comision_usd
        if monto is None or monto <= Decimal("0"):
            raise ValueError(
                "No hay monto de comisión guardado; no se puede regenerar este PDF."
            )
        if not (doc.recibo_beneficiario_nombre or "").strip():
            raise ValueError("Falta el beneficiario del recibo; no se puede regenerar el PDF.")
        html = render_to_string(
            "docs/recibo_comision_alquiler.html",
            _contexto_recibo_comision_alquiler(doc=doc, inmueble=inmueble, monto=monto),
        )
        return _html_to_pdf_bytes(html)

    raise ValueError(
        f"El tipo «{doc.get_tipo_display()}» no admite regeneración automática del PDF."
    )


def regenerar_pdf_y_persistir(doc: DocumentoEmitido) -> bytes:
    """Regenera bytes del PDF y vuelve a guardarlos en `pdf_file` cuando el almacenamiento lo permite."""
    pdf_bytes = regenerar_pdf_documento(doc)
    doc.hash_sha256 = _sha256(pdf_bytes)
    try:
        doc.pdf_file.save(f"{doc.numero}.pdf", ContentFile(pdf_bytes), save=False)
        doc.save(update_fields=["hash_sha256", "pdf_file"])
    except Exception:
        logger.exception(
            "PDF regenerado en memoria pero no se pudo volver a guardarlo (documento %s).",
            doc.numero,
        )
    return pdf_bytes


def generar_pdf_desde_plantilla(*, template_name: str, context: dict) -> bytes:
    """Renderiza una plantilla HTML y la convierte a PDF (WeasyPrint o xhtml2pdf)."""
    html = render_to_string(template_name, context)
    return _html_to_pdf_bytes(html)

