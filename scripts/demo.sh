#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$(mktemp -p /tmp watchdog_demo_XXXXXX.db)"

cleanup() {
  rm -f "$DB_PATH" "$DB_PATH-shm" "$DB_PATH-wal"
}
trap cleanup EXIT

echo "== WatchDog demo =="
echo "DB: $DB_PATH"
echo

export WATCHDOG_DB_PATH="$DB_PATH"
export WATCHDOG_TARGETS_FILE="$ROOT_DIR/watchdog/config/targets_minimal.yaml"
export WATCHDOG_SLACK_WEBHOOK_URL=""

echo "-> validate-config"
python "$ROOT_DIR/watchdog/main.py" --validate-config
echo

echo "-> monitor (5s)"
timeout 5s python "$ROOT_DIR/watchdog/main.py" --monitor || true
echo

echo "-> report (last 1h)"
python "$ROOT_DIR/watchdog/main.py" --report --last-hours 1 || true
echo

echo "-> status (last 5m)"
python "$ROOT_DIR/watchdog/main.py" --status --last-minutes 5 || true
echo

echo "-> metrics-server (brief)"
PORT="9100"
python "$ROOT_DIR/watchdog/main.py" --metrics-server --metrics-host 127.0.0.1 --metrics-port "$PORT" >/tmp/watchdog_demo_metrics.log 2>&1 &
PID=$!
sleep 1
curl -s "http://127.0.0.1:${PORT}/health" || true
echo
curl -s "http://127.0.0.1:${PORT}/metrics" | head -20 || true
kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true
echo

echo "Demo complete."
