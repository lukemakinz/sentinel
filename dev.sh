#!/usr/bin/env bash
# Sentinel — local dev runner
# Usage:  ./dev.sh
# Stop:   Ctrl+C
set -eo pipefail   # -e: exit on error, -o pipefail; NO -u (empty arrays OK)

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; MAGENTA='\033[0;35m'; WHITE='\033[1;37m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV_DIR="$SCRIPT_DIR/env"
LOG_DIR="$SCRIPT_DIR/.dev-logs"
mkdir -p "$LOG_DIR"

declare -a SERVICE_PIDS=()

log()  { echo -e "${WHITE}[sentinel]${NC} $*"; }
ok()   { echo -e "${GREEN}[sentinel]${NC} $*"; }
warn() { echo -e "${YELLOW}[sentinel]${NC} $*"; }

# ── Start service with colored prefix ────────────────────────────────────────
start_service() {
    local svc_name="$1"
    local svc_color="$2"
    local svc_log="$LOG_DIR/${svc_name}.log"
    shift 2

    ( "$@" 2>&1 ) \
        | awk -v n="$svc_name" -v c="$svc_color" -v r="$NC" \
              'BEGIN{ORS=""} {printf c"[%-9s]"r" %s\n", n, $0; fflush()}' \
        | tee -a "$svc_log" &

    local p=$!
    SERVICE_PIDS+=("$p")
    log "Started ${svc_name} (pid ${p})"
}

# ── Cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
    echo ""
    warn "Stopping all services..."
    for pid in "${SERVICE_PIDS[@]:-}"; do
        [ -n "$pid" ] && (kill "$pid" 2>/dev/null || true)
    done
    pkill -f "manage.py runserver"    2>/dev/null || true
    pkill -f "celery -A sentinel"     2>/dev/null || true
    pkill -f "manage.py run_ingester" 2>/dev/null || true
    pkill -f "vite"                   2>/dev/null || true
    ok "Stopped. Logs in: .dev-logs/"
}
trap cleanup EXIT INT TERM

# ── Prerequisites ─────────────────────────────────────────────────────────────
log "Checking prerequisites..."
[ -d "$VENV_DIR" ] || { echo "venv missing → python3 -m venv env && source env/bin/activate && pip install -r backend/requirements.pi.txt"; exit 1; }
[ -d "$FRONTEND_DIR/node_modules" ] || { warn "Installing npm packages..."; cd "$FRONTEND_DIR" && npm install && cd "$SCRIPT_DIR"; }
command -v redis-server >/dev/null || { echo "Redis missing → brew install redis"; exit 1; }

# ── Load .env ─────────────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source <(grep -v '^\s*#' "$SCRIPT_DIR/.env" | grep -v '^\s*$')
    set +a
fi

# Local overrides (not saved to .env)
export REDIS_URL="redis://localhost:6379/0"
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"
export DB_PATH="$BACKEND_DIR/db.sqlite3"
export VITE_API_URL="http://localhost:8000"
export DJANGO_SETTINGS_MODULE="sentinel.settings"
export PYTHONUNBUFFERED=1

ok "DB=$DB_PATH | Redis=localhost:6379"

# ── Redis ─────────────────────────────────────────────────────────────────────
if redis-cli ping >/dev/null 2>&1; then
    ok "Redis running ✓"
else
    log "Starting Redis..."
    redis-server --daemonize yes --loglevel warning
    sleep 1
    redis-cli ping >/dev/null 2>&1 || { echo "Redis failed"; exit 1; }
    ok "Redis started ✓"
fi

# ── Activate venv ─────────────────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"
ok "venv: $(python --version)"

# ── Migrations ────────────────────────────────────────────────────────────────
cd "$BACKEND_DIR"
log "Running migrations..."
python manage.py migrate --noinput 2>&1 | grep -E "Apply|OK|No migration" || true
ok "Migrations done ✓"

# ── Superuser (first run only) ───────────────────────────────────────────────
USER_COUNT=$(python manage.py shell -c \
    "from django.contrib.auth.models import User; print(User.objects.count())" \
    2>/dev/null || echo "0")
if [ "$USER_COUNT" = "0" ]; then
    echo ""
    warn "Tworzę konto admin (pierwsze uruchomienie)..."
    python manage.py shell -c "
from django.contrib.auth.models import User
User.objects.create_superuser('admin', 'admin@sentinel.local', 'sentinel123')
print('✅ Konto stworzone: admin / sentinel123')
" 2>/dev/null
    echo ""
fi

# ── Start services ─────────────────────────────────────────────────────────────
echo ""
log "Starting services..."

start_service "django"    "$GREEN"   python manage.py runserver 8000
sleep 1
start_service "worker"    "$BLUE"    celery -A sentinel worker --loglevel=info --concurrency=2
sleep 1
start_service "beat"      "$MAGENTA" celery -A sentinel beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
sleep 1
start_service "ingester"  "$YELLOW"  python manage.py run_ingester

cd "$FRONTEND_DIR"
start_service "frontend"  "$CYAN"    npm run dev -- --host 0.0.0.0 --port 3000

# ── Ready ──────────────────────────────────────────────────────────────────────
sleep 2
echo ""
echo -e "${GREEN}┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}│  ✅  Sentinel działa lokalnie                            │${NC}"
echo -e "${GREEN}│                                                           │${NC}"
echo -e "${GREEN}│  Dashboard:  ${WHITE}http://localhost:3000${GREEN}                     │${NC}"
echo -e "${GREEN}│  Admin:      ${WHITE}http://localhost:8000/admin/${GREEN}               │${NC}"
echo -e "${GREEN}│                                                           │${NC}"
echo -e "${GREEN}│  Login:      ${WHITE}admin${GREEN}   /   Hasło: ${WHITE}sentinel123${GREEN}          │${NC}"
echo -e "${GREEN}│  (zmień hasło w: /admin → Users → admin → change pass)   │${NC}"
echo -e "${GREEN}│                                                           │${NC}"
echo -e "${GREEN}│  Logi:       .dev-logs/<serwis>.log                      │${NC}"
echo -e "${GREEN}│  Stop:       Ctrl+C                                      │${NC}"
echo -e "${GREEN}└──────────────────────────────────────────────────────────┘${NC}"
echo ""

wait
