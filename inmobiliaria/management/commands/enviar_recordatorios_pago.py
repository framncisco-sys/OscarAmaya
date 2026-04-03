from __future__ import annotations

import re
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.db import IntegrityError
from django.utils import timezone

from inmobiliaria.models import CuotaProgramada, RecordatorioPago


def _normalizar_telefono_sv(raw: str) -> str:
    # Deja solo dígitos. Para SV, wa.me suele aceptar 503XXXXXXXX.
    digits = re.sub(r"\D+", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("503") and len(digits) >= 11:
        return digits
    if len(digits) == 8:
        return "503" + digits
    return digits


def _mensaje_recordatorio(cuota: CuotaProgramada) -> str:
    c = cuota.contrato
    cli = c.cliente
    return (
        f"Recordatorio: su cuota #{cuota.numero} vence el {cuota.vence_en}.\n"
        f"Contrato: {c.numero}\n"
        f"Cliente: {cli}\n"
        f"Monto: ${cuota.monto}\n"
        f"Gracias."
    )


class Command(BaseCommand):
    help = "Genera recordatorios de pago 3 días antes del vencimiento (email opcional + WhatsApp manual)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=3, help="Días antes del vencimiento.")
        parser.add_argument("--enviar-email", action="store_true", help="Intenta enviar correo si hay email.")

    def handle(self, *args, **options):
        dias = int(options["dias"])
        enviar_email = bool(options["enviar_email"])
        hoy = timezone.localdate()
        objetivo = hoy + timedelta(days=dias)

        cuotas = (
            CuotaProgramada.objects.select_related("contrato", "contrato__cliente")
            .filter(estado=CuotaProgramada.Estado.PENDIENTE, vence_en=objetivo)
            .order_by("id")
        )

        creados = 0
        enviados = 0
        for cuota in cuotas:
            msg = _mensaje_recordatorio(cuota)
            tel = _normalizar_telefono_sv(cuota.contrato.cliente.telefono)
            wa = f"https://wa.me/{tel}?text=" + re.sub(r"\s+", "%20", msg) if tel else ""

            # WhatsApp manual
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

            # Email (opcional)
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
                    rec = None

                if rec:
                    try:
                        send_mail(
                            subject=f"Recordatorio de pago cuota #{cuota.numero}",
                            message=msg,
                            from_email=None,
                            recipient_list=[cuota.contrato.cliente.email],
                            fail_silently=False,
                        )
                        rec.enviado = True
                        rec.enviado_en = timezone.now()
                        rec.save(update_fields=["enviado", "enviado_en"])
                        enviados += 1
                    except Exception as e:
                        self.stderr.write(f"No se pudo enviar email cuota {cuota.id}: {e}")

        self.stdout.write(f"Objetivo={objetivo} cuotas={cuotas.count()} recordatorios_creados={creados} emails_enviados={enviados}")

