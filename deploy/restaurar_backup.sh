#!/usr/bin/env bash
# Restaura un respaldo creado por update_con_backup.sh
# Uso:
#   bash /var/www/OscarAmaya/deploy/restaurar_backup.sh /var/backups/oscaramaya/20260803_041500
#   bash /var/www/OscarAmaya/deploy/restaurar_backup.sh latest
set -euo pipefail

APP_DIR=/var/www/OscarAmaya
BACKUP_ROOT=/var/backups/oscaramaya
SERVICE=oscaramaya
TARGET="${1:-}"

if [[ -z "${TARGET}" ]]; then
  echo "Uso: $0 /var/backups/oscaramaya/YYYYMMDD_HHMMSS"
  echo "     $0 latest"
  echo
  echo "Respaldos disponibles:"
  ls -1dt "${BACKUP_ROOT}"/20* 2>/dev/null || echo "(ninguno)"
  exit 1
fi

if [[ "${TARGET}" == "latest" ]]; then
  TARGET=$(ls -1dt "${BACKUP_ROOT}"/20* 2>/dev/null | head -1)
fi

if [[ ! -d "${TARGET}" ]]; then
  echo "No existe el respaldo: ${TARGET}"
  exit 1
fi

echo "========================================"
echo " RESTAURAR desde: ${TARGET}"
echo "========================================"
echo "Esto reemplazará la base de datos y media/ actuales."
read -r -p "Escriba RESTAURAR para continuar: " CONFIRM
if [[ "${CONFIRM}" != "RESTAURAR" ]]; then
  echo "Cancelado."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source <(grep -E '^(POSTGRES_)' "${APP_DIR}/.env" | sed 's/\r$//')
set +a

DB_NAME="${POSTGRES_DB:-paredes_bienes}"
DB_USER="${POSTGRES_USER:-paredes}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

systemctl stop "${SERVICE}" || true

echo "[1/4] Restaurar PostgreSQL..."
# Limpia y restaura dump custom (-F c)
pg_restore -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
  --clean --if-exists --no-owner --no-acl "${TARGET}/db.dump"

echo "[2/4] Restaurar media/..."
if [[ -f "${TARGET}/media.tar.gz" ]]; then
  rm -rf "${APP_DIR}/media"
  tar -C "${APP_DIR}" -xzf "${TARGET}/media.tar.gz"
  chown -R www-data:www-data "${APP_DIR}/media"
fi

echo "[3/4] Restaurar .env (opcional del backup)..."
if [[ -f "${TARGET}/env.backup" ]]; then
  cp -a "${TARGET}/env.backup" "${APP_DIR}/.env"
  chown root:www-data "${APP_DIR}/.env"
  chmod 600 "${APP_DIR}/.env"
fi

echo "[4/4] Arrancar servicio..."
systemctl start "${SERVICE}"
sleep 2
systemctl is-active "${SERVICE}"
echo "Restauración terminada."
if [[ -f "${TARGET}/git_commit.txt" ]]; then
  echo "Commit del respaldo: $(cat "${TARGET}/git_commit.txt")"
  echo "Si también quiere volver el código a ese commit:"
  echo "  cd ${APP_DIR} && git checkout \$(cat ${TARGET}/git_commit.txt) && systemctl restart ${SERVICE}"
fi
