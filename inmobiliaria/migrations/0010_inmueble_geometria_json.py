from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inmobiliaria", "0009_proyecto_plano_maestro"),
    ]

    operations = [
        migrations.AddField(
            model_name="inmueble",
            name="geometria_json",
            field=models.JSONField(
                blank=True,
                help_text="Coordenadas del lote para el mapa interactivo (formato JSON).",
                null=True,
            ),
        ),
    ]
