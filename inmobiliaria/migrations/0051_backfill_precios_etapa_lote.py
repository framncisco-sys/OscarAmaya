# Generated manually — copia precio_lista a las 3 etapas si están vacíos.

from django.db import migrations
from django.db.models import Q


def backfill_precios(apps, schema_editor):
    Inmueble = apps.get_model("inmobiliaria", "Inmueble")
    qs = Inmueble.objects.filter(precio_lista__isnull=False).filter(
        Q(precio_preventa__isnull=True)
        | Q(precio_promocional__isnull=True)
        | Q(precio_pos_preventa__isnull=True)
    )
    for inv in qs.iterator():
        pl = inv.precio_lista
        changed = False
        if inv.precio_preventa is None:
            inv.precio_preventa = pl
            changed = True
        if inv.precio_promocional is None:
            inv.precio_promocional = pl
            changed = True
        if inv.precio_pos_preventa is None:
            inv.precio_pos_preventa = pl
            changed = True
        if changed:
            inv.save(
                update_fields=[
                    "precio_preventa",
                    "precio_promocional",
                    "precio_pos_preventa",
                ]
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0050_etapa_venta_precios_lote_formato"),
    ]

    operations = [
        migrations.RunPython(backfill_precios, noop_reverse),
    ]
