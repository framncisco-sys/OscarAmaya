"""Avisos de cobro N días antes del vencimiento de la cuota."""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote

from django.core.mail import send_mail
from django.db import IntegrityError
from django.utils import timezone

from inmobiliaria.models import CuotaProgramada, RecordatorioPago


def normalizar_telefono_sv(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("503") and len(digits) >= 11:
        return digits
    if len(digits) == 8:
        return "503" + digits
    return digits


def mensaje_aviso_cobro(cuota: CuotaProgramada) -> str:
    from inmobiliaria.recargo_administrativo import resumen_cobro_contrato

    c = cuota.contrato
    cli = c.cliente
    cobro = resumen_cobro_contrato(c)
    lineas = [
        f"Aviso de cobro: su cuota #{cuota.numero} vence el {cuota.vence_en.strftime('%d/%m/%Y')}.",
        f"Contrato: {c.numero}",
        f"Cliente: {cli}",
        f"Monto de la cuota: ${cuota.monto}",
    ]
    if cobro.monto_recargo and cobro.cuota and cobro.cuota.pk == cuota.pk:
        lineas.append(
            f"Recargo administrativo pendiente: ${cobro.monto_recargo} "
            f"({cobro.cantidad_recargos} mes(es) sin pagar tras gracia)."
        )
        lineas.append(f"Total a pagar: ${cobro.monto_total}")
    lineas.append("Le recordamos realizar el pago a tiempo. Gracias.")
    return "\n".join(lineas)


def generar_avisos_cobro(
    *,
    dias: int = 5,
    enviar_email: bool = False,
    hoy: date | None = None,
) -> dict:
    """
    Busca cuotas PENDIENTE que vencen dentro de `dias` y crea recordatorios
    (WhatsApp manual + email opcional). No duplica por (cuota, canal, fecha).
    """
    if dias < 0:
        dias = 0
    base = hoy or timezone.localdate()
    objetivo = base + timedelta(days=dias)

    cuotas = (
        CuotaProgramada.objects.select_related("contrato", "contrato__cliente")
        .filter(estado=CuotaProgramada.Estado.PENDIENTE, vence_en=objetivo)
        .order_by("id")
    )

    creados = 0
    emails = 0
    for cuota in cuotas:
        msg = mensaje_aviso_cobro(cuota)
        tel = normalizar_telefono_sv(cuota.contrato.cliente.telefono or "")
        wa = f"https://wa.me/{tel}?text={quote(msg)}" if tel else ""

        try:
            RecordatorioPago.objects.create(
                cuota=cuota,
                canal=RecordatorioPago.Canal.WHATSAPP_MANUAL,
                programado_para=objetivo,
                mensaje=msg,
                wa_link=wa,
            )
            creados += 1
        except IntegrityError:
            pass

        if enviar_email and cuota.contrato.cliente.email:
            try:
                rec = RecordatorioPago.objects.create(
                    cuota=cuota,
                    canal=RecordatorioPago.Canal.EMAIL,
                    programado_para=objetivo,
                    mensaje=msg,
                )
                creados += 1
            except IntegrityError:
                rec = (
                    RecordatorioPago.objects.filter(
                        cuota=cuota,
                        canal=RecordatorioPago.Canal.EMAIL,
                        programado_para=objetivo,
                    ).first()
                )

            if rec and not rec.enviado:
                try:
                    send_mail(
                        subject=f"Aviso de cobro · cuota #{cuota.numero} · contrato {cuota.contrato.numero}",
                        message=msg,
                        from_email=None,
                        recipient_list=[cuota.contrato.cliente.email],
                        fail_silently=False,
                    )
                    rec.enviado = True
                    rec.enviado_en = timezone.now()
                    rec.save(update_fields=["enviado", "enviado_en"])
                    emails += 1
                except Exception:
                    pass

    return {
        "objetivo": objetivo,
        "cuotas": cuotas.count(),
        "creados": creados,
        "emails": emails,
    }
