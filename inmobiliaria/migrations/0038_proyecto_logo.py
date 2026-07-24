# Generated manually for proyecto logo + plano labels

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0037_recargo_administrativo"),
    ]

    operations = [
        migrations.AddField(
            model_name="proyecto",
            name="logo",
            field=models.ImageField(
                blank=True,
                help_text="Logo del residencial/lotificación (PNG o JPG). Se usa en recibos y documentos PDF.",
                upload_to="proyectos/logos/%Y/%m/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["png", "jpg", "jpeg", "webp"],
                        message="Use PNG, JPG o WEBP.",
                    )
                ],
                verbose_name="Logo del proyecto",
            ),
        ),
        migrations.AlterField(
            model_name="proyecto",
            name="plano_maestro",
            field=models.FileField(
                blank=True,
                help_text="Plano completo de la lotificación (imagen o PDF). Los polígonos se marcan sobre este archivo.",
                upload_to="proyectos/planos/%Y/%m/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["pdf", "png", "jpg", "jpeg", "webp"],
                        message="Use PDF, JPG, PNG o WEBP.",
                    )
                ],
                verbose_name="Plano del proyecto",
            ),
        ),
    ]
