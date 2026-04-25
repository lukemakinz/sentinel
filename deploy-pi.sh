#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
die()  { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── Prerequisites ────────────────────────────────────────────────────────────
command -v docker >/dev/null || die "Docker not installed. Run: curl -fsSL https://get.docker.com | sh"
command -v docker-compose >/dev/null 2>&1 || \
  docker compose version >/dev/null 2>&1   || \
  die "docker compose not available"

# Use 'docker compose' (v2) or 'docker-compose' (v1)
DC="docker compose"
docker compose version >/dev/null 2>&1 || DC="docker-compose"

# ── .env check ───────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  warn ".env not found — creating from .env.example"
  cp .env.example .env
  die "Fill in .env (ANTHROPIC_API_KEY, BINANCE_API_KEY) then re-run: ./deploy-pi.sh"
fi

if grep -q "zmien-na-losowy-klucz" .env; then
  die "DJANGO_SECRET_KEY not set in .env. Generate one: python3 -c \"import secrets; print(secrets.token_hex(32))\""
fi

if grep -q "sk-ant-\.\.\." .env; then
  warn "ANTHROPIC_API_KEY looks like placeholder — AI agents won't work"
fi

# ── Get Pi IP ─────────────────────────────────────────────────────────────────
PI_IP=$(hostname -I | awk '{print $1}')
log "Raspberry Pi local IP: ${PI_IP}"
log "App will be available at: http://${PI_IP}"

# ── Pull base images (ARM64) ─────────────────────────────────────────────────
log "Pulling base images for ARM64..."
$DC -f docker-compose.pi.yml pull redis nginx 2>/dev/null || true

# ── Build ────────────────────────────────────────────────────────────────────
log "Building images (first run takes 5-15 minutes on Pi)..."
$DC -f docker-compose.pi.yml build

# ── Migrate + collect static ─────────────────────────────────────────────────
log "Running database migrations..."
$DC -f docker-compose.pi.yml run --rm backend python manage.py migrate --noinput

log "Collecting static files..."
$DC -f docker-compose.pi.yml run --rm backend python manage.py collectstatic --noinput

# ── Start ─────────────────────────────────────────────────────────────────────
log "Starting all services..."
$DC -f docker-compose.pi.yml up -d

# ── Health check ─────────────────────────────────────────────────────────────
sleep 5
if curl -sf "http://localhost/health" >/dev/null 2>&1; then
  log "✅ Sentinel is running!"
  echo ""
  echo "  Dashboard:  http://${PI_IP}"
  echo "  Admin:      http://${PI_IP}/admin"
  echo "  API:        http://${PI_IP}/api"
  echo ""
  echo "  Logs:       $DC -f docker-compose.pi.yml logs -f"
  echo "  Stop:       $DC -f docker-compose.pi.yml down"
  echo "  Update:     git pull && ./deploy-pi.sh"
else
  warn "Health check failed — checking logs..."
  $DC -f docker-compose.pi.yml logs --tail=20 backend
fi
