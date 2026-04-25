#!/usr/bin/env bash
set -euo pipefail

DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

echo "[update] Pulling latest code..."
git pull

echo "[update] Rebuilding images..."
$DC -f docker-compose.pi.yml build

echo "[update] Running migrations..."
$DC -f docker-compose.pi.yml run --rm backend python manage.py migrate --noinput

echo "[update] Restarting services (zero-downtime where possible)..."
$DC -f docker-compose.pi.yml up -d --no-deps backend celery_worker celery_beat ingester frontend nginx

echo "[update] ✅ Done."
