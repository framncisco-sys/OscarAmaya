#!/usr/bin/env bash
# Actualiza la app en el Droplet haciendo respaldo ANTES de cada deploy.
# Uso en el servidor:
#   bash /var/www/OscarAmaya/deploy/update_con_backup.sh
#   bash /var/www/OscarAmaya/deploy/update_con_backup.sh --keep 15
set -euo pipefail

APP_DIR=/var/www/OscarAmaya
BACKUP_ROOT=/var/backups/oscaramaya
KEEP=10
BRANCH=main
SERVICE=oscaramaya

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP="${2:-10}"; shift 2 ;;
    --branch) BRANCH="${2:-main}"; shift 2 ;;
    *) echo "Opción desconocida: $1"; exit 1 ;;
  esac
done

ts=$(date +%Y%m%d_%H%M%S)
DEST="${BACKUP_ROOT}/${ts}"
mkdir -p "${DEST}"
mkdir -p "${BACKUP_ROOT}"

echo "========================================"
echo " Respaldo pre-deploy: ${DEST}"
echo "========================================"

# Cargar credenciales DB desde .env (sin imprimir secretos)
set -a
# shellcheck disable=SC1091
source <(grep -E '^(POSTGRES_|SECRET_KEY=)' "${APP_DIR}/.env" | sed 's/\r$//')
set +a

DB_NAME="${POSTGRES_DB:-paredes_bienes}"
DB_USER="${POSTGRES_USER:-paredes}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

echo "[1/6] Dump PostgreSQL (${DB_NAME})..."
pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
  --no-owner --no-acl -F c -f "${DEST}/db.dump"

echo "[2/6] Copia media/ ..."
if [[ -d "${APP_DIR}/media" ]]; then
  tar -C "${APP_DIR}" -czf "${DEST}/media.tar.gz" media
else
  echo "(sin carpeta media)"
fi

echo "[3/6] Copia .env y commit actual..."
cp -a "${APP_DIR}/.env" "${DEST}/env.backup"
cd "${APP_DIR}"
git rev-parse HEAD > "${DEST}/git_commit.txt" || echo "unknown" > "${DEST}/git_commit.txt"
git status -sb > "${DEST}/git_status.txt" || true
date -u +"backup_utc=%Y-%m-%dT%H:%M:%SZ" > "${DEST}/meta.txt"
echo "keep_policy=${KEEP}" >> "${DEST}/meta.txt"

# Checksum rápido
sha256sum "${DEST}/db.dump" > "${DEST}/checksums.txt" 2>/dev/null || true
[[ -f "${DEST}/media.tar.gz" ]] && sha256sum "${DEST}/media.tar.gz" >> "${DEST}/checksums.txt"

echo "[4/6] Rotación: conservar últimos ${KEEP} respaldos..."
mapfile -t ALL_BACKUPS < <(ls -1dt "${BACKUP_ROOT}"/20* 2>/dev/null || true)
if (( ${#ALL_BACKUPS[@]} > KEEP )); then
  for old in "${ALL_BACKUPS[@]:KEEP}"; do
    echo "  borrando antiguo: ${old}"
    rm -rf "${old}"
  done
fi

echo
echo "========================================"
echo " Deploy (git pull + migrate + restart)"
echo "========================================"

cd "${APP_DIR}"
echo "[5/6] git fetch/reset ${BRANCH}..."
git fetch origin
git reset --hard "origin/${BRANCH}"

# shellcheck disable=SC1091
source "${APP_DIR}/.venv/bin/activate"
pip install -q -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput

mkdir -p "${APP_DIR}/media"
chown -R www-data:www-data "${APP_DIR}/media" "${APP_DIR}/staticfiles" || true
# Mantener .env solo root:www-data
chown root:www-data "${APP_DIR}/.env"
chmod 600 "${APP_DIR}/.env"

echo "[6/6] Reiniciar ${SERVICE}..."
systemctl restart "${SERVICE}"
sleep 2
systemctl is-active "${SERVICE}"

SIZE=$(du -sh "${DEST}" | awk '{print $1}')
echo
echo "OK. Respaldo: ${DEST} (${SIZE})"
echo "Para restaurar si falla algo:"
echo "  bash ${APP_DIR}/deploy/restaurar_backup.sh ${DEST}"
echo
curl -s -o /dev/null -w "HTTP local: %{http_code}\n" -H "Host: paredesdesarrollosinmobiliarios.com" http://127.0.0.1/login/ || true
