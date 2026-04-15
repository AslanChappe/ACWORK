#!/bin/bash
# ============================================================
# Renouvellement automatique des certificats Let's Encrypt
#
# Prérequis VPS : certbot installé (apt install certbot)
#
# Ajouter au crontab (crontab -e) :
#   0 3 */15 * * /home/ubuntu/ACWORK/scripts/renew-ssl.sh >> /var/log/acwork-ssl-renew.log 2>&1
#
# Let's Encrypt expire tous les 90j → ce cron tourne toutes les 15j
# (certbot ne renouvelle que si expiration < 30j → sans effet si pas nécessaire)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking SSL certificate renewal..."

certbot renew --quiet

# Recopier les certs renouvelés vers nginx/ssl/ et redémarrer nginx
# Adapter les chemins selon ton domaine :
# cp /etc/letsencrypt/live/api.ton-domaine.com/fullchain.pem "$PROJECT_DIR/nginx/ssl/api.crt"
# cp /etc/letsencrypt/live/api.ton-domaine.com/privkey.pem   "$PROJECT_DIR/nginx/ssl/api.key"
# cp /etc/letsencrypt/live/n8n.ton-domaine.com/fullchain.pem "$PROJECT_DIR/nginx/ssl/n8n.crt"
# cp /etc/letsencrypt/live/n8n.ton-domaine.com/privkey.pem   "$PROJECT_DIR/nginx/ssl/n8n.key"

cd "$PROJECT_DIR"
docker compose restart nginx

echo "[$(date '+%Y-%m-%d %H:%M:%S')] SSL renewal check complete."
