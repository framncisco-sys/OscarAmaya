"""Comprueba la configuración de correo y envía un mensaje de prueba."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Muestra la configuración de correo actual y envía un correo de prueba. "
        "Uso: python manage.py probar_correo su@correo.com"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "destino",
            nargs="?",
            default="",
            help="Correo que recibirá la prueba (recomendado: el mismo que EMAIL_HOST_USER).",
        )

    def handle(self, *args, **options):
        dest = (options.get("destino") or "").strip()
        host = getattr(settings, "EMAIL_HOST", "") or ""
        user = getattr(settings, "EMAIL_HOST_USER", "") or ""
        pwd = getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""
        backend = getattr(settings, "EMAIL_BACKEND", "")
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")

        self.stdout.write(self.style.NOTICE("--- Configuración actual (sin contraseña) ---"))
        self.stdout.write(f"  EMAIL_BACKEND: {backend}")
        self.stdout.write(f"  BREVO_API_KEY: {'***' if getattr(settings, 'BREVO_API_KEY', '') else '(vacía)'}")
        self.stdout.write(f"  EMAIL_HOST:    {host or '(vacío — no hay SMTP)'}")
        self.stdout.write(f"  EMAIL_PORT:    {getattr(settings, 'EMAIL_PORT', '')}")
        self.stdout.write(f"  USE_TLS/SSL:   {getattr(settings, 'EMAIL_USE_TLS', '')} / {getattr(settings, 'EMAIL_USE_SSL', '')}")
        self.stdout.write(f"  EMAIL_HOST_USER: {user or '(vacío)'}")
        self.stdout.write(f"  Contraseña:    {'***' if pwd else '(vacía)'}")
        self.stdout.write(f"  DEFAULT_FROM_EMAIL: {from_email}")
        self.stdout.write("")

        brevo = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
        if not host.strip() and not brevo:
            self.stderr.write(
                self.style.ERROR(
                    "No hay BREVO_API_KEY ni EMAIL_HOST en el entorno (.env).\n"
                    "Recomendado en DigitalOcean: cree una API key en https://app.brevo.com/ "
                    "(SMTP & API → API keys) y ponga BREVO_API_KEY=... en .env.\n"
                    "Alternativa: EMAIL_HOST + EMAIL_HOST_USER + EMAIL_HOST_PASSWORD (SMTP)."
                )
            )
            raise SystemExit(1)

        if host.strip() and not brevo and (not user or not pwd):
            self.stderr.write(
                self.style.WARNING(
                    "Falta EMAIL_HOST_USER o EMAIL_HOST_PASSWORD. "
                    "El envío casi seguro fallará hasta completarlos."
                )
            )

        if not dest:
            dest = user
        if not dest:
            self.stderr.write(
                self.style.ERROR(
                    "Indique un correo destino: python manage.py probar_correo su@correo.com\n"
                    "O defina EMAIL_HOST_USER en .env para usarlo por defecto."
                )
            )
            raise SystemExit(1)

        self.stdout.write(self.style.NOTICE(f"Enviando prueba a: {dest} ..."))
        try:
            send_mail(
                subject="Paredes Bienes Raíces — Prueba de correo",
                message=(
                    "Si leyó este mensaje, el servidor SMTP y el remitente están configurados correctamente.\n\n"
                    f"Backend: {backend}\n"
                    f"From: {from_email}\n"
                ),
                from_email=from_email,
                recipient_list=[dest],
                fail_silently=False,
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error al enviar: {type(e).__name__}: {e}"))
            self.stderr.write(
                "\nRevise: credenciales, puerto TLS/SSL, que DEFAULT_FROM_EMAIL coincida con la cuenta "
                "si su hosting lo exige, y firewall. Gmail requiere «contraseña de aplicación»."
            )
            raise SystemExit(1) from e

        self.stdout.write(self.style.SUCCESS(f"Listo. Revise la bandeja de entrada (y SPAM) de {dest}."))
