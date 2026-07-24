from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0034_asesoralquiler"),
        ("docs", "0005_recibo_comision_arrendamiento"),
    ]

    operations = [
        migrations.AlterField(
            model_name="documentoemitido",
            name="vendedor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documentos_comision",
                to="inmobiliaria.vendedor",
                verbose_name="vendedor (comisión venta)",
            ),
        ),
        migrations.AddField(
            model_name="documentoemitido",
            name="asesor_alquiler",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="recibos_comision",
                to="inmobiliaria.asesoralquiler",
                verbose_name="asesor (comisión alquiler)",
            ),
        ),
    ]
