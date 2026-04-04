# Tercera fila de referencias (idempotente si la columna ya existía en BD).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inmobiliaria", "0017_formato_aceptacion"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE inmobiliaria_formatoaceptacion
              ADD COLUMN IF NOT EXISTS ref_com_nombre_3 varchar(200) NOT NULL DEFAULT '';
            ALTER TABLE inmobiliaria_formatoaceptacion
              ADD COLUMN IF NOT EXISTS ref_com_tel_3 varchar(40) NOT NULL DEFAULT '';
            ALTER TABLE inmobiliaria_formatoaceptacion
              ADD COLUMN IF NOT EXISTS ref_com_obs_3 varchar(200) NOT NULL DEFAULT '';
            ALTER TABLE inmobiliaria_formatoaceptacion
              ADD COLUMN IF NOT EXISTS ref_per_nombre_3 varchar(200) NOT NULL DEFAULT '';
            ALTER TABLE inmobiliaria_formatoaceptacion
              ADD COLUMN IF NOT EXISTS ref_per_tel_3 varchar(40) NOT NULL DEFAULT '';
            ALTER TABLE inmobiliaria_formatoaceptacion
              ADD COLUMN IF NOT EXISTS ref_per_obs_3 varchar(200) NOT NULL DEFAULT '';
            ALTER TABLE inmobiliaria_formatoaceptacion ALTER COLUMN ref_com_nombre_3 DROP DEFAULT;
            ALTER TABLE inmobiliaria_formatoaceptacion ALTER COLUMN ref_com_tel_3 DROP DEFAULT;
            ALTER TABLE inmobiliaria_formatoaceptacion ALTER COLUMN ref_com_obs_3 DROP DEFAULT;
            ALTER TABLE inmobiliaria_formatoaceptacion ALTER COLUMN ref_per_nombre_3 DROP DEFAULT;
            ALTER TABLE inmobiliaria_formatoaceptacion ALTER COLUMN ref_per_tel_3 DROP DEFAULT;
            ALTER TABLE inmobiliaria_formatoaceptacion ALTER COLUMN ref_per_obs_3 DROP DEFAULT;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
