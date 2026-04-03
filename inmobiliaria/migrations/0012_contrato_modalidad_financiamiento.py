from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inmobiliaria", "0011_contrato_precio_referencia_descuento"),
    ]

    operations = [
        migrations.AddField(
            model_name="contrato",
            name="meses_sin_interes",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Solo si aplica: cantidad de meses al inicio sin cargo de intereses (ej. 12 = un año).",
                null=True,
                verbose_name="Meses sin interés (iniciales)",
            ),
        ),
        migrations.AddField(
            model_name="contrato",
            name="modalidad_financiamiento",
            field=models.CharField(
                choices=[
                    ("TASA_NEGOCIADA", "Financiamiento con tasa anual negociada"),
                    (
                        "PRIMER_ANO_SIN_INTERESES",
                        "Primer año sin intereses (luego aplica tasa acordada)",
                    ),
                    (
                        "MESES_INICIALES_SIN_INTERES",
                        "Meses iniciales sin intereses (indique cantidad abajo)",
                    ),
                    ("SIN_FINANCIAMIENTO", "Sin financiamiento (contado / pago único)"),
                    ("OTRO", "Otra modalidad (detalle en notas)"),
                ],
                db_index=True,
                default="TASA_NEGOCIADA",
                help_text="Cómo se acordó el interés o el período sin intereses.",
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="contrato",
            name="tasa_interes_anual",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="Tasa anual negociada (cuando aplique después del período sin interés o en modalidad estándar). Use 0 si acuerda tasa cero en todo el plazo.",
                max_digits=6,
                null=True,
            ),
        ),
    ]
