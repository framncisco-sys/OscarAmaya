# Generated manually for third reference rows on FormatoAceptacion.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0017_formato_aceptacion"),
    ]

    operations = [
        migrations.AddField(
            model_name="formatoaceptacion",
            name="ref_com_nombre_3",
            field=models.CharField(
                blank=True,
                max_length=200,
                verbose_name="Ref. comercial — empresa 3",
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="ref_com_obs_3",
            field=models.CharField(
                blank=True,
                max_length=200,
                verbose_name="Ref. comercial — observación 3",
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="ref_com_tel_3",
            field=models.CharField(
                blank=True,
                max_length=40,
                verbose_name="Ref. comercial — tel. 3",
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="ref_per_nombre_3",
            field=models.CharField(
                blank=True,
                max_length=200,
                verbose_name="Ref. personal — nombre 3",
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="ref_per_obs_3",
            field=models.CharField(
                blank=True,
                max_length=200,
                verbose_name="Ref. personal — observación 3",
            ),
        ),
        migrations.AddField(
            model_name="formatoaceptacion",
            name="ref_per_tel_3",
            field=models.CharField(
                blank=True,
                max_length=40,
                verbose_name="Ref. personal — tel. 3",
            ),
        ),
    ]
