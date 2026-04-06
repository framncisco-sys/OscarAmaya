# release: fase Heroku-style (si su PaaS la ejecuta).
release: python manage.py migrate --noinput
# Web: migrar y luego Gunicorn. En DigitalOcean App Platform el Run Command del servicio
# DEBE ser exactamente esto (no solo "gunicorn ..."), si no fallan rutas nuevas (p. ej. en_alquiler).
web: bash scripts/run_web.sh
