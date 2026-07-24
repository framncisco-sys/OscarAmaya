from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("docs", "0004_alter_documentoemitido_numero"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentoemitido",
            name="recibo_beneficiario_nombre",
            field=models.CharField(
                blank=True,
                help_text="Nombre del vendedor o asesor en recibos de arrendamiento.",
                max_length=120,
                verbose_name="Beneficiario del recibo",
            ),
        ),
        migrations.AlterField(
            model_name="correlativodocumento",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("PROMESA_VENTA", "Promesa de venta"),
                    ("RECIBO_INGRESO", "Recibo de ingreso"),
                    ("RECIBO_COMISION_VENDEDOR", "Recibo de comisión (vendedor)"),
                    ("RECIBO_COMISION_ARRENDAMIENTO", "Recibo de comisión (arrendamiento)"),
                    ("HOJA_VISITA", "Hoja de visita"),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="documentoemitido",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("PROMESA_VENTA", "Promesa de venta"),
                    ("RECIBO_INGRESO", "Recibo de ingreso"),
                    ("RECIBO_COMISION_VENDEDOR", "Recibo de comisión (vendedor)"),
                    ("RECIBO_COMISION_ARRENDAMIENTO", "Recibo de comisión (arrendamiento)"),
                    ("HOJA_VISITA", "Hoja de visita"),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
