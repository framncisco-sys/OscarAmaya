#!/usr/bin/env bash
# Arranque en producción (DigitalOcean, Heroku, etc.): migrar BD y luego Gunicorn.
# En App Platform, use como Run Command: bash scripts/run_web.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "[run_web] Aplicando migraciones Django..."
python manage.py migrate --noinput
echo "[run_web] Iniciando Gunicorn..."
exec gunicorn backend.wsgi:application \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 2 \
  --threads 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
