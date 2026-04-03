from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inmobiliaria", "0010_inmueble_geometria_json"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contrato",
            name="precio_final",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Precio total acordado en esta operación (financiado, efectivo u otra condición).",
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
            ),
        ),
        migrations.AddField(
            model_name="contrato",
            name="descuento_efectivo_monto",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Monto de descuento aplicado (ej. pago en efectivo). Opcional; puede ser cualquier valor.",
                max_digits=14,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Descuento por efectivo u otra condición",
            ),
        ),
        migrations.AddField(
            model_name="contrato",
            name="precio_lista_referencia",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Precio de lista del lote al momento de la venta (referencia; puede ser cualquier valor acordado internamente).",
                max_digits=14,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Precio de lista (referencia)",
            ),
        ),
    ]
