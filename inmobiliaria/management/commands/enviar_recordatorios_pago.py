from __future__ import annotations

from django.core.management.base import BaseCommand

from inmobiliaria.recordatorios_cobro import generar_avisos_cobro


class Command(BaseCommand):
    help = (
        "Aviso de cobro: genera recordatorios N días antes del vencimiento de la cuota "
        "(enlace WhatsApp + correo opcional). Por defecto: 5 días."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=5,
            help="Días antes del vencimiento (default: 5).",
        )
        parser.add_argument(
            "--enviar-email",
            action="store_true",
            help="Envía correo si el cliente tiene email y SMTP está configurado.",
        )

    def handle(self, *args, **options):
        dias = int(options["dias"])
        enviar_email = bool(options["enviar_email"])
        resultado = generar_avisos_cobro(dias=dias, enviar_email=enviar_email)
        self.stdout.write(
            f"Aviso de cobro: fecha_vencimiento_objetivo={resultado['objetivo']} "
            f"cuotas={resultado['cuotas']} "
            f"recordatorios_creados={resultado['creados']} "
            f"emails_enviados={resultado['emails']}"
        )
