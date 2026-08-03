#!/usr/bin/env bash
# Solo crea un respaldo (sin desplegar). Útil para cron diario.
# Uso: bash /var/www/OscarAmaya/deploy/solo_backup.sh
set -euo pipefail

APP_DIR=/var/www/OscarAmaya
BACKUP_ROOT=/var/backups/oscaramaya
KEEP=14

ts=$(date +%Y%m%d_%H%M%S)
DEST="${BACKUP_ROOT}/${ts}"
mkdir -p "${DEST}"

set -a
# shellcheck disable=SC1091
source <(grep -E '^(POSTGRES_)' "${APP_DIR}/.env" | sed 's/\r$//')
set +a

export PGPASSWORD="${POSTGRES_PASSWORD:-}"
pg_dump -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" \
  -U "${POSTGRES_USER:-paredes}" -d "${POSTGRES_DB:-paredes_bienes}" \
  --no-owner --no-acl -F c -f "${DEST}/db.dump"

[[ -d "${APP_DIR}/media" ]] && tar -C "${APP_DIR}" -czf "${DEST}/media.tar.gz" media
cp -a "${APP_DIR}/.env" "${DEST}/env.backup"
cd "${APP_DIR}"
git rev-parse HEAD > "${DEST}/git_commit.txt" 2>/dev/null || true
date -u +"backup_utc=%Y-%m-%dT%H:%M:%SZ" > "${DEST}/meta.txt"

mapfile -t ALL_BACKUPS < <(ls -1dt "${BACKUP_ROOT}"/20* 2>/dev/null || true)
if (( ${#ALL_BACKUPS[@]} > KEEP )); then
  for old in "${ALL_BACKUPS[@]:KEEP}"; do
    rm -rf "${old}"
  done
fi

echo "Backup OK: ${DEST} ($(du -sh "${DEST}" | awk '{print $1}'))"
