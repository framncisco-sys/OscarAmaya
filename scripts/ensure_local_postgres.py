"""Crea rol y base local de desarrollo si no existen (Windows / Postgres nativo)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg
from psycopg import sql

# Carga .env sin depender de Django (evita conectar a BD inexistente).
try:
    import environ

    env = environ.Env()
    if (ROOT / ".env").is_file():
        environ.Env.read_env(ROOT / ".env", overwrite=True)
except ImportError:
    env = None

DB_NAME = os.environ.get("POSTGRES_DB", "paredes_bienes_dev")
DB_USER = os.environ.get("POSTGRES_USER", "paredes_dev")
DB_PASS = os.environ.get("POSTGRES_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

SUPER_USERS = ("postgres", os.environ.get("POSTGRES_SUPERUSER", "") or "")
SUPER_PASSWORDS = (
    os.environ.get("POSTGRES_SUPERUSER_PASSWORD", ""),
    os.environ.get("PGPASSWORD", ""),
    "postgres",
    "",
)


def _connect_superuser():
    last_err = None
    for user in SUPER_USERS:
        if not user:
            continue
        for pwd in SUPER_PASSWORDS:
            try:
                return psycopg.connect(
                    dbname="postgres",
                    user=user,
                    password=pwd,
                    host=DB_HOST,
                    port=DB_PORT,
                    connect_timeout=5,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
    raise SystemExit(
        f"No se pudo conectar como superusuario a {DB_HOST}:{DB_PORT}. "
        f"Defina POSTGRES_SUPERUSER_PASSWORD o cree manualmente el rol {DB_USER}. "
        f"Último error: {last_err}"
    )


def main() -> None:
    conn = _connect_superuser()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (DB_USER,))
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE USER {} WITH PASSWORD {}").format(
                    sql.Identifier(DB_USER),
                    sql.Literal(DB_PASS),
                )
            )
            print(f"Rol creado: {DB_USER}")
        else:
            print(f"Rol ya existe: {DB_USER}")

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(DB_NAME),
                    sql.Identifier(DB_USER),
                )
            )
            print(f"Base creada: {DB_NAME}")
        else:
            print(f"Base ya existe: {DB_NAME}")

        cur.execute(
            sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                sql.Identifier(DB_NAME),
                sql.Identifier(DB_USER),
            )
        )
    conn.close()
    print("OK: Postgres local listo para migrate.")


if __name__ == "__main__":
    main()
