import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0022_formato_beneficiario_porcentaje"),
    ]

    operations = [
        migrations.AddField(
            model_name="pago",
            name="formato_aceptacion",
            field=models.ForeignKey(
                blank=True,
                help_text="Opcional: formato guardado desde el cual se tomó la referencia de este pago.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pagos",
                to="inmobiliaria.formatoaceptacion",
                verbose_name="Formato de aceptación",
            ),
        ),
    ]
