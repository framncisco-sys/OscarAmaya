from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("docs", "0002_vendedor_modulo_comision"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentoemitido",
            name="comision_concepto",
            field=models.TextField(
                blank=True,
                help_text="Concepto o detalle impreso en el recibo de comisión al vendedor.",
            ),
        ),
        migrations.AddField(
            model_name="documentoemitido",
            name="comision_porcentaje_recibo",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Porcentaje mostrado en el recibo de comisión, si aplica.",
                max_digits=6,
                null=True,
                verbose_name="Porcentaje comisión (recibo)",
            ),
        ),
        migrations.AddField(
            model_name="documentoemitido",
            name="monto_comision_usd",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Comisión liquidada en el recibo al vendedor (snapshot al emitir).",
                max_digits=14,
                null=True,
                verbose_name="Monto comisión (USD)",
            ),
        ),
    ]
