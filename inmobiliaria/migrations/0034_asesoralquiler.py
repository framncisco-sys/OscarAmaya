# Generated manually for separate alquiler advisors catalog.

import django.core.validators
from decimal import Decimal
from django.db import migrations, models

import inmobiliaria.validators


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0033_inquilino_alquiler_cliente"),
    ]

    operations = [
        migrations.CreateModel(
            name="AsesorAlquiler",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombres", models.CharField(max_length=120)),
                ("apellidos", models.CharField(max_length=120)),
                (
                    "dui",
                    models.CharField(
                        blank=True,
                        max_length=20,
                        validators=[inmobiliaria.validators.validar_dui_sv],
                    ),
                ),
                ("telefono", models.CharField(blank=True, max_length=40)),
                ("email", models.EmailField(blank=True, max_length=254)),
                (
                    "comision_arrendamiento_pct",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("100"),
                        help_text="Porcentaje de referencia sobre la renta mensual al emitir recibo de comisión de alquiler.",
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0")),
                            django.core.validators.MaxValueValidator(Decimal("100")),
                        ],
                        verbose_name="Comisión sugerida (%)",
                    ),
                ),
                ("activo", models.BooleanField(default=True)),
                ("notas", models.TextField(blank=True)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Asesor de alquiler",
                "verbose_name_plural": "Asesores de alquiler",
                "ordering": ["apellidos", "nombres"],
            },
        ),
    ]
