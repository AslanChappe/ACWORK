#!/bin/bash
# ============================================================
# Backup automatisé — PostgreSQL + n8n data
#
# Usage      : bash scripts/backup.sh
# Cron VPS   : 0 2 * * * /home/ubuntu/ACWORK/scripts/backup.sh >> /var/log/acwork-backup.log 2>&1
# Rétention  : 7 jours locaux (modifier RETENTION_DAYS)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="/var/backups/acwork"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7

# Charger les variables d'environnement depuis le .env du projet
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$PROJECT_DIR/.env" | grep -v '^$')
    set +a
fi

POSTGRES_USER="${POSTGRES_USER:-admin}"
API_DB_NAME="${API_DB_NAME:-appdb}"
N8N_DB_NAME="${N8N_DB_NAME:-n8n}"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup..."

# ── PostgreSQL appdb ───────────────────────────────────────
echo "  → Dumping PostgreSQL (appdb)..."
docker exec postgres pg_dump \
    -U "$POSTGRES_USER" \
    --clean --if-exists \
    "$API_DB_NAME" \
    | gzip > "$BACKUP_DIR/postgres_appdb_${DATE}.sql.gz"

# ── PostgreSQL n8n ─────────────────────────────────────────
echo "  → Dumping PostgreSQL (n8n)..."
docker exec postgres pg_dump \
    -U "$POSTGRES_USER" \
    --clean --if-exists \
    "$N8N_DB_NAME" \
    | gzip > "$BACKUP_DIR/postgres_n8n_${DATE}.sql.gz"

# ── n8n data volume (workflows, credentials, configs) ──────
echo "  → Backing up n8n data volume..."
docker run --rm \
    -v n8n-stack_n8n_data:/data:ro \
    -v "$BACKUP_DIR":/backup \
    alpine tar czf "/backup/n8n_data_${DATE}.tar.gz" -C /data . 2>/dev/null

# ── Nettoyage des anciens backups ──────────────────────────
echo "  → Removing backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "*.gz" -mtime "+${RETENTION_DAYS}" -delete

# ── Résumé ─────────────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup complete."
echo "  Files in $BACKUP_DIR :"
ls -lh "$BACKUP_DIR" | tail -10
