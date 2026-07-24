# Generated manually for Pago validación de abono (gerencia)

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inmobiliaria", "0035_pago_concepto_reserva"),
    ]

    operations = [
        migrations.AddField(
            model_name="pago",
            name="validacion_abono",
            field=models.CharField(
                choices=[
                    ("NO_APLICA", "No requiere validación"),
                    ("PENDIENTE", "Pendiente de gerencia"),
                    ("VALIDADO", "Abono confirmado en cuenta"),
                    ("RECHAZADO", "Rechazado por gerencia"),
                ],
                db_index=True,
                default="NO_APLICA",
                help_text="Reserva, prima y cuotas a plazos: gerencia confirma el depósito en cuenta antes de emitir recibo al cliente.",
                max_length=12,
                verbose_name="Validación de abono",
            ),
        ),
        migrations.AddField(
            model_name="pago",
            name="validacion_nota",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Nota de validación",
            ),
        ),
        migrations.AddField(
            model_name="pago",
            name="validado_en",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Validado en",
            ),
        ),
        migrations.AddField(
            model_name="pago",
            name="validado_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pagos_abono_validados",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Validado por",
            ),
        ),
    ]
