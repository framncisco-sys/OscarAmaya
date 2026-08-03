#!/usr/bin/env bash
# Despliegue inicial en DigitalOcean Droplet (Ubuntu 24.04).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

APP_DIR=/var/www/OscarAmaya
REPO=https://github.com/framncisco-sys/OscarAmaya.git
APP_IP=67.205.145.246
DB_NAME=paredes_bienes
DB_USER=paredes
DB_PASS='CAMBIAR_PASSWORD_FUERTE'

echo "=== [1/9] Paquetes del sistema ==="
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  postgresql postgresql-contrib libpq-dev \
  nginx git curl ufw \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
  libgdk-pixbuf-2.0-0 libffi8 shared-mime-info fonts-dejavu-core \
  build-essential pkg-config

echo "=== [2/9] PostgreSQL ==="
systemctl enable --now postgresql
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
fi
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
sudo -u postgres psql -d "${DB_NAME}" -c "GRANT ALL ON SCHEMA public TO ${DB_USER};"

echo "=== [3/9] Clonar / actualizar código ==="
mkdir -p /var/www
if [ -d "${APP_DIR}/.git" ]; then
  cd "${APP_DIR}"
  git fetch origin
  git reset --hard origin/main
else
  rm -rf "${APP_DIR}"
  git clone "${REPO}" "${APP_DIR}"
fi
cd "${APP_DIR}"

echo "=== [4/9] Virtualenv + pip ==="
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "=== [5/9] Archivo .env ==="
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
cat > "${APP_DIR}/.env" << ENV
SECRET_KEY=${SECRET}
DEBUG=False
DJANGO_ALLOWED_HOSTS=${APP_IP},localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://${APP_IP}
PUBLIC_BASE_URL=http://${APP_IP}
DJANGO_SESSION_COOKIE_SECURE=False
DJANGO_CSRF_COOKIE_SECURE=False
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_USE_WHITENOISE=1
DJANGO_SERVE_MEDIA_PUBLIC=1
DJANGO_USE_X_FORWARDED_HOST=True

POSTGRES_DB=${DB_NAME}
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASS}
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

RECIBO_ENVIAR_EMAIL=0
ENV
chmod 600 "${APP_DIR}/.env"

echo "=== [6/9] Migraciones y estáticos ==="
python manage.py migrate --noinput
python manage.py collectstatic --noinput
mkdir -p "${APP_DIR}/media"
chown -R www-data:www-data "${APP_DIR}/media" "${APP_DIR}/staticfiles"
# El código debe ser legible por www-data
chown -R root:www-data "${APP_DIR}"
chmod -R g+rX "${APP_DIR}"
chmod 600 "${APP_DIR}/.env"

echo "=== [7/9] systemd Gunicorn ==="
cat > /etc/systemd/system/oscaramaya.service << 'UNIT'
[Unit]
Description=OscarAmaya Django (Gunicorn)
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/OscarAmaya
Environment="PATH=/var/www/OscarAmaya/.venv/bin"
EnvironmentFile=/var/www/OscarAmaya/.env
ExecStart=/var/www/OscarAmaya/.venv/bin/gunicorn backend.wsgi:application \
  --bind 127.0.0.1:8001 \
  --workers 2 \
  --threads 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable oscaramaya
systemctl restart oscaramaya

echo "=== [8/9] Nginx ==="
cat > /etc/nginx/sites-available/oscaramaya << NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${APP_IP} _;

    client_max_body_size 50M;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        expires 7d;
        access_log off;
    }

    location /media/ {
        alias ${APP_DIR}/media/;
        expires 1d;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX

ln -sfn /etc/nginx/sites-available/oscaramaya /etc/nginx/sites-enabled/oscaramaya
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

echo "=== [9/9] Firewall ==="
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo
echo "=== Estado servicios ==="
systemctl is-active postgresql oscaramaya nginx
curl -s -o /dev/null -w "HTTP local: %{http_code}\n" http://127.0.0.1:8001/ || true
curl -s -o /dev/null -w "HTTP nginx: %{http_code}\n" http://127.0.0.1/ || true
echo "Despliegue base terminado."
