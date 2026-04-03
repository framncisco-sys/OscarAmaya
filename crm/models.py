from django.conf import settings
from django.db import models

from inmobiliaria.models import Inmueble, Poligono, Proyecto


class Lead(models.Model):
    class EstadoEmbudo(models.TextChoices):
        INTERESADO = "INTERESADO", "Interesado"
        CITA_PROGRAMADA = "CITA_PROGRAMADA", "Cita programada"
        RESERVADO = "RESERVADO", "Reservado"
        VENDIDO = "VENDIDO", "Vendido"

    nombre = models.CharField(max_length=160)
    telefono = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    fuente = models.CharField(max_length=120, blank=True)
    estado_embudo = models.CharField(
        max_length=20,
        choices=EstadoEmbudo.choices,
        default=EstadoEmbudo.INTERESADO,
        db_index=True,
    )

    proyecto_interes = models.ForeignKey(
        Proyecto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    poligono_interes = models.ForeignKey(
        Poligono,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    inmueble_interes = models.ForeignKey(
        Inmueble,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )

    asignado_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads_asignados",
    )

    proxima_accion_en = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "id"]
        verbose_name = "Lead"
        verbose_name_plural = "Leads"

    def __str__(self) -> str:
        return f"{self.nombre} ({self.get_estado_embudo_display()})"


class LeadActividad(models.Model):
    class Tipo(models.TextChoices):
        LLAMADA = "LLAMADA", "Llamada"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        EMAIL = "EMAIL", "Correo"
        VISITA = "VISITA", "Visita"
        NOTA = "NOTA", "Nota"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="actividades")
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.NOTA)
    fecha = models.DateTimeField()
    resumen = models.CharField(max_length=240)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_actividades_creadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Actividad"
        verbose_name_plural = "Actividades"

    def __str__(self) -> str:
        return f"{self.lead_id} {self.tipo} {self.fecha:%Y-%m-%d}"


class HojaVisita(models.Model):
    fecha = models.DateTimeField()
    lead = models.ForeignKey(
        Lead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visitas",
    )
    nombre_interesado = models.CharField(max_length=160, blank=True)
    telefono_interesado = models.CharField(max_length=40, blank=True)
    inmueble = models.ForeignKey(
        Inmueble,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visitas",
    )
    resultado = models.CharField(max_length=240, blank=True)
    siguiente_paso = models.CharField(max_length=240, blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hojas_visita_creadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Hoja de visita"
        verbose_name_plural = "Hojas de visita"

    def __str__(self) -> str:
        return f"Visita {self.fecha:%Y-%m-%d} ({self.inmueble_id or 's/lote'})"
