import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inmobiliaria", "0012_contrato_modalidad_financiamiento"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClienteDocumento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "archivo",
                    models.FileField(
                        upload_to="clientes/documentos/%Y/%m/",
                        validators=[
                            django.core.validators.FileExtensionValidator(
                                allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp", "doc", "docx"],
                                message="Use PDF, imágenes (JPG, PNG, WEBP) o Word (.doc, .docx).",
                            )
                        ],
                    ),
                ),
                ("descripcion", models.CharField(blank=True, max_length=200)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                (
                    "cliente",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documentos",
                        to="inmobiliaria.cliente",
                    ),
                ),
            ],
            options={
                "verbose_name": "Documento de cliente",
                "verbose_name_plural": "Documentos de clientes",
                "ordering": ["-creado_en"],
            },
        ),
    ]
