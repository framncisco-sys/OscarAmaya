from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0036_pago_validacion_abono"),
    ]

    operations = [
        migrations.AddField(
            model_name="parametromora",
            name="monto_recargo",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "Monto fijo que ustedes definen. Se suma a la cuota del mes siguiente "
                    "si el mes anterior quedó sin pagar después de los días de gracia."
                ),
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                verbose_name="Monto del recargo administrativo",
            ),
        ),
        migrations.AlterField(
            model_name="parametromora",
            name="dias_gracia",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text=(
                    "Días naturales después de la fecha de vencimiento de la cuota "
                    "antes de aplicar el recargo administrativo. Ej.: si vence el 5 y gracia = 5, "
                    "el recargo aplica a partir del 11; en el siguiente mes se cobra cuota + recargo."
                ),
                verbose_name="Días de gracia",
            ),
        ),
        migrations.AlterField(
            model_name="parametromora",
            name="tasa_diaria_porcentaje",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                default=Decimal("0"),
                help_text="Obsoleto: ya no se usa. El cobro es un monto fijo (recargo administrativo).",
                max_digits=8,
            ),
        ),
        migrations.AlterField(
            model_name="pago",
            name="concepto",
            field=models.CharField(
                choices=[
                    ("RESERVA", "Reserva pagada"),
                    ("PRIMA", "Prima / enganche"),
                    ("CUOTA", "Cuota de financiamiento (plazos)"),
                    ("MANTENIMIENTO", "Cuota de mantenimiento"),
                    ("ABONO_CAPITAL", "Abono a capital"),
                    ("MORA", "Recargo administrativo"),
                    ("OTRO", "Otro"),
                ],
                max_length=24,
            ),
        ),
        migrations.AlterModelOptions(
            name="parametromora",
            options={
                "verbose_name": "Parámetro de recargo administrativo",
                "verbose_name_plural": "Parámetros de recargo administrativo",
            },
        ),
    ]
