#!/usr/bin/env bash
# Anclar dominio Cloudflare + certificados Let's Encrypt en el Droplet.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

APP_DIR=/var/www/OscarAmaya
DOMAIN=paredesdesarrollosinmobiliarios.com
WWW=www.paredesdesarrollosinmobiliarios.com
APP_IP=67.205.145.246
EMAIL=admin@${DOMAIN}

echo "=== [1/5] Actualizar .env Django ==="
# Conservar SECRET_KEY y POSTGRES_* existentes
SECRET=$(grep -E '^SECRET_KEY=' "${APP_DIR}/.env" | cut -d= -f2-)
DB_NAME=$(grep -E '^POSTGRES_DB=' "${APP_DIR}/.env" | cut -d= -f2-)
DB_USER=$(grep -E '^POSTGRES_USER=' "${APP_DIR}/.env" | cut -d= -f2-)
DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "${APP_DIR}/.env" | cut -d= -f2-)
DB_HOST=$(grep -E '^POSTGRES_HOST=' "${APP_DIR}/.env" | cut -d= -f2-)
DB_PORT=$(grep -E '^POSTGRES_PORT=' "${APP_DIR}/.env" | cut -d= -f2-)

cat > "${APP_DIR}/.env" << ENV
SECRET_KEY=${SECRET}
DEBUG=False
DJANGO_ALLOWED_HOSTS=${DOMAIN},${WWW},${APP_IP},localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://${DOMAIN},https://${WWW},http://${DOMAIN},http://${WWW}
PUBLIC_BASE_URL=https://${DOMAIN}
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_SECURE_PROXY_SSL_HEADER=True
DJANGO_USE_WHITENOISE=1
DJANGO_SERVE_MEDIA_PUBLIC=1
DJANGO_USE_X_FORWARDED_HOST=True

POSTGRES_DB=${DB_NAME}
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASS}
POSTGRES_HOST=${DB_HOST}
POSTGRES_PORT=${DB_PORT}

RECIBO_ENVIAR_EMAIL=0
ENV
chmod 600 "${APP_DIR}/.env"
chown root:www-data "${APP_DIR}/.env"

echo "=== [2/5] Nginx (HTTP, listo para Certbot) ==="
cat > /etc/nginx/sites-available/oscaramaya << NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${DOMAIN} ${WWW} ${APP_IP};

    client_max_body_size 50M;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

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
        # Cloudflare envía X-Forwarded-Proto: https aunque el origen sea HTTP
        proxy_set_header X-Forwarded-Proto \$http_x_forwarded_proto;
        proxy_read_timeout 120s;
    }
}
NGINX

mkdir -p /var/www/html
ln -sfn /etc/nginx/sites-available/oscaramaya /etc/nginx/sites-enabled/oscaramaya
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
systemctl restart oscaramaya

echo "=== [3/5] Probar host permitido ==="
sleep 2
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${DOMAIN}" http://127.0.0.1/)
echo "HTTP Host ${DOMAIN}: ${CODE}"

echo "=== [4/5] Instalar Certbot y pedir certificado ==="
apt-get update -qq
apt-get install -y -qq certbot python3-certbot-nginx

# Si Cloudflare está en proxy naranja, HTTP-01 suele funcionar vía CF.
# Si falla, el sitio ya quedará bien por HTTPS de Cloudflare + Full/Flexible.
if certbot --nginx \
  -d "${DOMAIN}" -d "${WWW}" \
  --non-interactive --agree-tos -m "${EMAIL}" \
  --redirect; then
  echo "Certificado Let's Encrypt OK"
else
  echo "AVISO: Certbot no pudo emitir certificado en el origen."
  echo "El sitio puede seguir con HTTPS de Cloudflare; configure SSL/TLS = Full o Flexible."
fi

# Asegurar que tras certbot se preserve X-Forwarded-Proto de Cloudflare
if grep -q "proxy_pass http://127.0.0.1:8001" /etc/nginx/sites-available/oscaramaya; then
  if ! grep -q 'X-Forwarded-Proto \$http_x_forwarded_proto' /etc/nginx/sites-available/oscaramaya \
     && ! grep -q 'X-Forwarded-Proto $http_x_forwarded_proto' /etc/nginx/sites-available/oscaramaya; then
    sed -i 's/proxy_set_header X-Forwarded-Proto \$scheme;/proxy_set_header X-Forwarded-Proto \$http_x_forwarded_proto;/' /etc/nginx/sites-available/oscaramaya || true
    sed -i 's/proxy_set_header X-Forwarded-Proto $scheme;/proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;/' /etc/nginx/sites-available/oscaramaya || true
  fi
fi

nginx -t && systemctl reload nginx
systemctl restart oscaramaya

echo "=== [5/5] Verificación final ==="
systemctl is-active oscaramaya nginx
curl -s -o /dev/null -w "local Host dominio: %{http_code}\n" -H "Host: ${DOMAIN}" http://127.0.0.1/
echo "Listo."
