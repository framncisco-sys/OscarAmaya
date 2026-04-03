"""Crea la base POSTGRES_DB si no existe (usa settings de Django / .env)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from django.conf import settings

import psycopg
from psycopg import sql

c = settings.DATABASES["default"]
conn = psycopg.connect(
    dbname="postgres",
    user=c["USER"],
    password=c["PASSWORD"],
    host=c["HOST"],
    port=c["PORT"],
)
conn.autocommit = True
name = c["NAME"]
owner = c["USER"]
with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    if cur.fetchone():
        print(f"La base '{name}' ya existe.")
    else:
        cur.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                sql.Identifier(name),
                sql.Identifier(owner),
            )
        )
        print(f"Base creada: {name}")
conn.close()
