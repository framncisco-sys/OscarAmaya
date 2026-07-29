from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0002_auditlog_json_encoder"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditlog",
            name="marca_slug",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["marca_slug", "created_at"],
                name="audit_audit_marca_s_7a2c1d_idx",
            ),
        ),
    ]
