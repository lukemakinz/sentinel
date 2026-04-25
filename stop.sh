#!/usr/bin/env bash
# Zatrzymuje wszystkie lokalne procesy Sentinela
# Uruchom gdy: zamknąłeś terminal bez Ctrl+C, dev.sh zawiesił się, coś nie wychodzi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
stopped=0

kill_procs() {
    local pattern="$1" label="$2"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}Stopping ${label}...${NC}"
        echo "$pids" | xargs kill 2>/dev/null || true
        stopped=$((stopped + 1))
    fi
}

kill_procs "manage.py runserver"      "Django"
kill_procs "celery -A sentinel worker" "Celery worker"
kill_procs "celery -A sentinel beat"   "Celery beat"
kill_procs "manage.py run_ingester"   "Ingester"
kill_procs "vite"                     "Vite/React"

# Czyszczenie pliku z PIDami (jeśli dev.sh go zostawił)
rm -f .sentinel-pids

if [ "$stopped" -eq 0 ]; then
    echo -e "${GREEN}Nic nie było uruchomione.${NC}"
else
    echo -e "${GREEN}Zatrzymano $stopped serwis(ów). ✓${NC}"
fi
