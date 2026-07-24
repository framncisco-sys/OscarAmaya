# Generated manually for Pago.Concepto.RESERVA

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0034_asesoralquiler"),
    ]

    operations = [
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
                    ("MORA", "Intereses moratorios"),
                    ("OTRO", "Otro"),
                ],
                max_length=24,
            ),
        ),
    ]
