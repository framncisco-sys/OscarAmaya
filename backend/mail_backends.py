"""Backends de correo para desarrollo."""

import sys
import threading

from django.core.mail.backends.base import BaseEmailBackend


class QuietConsoleEmailBackend(BaseEmailBackend):
    """
    Escribe una sola línea por mensaje (asunto, destinatarios, adjuntos).
    Evita volcar el MIME completo con PDF en base64, que satura la terminal
    al usar el backend de consola estándar de Django.
    """

    def __init__(self, *args, **kwargs):
        self.stream = kwargs.pop("stream", sys.stdout)
        self._lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def write_summary(self, message):
        to = getattr(message, "to", None) or []
        subj = getattr(message, "subject", "") or ""
        atts = getattr(message, "attachments", None) or []
        n = len(atts)
        self.stream.write(f"[EMAIL] To: {to!s} | Subject: {subj!s} | Adjuntos: {n}\n")

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        msg_count = 0
        with self._lock:
            try:
                for message in email_messages:
                    self.write_summary(message)
                    self.stream.flush()
                    msg_count += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return msg_count
