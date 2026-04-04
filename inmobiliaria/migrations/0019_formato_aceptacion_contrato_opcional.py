# Formato de aceptación: contrato opcional (independiente del flujo de contratos).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0018_formato_aceptacion_refs_tercera_fila"),
    ]

    operations = [
        migrations.AlterField(
            model_name="formatoaceptacion",
            name="contrato",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="formatos_aceptacion",
                to="inmobiliaria.contrato",
                verbose_name="Contrato (opcional)",
            ),
        ),
        migrations.AddConstraint(
            model_name="formatoaceptacion",
            constraint=models.UniqueConstraint(
                condition=models.Q(contrato__isnull=False),
                fields=("contrato",),
                name="formato_aceptacion_contrato_id_uniq_when_set",
            ),
        ),
    ]
