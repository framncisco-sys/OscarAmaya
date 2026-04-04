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

from inmobiliaria.models import Contrato

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


def _pdf_static_base_url() -> str:
    """Directorio de estáticos donde están los logos (cualquiera sirve como ancla)."""
    for fname in ("logo_paredes_desarrollos.png", "logo_valle_alegre.png"):
        found = finders.find(fname)
        if found:
            return Path(found).parent.as_uri() + "/"
    return Path(settings.BASE_DIR).as_uri() + "/"


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def emitir_recibo_ingreso(*, pago, emitido_por=None) -> tuple[DocumentoEmitido, ReciboNotificacionInfo]:
    numero = _next_correlativo(tipo=DocumentoTipo.RECIBO_INGRESO, cfg=CorrelativoConfig())
    doc = DocumentoEmitido.objects.create(
        tipo=DocumentoTipo.RECIBO_INGRESO,
        numero=numero,
        pago=pago,
        contrato=pago.contrato,
        inmueble=pago.contrato.inmueble if pago.contrato_id else None,
        emitido_por=emitido_por,
    )

    proyecto = pago.contrato.inmueble.proyecto
    html = render_to_string(
        "docs/recibo_ingreso.html",
        {
            "doc": doc,
            "pago": pago,
            "contrato": pago.contrato,
            "cliente": pago.contrato.cliente,
            "proyecto": proyecto,
            "lugar_emision": _lugar_emision_republica(proyecto),
            "razon_social_receptor": _razon_social_negocio_pdf(),
            "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
            "monto_fmt": format_monto_sv(pago.monto),
            "monto_letras": monto_usd_letras_es(pago.monto),
        },
    )
    pdf_bytes = _html_to_pdf_bytes(html)
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
        },
    )
    pdf_bytes = _html_to_pdf_bytes(html)
    doc.hash_sha256 = _sha256(pdf_bytes)
    doc.pdf_file.save(f"{numero}.pdf", ContentFile(pdf_bytes), save=False)
    doc.save(update_fields=["hash_sha256", "pdf_file"])
    return doc


def emitir_recibo_comision_vendedor(*, contrato: Contrato, emitido_por=None) -> DocumentoEmitido:
    """PDF tipo recibo corporativo: comisión al vendedor por la venta (lote, casa, etc.)."""
    from decimal import Decimal

    monto = contrato.monto_comision_efectivo()
    if monto is None or monto <= Decimal("0"):
        raise ValueError(
            "No hay monto de comisión: revise precio final y porcentaje o monto fijo en el contrato."
        )

    nombre_v = contrato.nombre_vendedor_documentos()
    if not (nombre_v or "").strip():
        raise ValueError("Indique el vendedor en el contrato (catálogo o nombre).")

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
    )

    proyecto = contrato.inmueble.proyecto
    pct_txt = ""
    if contrato.comision_porcentaje is not None:
        pct_txt = f"{contrato.comision_porcentaje.normalize()} %"

    html = render_to_string(
        "docs/recibo_comision_vendedor.html",
        {
            "doc": doc,
            "contrato": contrato,
            "cliente": contrato.cliente,
            "proyecto": proyecto,
            "inmueble": contrato.inmueble,
            "vendedor_nombre": nombre_v,
            "monto": monto,
            "monto_fmt": format_monto_sv(monto),
            "monto_letras": monto_usd_letras_es(monto),
            "comision_porcentaje": contrato.comision_porcentaje,
            "comision_porcentaje_txt": pct_txt,
            "precio_final_fmt": format_monto_sv(contrato.precio_final),
            "lugar_emision": _lugar_emision_republica(proyecto),
            "razon_social_receptor": _razon_social_negocio_pdf(),
            "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
        },
    )
    pdf_bytes = _html_to_pdf_bytes(html)
    doc.hash_sha256 = _sha256(pdf_bytes)
    doc.pdf_file.save(f"{numero}.pdf", ContentFile(pdf_bytes), save=False)
    doc.save(update_fields=["hash_sha256", "pdf_file"])
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
        proyecto = contrato.inmueble.proyecto
        html = render_to_string(
            "docs/recibo_ingreso.html",
            {
                "doc": doc,
                "pago": pago,
                "contrato": contrato,
                "cliente": contrato.cliente,
                "proyecto": proyecto,
                "lugar_emision": _lugar_emision_republica(proyecto),
                "razon_social_receptor": _razon_social_negocio_pdf(),
                "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
                "monto_fmt": format_monto_sv(pago.monto),
                "monto_letras": monto_usd_letras_es(pago.monto),
            },
        )
        return _html_to_pdf_bytes(html)

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
            },
        )
        return _html_to_pdf_bytes(html)

    if doc.tipo == DocumentoTipo.RECIBO_COMISION_VENDEDOR:
        contrato = doc.contrato
        if contrato is None:
            raise ValueError("Este recibo no tiene contrato; no se puede regenerar el PDF.")
        monto = contrato.monto_comision_efectivo()
        if monto is None or monto <= Decimal("0"):
            raise ValueError(
                "No hay monto de comisión válido en el contrato; no se puede regenerar este PDF."
            )
        nombre_v = contrato.nombre_vendedor_documentos()
        if not (nombre_v or "").strip():
            raise ValueError("Falta el vendedor en el contrato; no se puede regenerar el PDF.")
        proyecto = contrato.inmueble.proyecto
        pct_txt = ""
        if contrato.comision_porcentaje is not None:
            pct_txt = f"{contrato.comision_porcentaje.normalize()} %"
        html = render_to_string(
            "docs/recibo_comision_vendedor.html",
            {
                "doc": doc,
                "contrato": contrato,
                "cliente": contrato.cliente,
                "proyecto": proyecto,
                "inmueble": contrato.inmueble,
                "vendedor_nombre": nombre_v,
                "monto": monto,
                "monto_fmt": format_monto_sv(monto),
                "monto_letras": monto_usd_letras_es(monto),
                "comision_porcentaje": contrato.comision_porcentaje,
                "comision_porcentaje_txt": pct_txt,
                "precio_final_fmt": format_monto_sv(contrato.precio_final),
                "lugar_emision": _lugar_emision_republica(proyecto),
                "razon_social_receptor": _razon_social_negocio_pdf(),
                "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
            },
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

