# Generated manually

from django.db import migrations


def limpiar_cola_formato_plan(apps, schema_editor):
    FormatoAceptacion = apps.get_model("inmobiliaria", "FormatoAceptacion")
    Contrato = apps.get_model("inmobiliaria", "Contrato")
    FormatoAceptacion.objects.exclude(validacion_gerencia="NO_APLICA").update(
        validacion_gerencia="NO_APLICA",
        validado_gerencia_por=None,
        validado_gerencia_en=None,
        validacion_gerencia_nota="",
    )
    Contrato.objects.exclude(validacion_gerencia="NO_APLICA").update(
        validacion_gerencia="NO_APLICA",
        validado_gerencia_por=None,
        validado_gerencia_en=None,
        validacion_gerencia_nota="",
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0057_contrato_plan_anos_6"),
    ]

    operations = [
        migrations.RunPython(limpiar_cola_formato_plan, noop_reverse),
    ]
