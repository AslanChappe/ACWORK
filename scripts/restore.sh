#!/bin/bash
# ============================================================
# Restauration depuis un backup
#
# Usage : bash scripts/restore.sh /var/backups/acwork/postgres_appdb_20240101_020000.sql.gz
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -z "${1:-}" ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo ""
    echo "Available backups:"
    ls -lh /var/backups/acwork/*.sql.gz 2>/dev/null || echo "  No backups found in /var/backups/acwork/"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: file not found: $BACKUP_FILE"
    exit 1
fi

# Charger les variables d'env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source <(grep -v '^#' "$PROJECT_DIR/.env" | grep -v '^$')
    set +a
fi

POSTGRES_USER="${POSTGRES_USER:-admin}"

# Détecter le nom de la DB depuis le nom de fichier
if [[ "$BACKUP_FILE" == *"_appdb_"* ]]; then
    DB_NAME="${API_DB_NAME:-appdb}"
elif [[ "$BACKUP_FILE" == *"_n8n_"* ]]; then
    DB_NAME="${N8N_DB_NAME:-n8n}"
else
    echo "Cannot determine target DB from filename. Use appdb or n8n in the filename."
    exit 1
fi

echo "⚠️  This will OVERWRITE the database '$DB_NAME'. Press Ctrl+C to cancel."
echo "   Restoring from: $BACKUP_FILE"
sleep 5

echo "Restoring $DB_NAME..."
gunzip -c "$BACKUP_FILE" | docker exec -i postgres psql -U "$POSTGRES_USER" "$DB_NAME"

echo "Restore complete."
