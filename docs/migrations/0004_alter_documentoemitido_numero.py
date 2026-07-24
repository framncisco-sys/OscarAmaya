from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("docs", "0003_documentoemitido_comision_snapshot"),
    ]

    operations = [
        migrations.AlterField(
            model_name="documentoemitido",
            name="numero",
            field=models.CharField(db_index=True, max_length=64),
        ),
    ]
