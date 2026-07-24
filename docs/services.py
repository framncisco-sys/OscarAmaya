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


def _pdf_static_base_url() -> str:
    """Directorio de estáticos donde están los logos (cualquiera sirve como ancla)."""
    for fname in (
        "logo_paredes_bienes_raices.png",
        "logo_paredes_desarrollos.png",
        "logo_valle_alegre.png",
    ):
        found = finders.find(fname)
        if found:
            return Path(found).parent.as_uri() + "/"
    return Path(settings.BASE_DIR).as_uri() + "/"


def _proyecto_logo_src_para_pdf(proyecto) -> str:
    """
    Logo del proyecto subido (ruta absoluta) o fallback estático Valle Alegre.
    WeasyPrint/xhtml2pdf resuelven file: o nombre en STATIC.
    """
    if proyecto is not None:
        logo = getattr(proyecto, "logo", None)
        if logo and getattr(logo, "name", None):
            try:
                path = Path(logo.path)
                if path.is_file():
                    return path.as_uri()
            except (ValueError, OSError):
                pass
    return "logo_valle_alegre.png"


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contexto_recibo_ingreso(*, doc, pago) -> dict:
    from inmobiliaria.pago_desglose import desglose_para_recibo
    from inmobiliaria.signals import aplicar_cuotas_programadas_del_pago

    # Asegura cuotas vinculadas antes del PDF (excedente = abono a capital en el mismo recibo).
    if pago.concepto == pago.Concepto.CUOTA and pago.puede_emitir_recibo_cliente:
        if not pago.cuotas_aplicadas.exists():
            aplicar_cuotas_programadas_del_pago(pago)
            pago.refresh_from_db()

    proyecto = pago.contrato.inmueble.proyecto
    desglose = desglose_para_recibo(pago)
    lineas_fmt = [
        (etiqueta, format_monto_sv(monto))
        for etiqueta, monto in desglose.lineas
    ]
    return {
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
        "desglose": desglose,
        "desglose_lineas_fmt": lineas_fmt,
        "monto_abono_capital_fmt": (
            format_monto_sv(desglose.monto_abono_capital)
            if desglose.monto_abono_capital > 0
            else ""
        ),
        "proyecto_logo_src": _proyecto_logo_src_para_pdf(proyecto),
    }


def emitir_recibo_ingreso(*, pago, emitido_por=None) -> tuple[DocumentoEmitido, ReciboNotificacionInfo]:
    if not pago.puede_emitir_recibo_cliente:
        raise ValueError(
            "El abono (reserva, prima, cuota o abono a capital) debe ser validado por gerencia antes de emitir el recibo."
        )
    numero = _next_correlativo(tipo=DocumentoTipo.RECIBO_INGRESO, cfg=CorrelativoConfig())
    doc = DocumentoEmitido.objects.create(
        tipo=DocumentoTipo.RECIBO_INGRESO,
        numero=numero,
        pago=pago,
        contrato=pago.contrato,
        inmueble=pago.contrato.inmueble if pago.contrato_id else None,
        emitido_por=emitido_por,
    )

    html = render_to_string(
        "docs/recibo_ingreso.html",
        _contexto_recibo_ingreso(doc=doc, pago=pago),
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
            "proyecto_logo_src": _proyecto_logo_src_para_pdf(contrato.inmueble.proyecto),
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


def _contexto_recibo_comision_vendedor(
    *,
    doc: DocumentoEmitido,
    contrato: Contrato,
    monto,
    comision_porcentaje=None,
    concepto: str = "",
) -> dict:
    from decimal import Decimal

    nombre_v = contrato.nombre_vendedor_documentos()
    proyecto = contrato.inmueble.proyecto
    pct = comision_porcentaje
    if pct is None and doc.comision_porcentaje_recibo is not None:
        pct = doc.comision_porcentaje_recibo
    concepto_txt = (concepto or doc.comision_concepto or "").strip()
    if not concepto_txt:
        from .forms import _concepto_comision_default

        concepto_txt = _concepto_comision_default(contrato)
    return {
        "doc": doc,
        "contrato": contrato,
        "cliente": contrato.cliente,
        "proyecto": proyecto,
        "inmueble": contrato.inmueble,
        "vendedor_nombre": nombre_v,
        "monto": monto,
        "monto_fmt": format_monto_sv(monto),
        "monto_letras": monto_usd_letras_es(monto),
        "comision_porcentaje": pct,
        "comision_porcentaje_txt": _pct_txt_comision(pct),
        "comision_concepto": concepto_txt,
        "precio_final_fmt": format_monto_sv(contrato.precio_final),
        "lugar_emision": _lugar_emision_republica(proyecto),
        "razon_social_emisor": _razon_social_negocio_pdf(),
        "emisor_nit": (getattr(settings, "PBR_EMPRESA_NIT", None) or "").strip(),
        "proyecto_logo_src": _proyecto_logo_src_para_pdf(proyecto),
    }


def emitir_recibo_comision_vendedor(
    *,
    contrato: Contrato,
    emitido_por=None,
    monto_comision=None,
    comision_porcentaje=None,
    concepto: str = "",
) -> DocumentoEmitido:
    """PDF de liquidación de comisión al vendedor (diseño distinto al recibo de ingreso del cliente)."""
    from decimal import Decimal

    from inmobiliaria.comision_vendedor import requisitos_comision_venta

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
        monto_comision_usd=monto,
        comision_porcentaje_recibo=comision_porcentaje,
        comision_concepto=(concepto or "").strip(),
    )

    html = render_to_string(
        "docs/recibo_comision_vendedor.html",
        _contexto_recibo_comision_vendedor(
            doc=doc,
            contrato=contrato,
            monto=monto,
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
        "proyecto_logo_src": _proyecto_logo_src_para_pdf(proyecto),
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
        raise ValueError("Indique el nombre del vendedor o asesor beneficiario.")

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
        proyecto = contrato.inmueble.proyecto
        html = render_to_string(
            "docs/recibo_ingreso.html",
            _contexto_recibo_ingreso(doc=doc, pago=pago),
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
                "proyecto_logo_src": _proyecto_logo_src_para_pdf(contrato.inmueble.proyecto),
            },
        )
        return _html_to_pdf_bytes(html)

    if doc.tipo == DocumentoTipo.RECIBO_COMISION_VENDEDOR:
        contrato = doc.contrato
        if contrato is None:
            raise ValueError("Este recibo no tiene contrato; no se puede regenerar el PDF.")
        monto = _monto_comision_documento(doc, contrato)
        if monto is None or monto <= Decimal("0"):
            raise ValueError(
                "No hay monto de comisión guardado en el documento; no se puede regenerar este PDF."
            )
        if not (contrato.nombre_vendedor_documentos() or "").strip():
            raise ValueError("Falta el vendedor en el contrato; no se puede regenerar el PDF.")
        html = render_to_string(
            "docs/recibo_comision_vendedor.html",
            _contexto_recibo_comision_vendedor(doc=doc, contrato=contrato, monto=monto),
        )
        return _html_to_pdf_bytes(html)

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

