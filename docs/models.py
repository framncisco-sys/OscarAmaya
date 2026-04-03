from __future__ import annotations

from django.conf import settings
from django.db import models

from crm.models import HojaVisita, Lead
from inmobiliaria.models import Contrato, Inmueble, Pago, Vendedor


class DocumentoTipo(models.TextChoices):
    PROMESA_VENTA = "PROMESA_VENTA", "Promesa de venta"
    RECIBO_INGRESO = "RECIBO_INGRESO", "Recibo de ingreso"
    RECIBO_COMISION_VENDEDOR = "RECIBO_COMISION_VENDEDOR", "Recibo de comisión (vendedor)"
    HOJA_VISITA = "HOJA_VISITA", "Hoja de visita"


class CorrelativoDocumento(models.Model):
    tipo = models.CharField(max_length=30, choices=DocumentoTipo.choices)
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField(null=True, blank=True)
    ultimo_numero = models.PositiveIntegerField(default=0)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tipo", "anio", "mes")]
        verbose_name = "Correlativo"
        verbose_name_plural = "Correlativos"

    def __str__(self) -> str:
        return f"{self.tipo} {self.anio}-{self.mes or 0:02d} #{self.ultimo_numero}"


class DocumentoEmitido(models.Model):
    tipo = models.CharField(max_length=30, choices=DocumentoTipo.choices, db_index=True)
    numero = models.CharField(max_length=40, db_index=True)

    contrato = models.ForeignKey(Contrato, on_delete=models.SET_NULL, null=True, blank=True)
    pago = models.ForeignKey(Pago, on_delete=models.SET_NULL, null=True, blank=True)
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True)
    hoja_visita = models.ForeignKey(HojaVisita, on_delete=models.SET_NULL, null=True, blank=True)
    inmueble = models.ForeignKey(Inmueble, on_delete=models.SET_NULL, null=True, blank=True)
    vendedor = models.ForeignKey(
        Vendedor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_comision",
        verbose_name="vendedor (comisión)",
    )

    emitido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    emitido_en = models.DateTimeField(auto_now_add=True)

    pdf_file = models.FileField(upload_to="docs/%Y/%m/", blank=True)
    hash_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-emitido_en", "-id"]
        verbose_name = "Documento emitido"
        verbose_name_plural = "Documentos emitidos"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.numero}"
