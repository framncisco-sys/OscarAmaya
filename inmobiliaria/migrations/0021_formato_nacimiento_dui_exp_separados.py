# Separa lugar/fecha de nacimiento y lugar/fecha de exp. DUI en campos propios.

from django.db import migrations, models


def copiar_campos_lugar_fecha(apps, schema_editor):
    Formato = apps.get_model("inmobiliaria", "FormatoAceptacion")
    for row in Formato.objects.all():
        legacy_ln = (getattr(row, "lugar_fecha_nacimiento", None) or "")[:200]
        legacy_dui = (getattr(row, "dui_exp_lugar_fecha", None) or "")[:120]
        row.lugar_nacimiento = legacy_ln
        row.dui_exp_lugar = legacy_dui
        row.save(update_fields=["lugar_nacimiento", "dui_exp_lugar"])


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0020_formatoaceptacion_tercera_fila_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="formatoaceptacion",
            name="lugar_nacimiento",
            field=models.CharField(
                blank=True, max_length=200, verbose_name="Lugar de nacimiento"
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="fecha_nacimiento",
            field=models.DateField(
                blank=True, null=True, verbose_name="Fecha de nacimiento"
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="dui_exp_lugar",
            field=models.CharField(
                blank=True, max_length=120, verbose_name="Lugar de exp. DUI"
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="dui_exp_fecha",
            field=models.DateField(
                blank=True, null=True, verbose_name="Fecha de exp. DUI"
            ),
        ),
        migrations.RunPython(copiar_campos_lugar_fecha, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="formatoaceptacion",
            name="lugar_fecha_nacimiento",
        ),
        migrations.RemoveField(
            model_name="formatoaceptacion",
            name="dui_exp_lugar_fecha",
        ),
    ]
