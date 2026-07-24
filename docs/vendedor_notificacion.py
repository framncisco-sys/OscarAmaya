"""Correo al vendedor: cierre de venta (etapa comercial) y recibo de comisión generado."""

from __future__ import annotations

import logging
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.template.loader import render_to_string

from inmobiliaria.models import Contrato

from .models import DocumentoEmitido, DocumentoTipo
from .recibo_notificacion import url_pdf_publica_https
from .recibo_text import format_monto_sv

logger = logging.getLogger(__name__)


def _empresa_notificacion() -> str:
    n = (getattr(settings, "RECIBO_NOTIFICACION_EMPRESA_NOMBRE", "") or "").strip()
    return n or "Paredes Desarrollos Inmobiliarios"


def _emails_vendedor_contrato(contrato: Contrato) -> list[str]:
    """Catálogo `Vendedor.email` y, si existe, email del usuario Django vinculado al contrato (sin duplicar)."""
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str | None) -> None:
        e = (raw or "").strip()
        if not e:
            return
        try:
            validate_email(e)
        except ValidationError:
            logger.warning("Email de vendedor omitido (formato inválido): %s", e[:40])
            return
        key = e.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(e)

    if contrato.vendedor_perfil_id:
        vp = contrato.vendedor_perfil
        add(getattr(vp, "email", None))
    if contrato.vendedor_id:
        u = contrato.vendedor
        if u is not None:
            add(getattr(u, "email", None))
    return out


def notificar_vendedor_cierre_venta(contrato_id: int) -> bool:
    """
    Aviso cuando el contrato pasa a etapa «Cierre / venta».
    Destinatarios: email del vendedor en catálogo y/o del usuario vendedor en el contrato.
    """
    if not getattr(settings, "VENDEDOR_NOTIFICAR_CIERRE_EMAIL", True):
        return False
    contrato = (
        Contrato.objects.filter(pk=contrato_id)
        .select_related("cliente", "inmueble", "inmueble__proyecto", "vendedor_perfil", "vendedor")
        .first()
    )
    if not contrato:
        return False
    to = _emails_vendedor_contrato(contrato)
    if not to:
        logger.info(
            "Cierre venta contrato %s: sin email de vendedor (catálogo o usuario); no se envía correo.",
            contrato.numero,
        )
        return False
    ctx = {
        "contrato": contrato,
        "cliente": contrato.cliente,
        "inmueble": contrato.inmueble,
        "empresa_nombre": _empresa_notificacion(),
        "vendedor_nombre": contrato.nombre_vendedor_documentos() or "—",
        "monto_fmt": format_monto_sv(contrato.precio_final),
    }
    body = render_to_string("docs/email_vendedor_cierre_venta.txt", ctx).strip()
    subject = getattr(
        settings,
        "VENDEDOR_CIERRE_EMAIL_ASUNTO",
        "Etapa Cierre / venta — contrato registrado",
    )
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=to,
    )
    try:
        msg.send(fail_silently=False)
        logger.info(
            "Cierre venta: correo enviado a vendedor(es) del contrato %s → %s",
            contrato.numero,
            to,
        )
        return True
    except Exception as exc:
        logger.exception("Cierre venta contrato %s: fallo correo vendedor: %s", contrato.numero, exc)
        return False


def enviar_recibo_comision_vendedor_correo(doc_id: int) -> bool:
    """Adjunta el PDF del recibo de comisión y envía a los mismos destinatarios que el cierre."""
    if not getattr(settings, "VENDEDOR_NOTIFICAR_RECIBO_COMISION_EMAIL", True):
        return False
    doc = (
        DocumentoEmitido.objects.filter(pk=doc_id, tipo=DocumentoTipo.RECIBO_COMISION_VENDEDOR)
        .select_related(
            "contrato",
            "contrato__cliente",
            "contrato__inmueble",
            "contrato__inmueble__proyecto",
            "contrato__vendedor_perfil",
            "contrato__vendedor",
        )
        .first()
    )
    if not doc or not doc.contrato_id:
        return False
    contrato = doc.contrato
    to = _emails_vendedor_contrato(contrato)
    if not to:
        logger.info(
            "Recibo comisión %s: sin email de vendedor; no se envía correo.",
            doc.numero,
        )
        return False
    if not doc.pdf_file or not doc.pdf_file.name:
        return False
    try:
        doc.pdf_file.open("rb")
        pdf_bytes = doc.pdf_file.read()
    except OSError as exc:
        logger.warning("Recibo comisión %s: no se pudo leer PDF: %s", doc.numero, exc)
        return False
    finally:
        try:
            doc.pdf_file.close()
        except Exception:
            pass

    monto = doc.monto_comision_usd or contrato.monto_comision_efectivo()
    ctx = {
        "doc": doc,
        "contrato": contrato,
        "cliente": contrato.cliente,
        "inmueble": contrato.inmueble,
        "empresa_nombre": _empresa_notificacion(),
        "vendedor_nombre": contrato.nombre_vendedor_documentos() or "—",
        "monto_fmt": format_monto_sv(monto) if monto is not None else "—",
        "pdf_url": url_pdf_publica_https(doc),
    }
    body = render_to_string("docs/email_vendedor_recibo_comision.txt", ctx).strip()
    subject = getattr(
        settings,
        "VENDEDOR_RECIBO_COMISION_EMAIL_ASUNTO",
        "Recibo de comisión (PDF adjunto)",
    )
    nombre_archivo = f"recibo_comision_{doc.numero.replace('/', '-')}.pdf"
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
        to=to,
    )
    msg.attach(nombre_archivo, pdf_bytes, "application/pdf")
    try:
        msg.send(fail_silently=False)
        logger.info("Recibo comisión %s: correo a vendedor → %s", doc.numero, to)
        return True
    except Exception as exc:
        logger.exception("Recibo comisión %s: fallo correo vendedor: %s", doc.numero, exc)
        return False
