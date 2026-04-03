# Mapa catastral WGS84 (Leaflet + OSM)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0015_vendedor_modulo_comision"),
    ]

    operations = [
        migrations.AddField(
            model_name="inmueble",
            name="geometria_catastral_geojson",
            field=models.JSONField(
                blank=True,
                help_text="GeoJSON Polygon en EPSG:4326 (ej. dibujado sobre OpenStreetMap). Opcional; ver también geometria_json sobre el plano.",
                null=True,
            ),
        ),
    ]
