# Migra la BD en cada arranque del contenedor (evita "relation ... does not exist" si olvidó migrate en DO/Heroku).
# Si usa varias réplicas y nota condiciones de carrera, use un Job PRE_DEPLOY solo con migrate.
web: python manage.py migrate --noinput && gunicorn backend.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120 --access-logfile - --error-logfile -
