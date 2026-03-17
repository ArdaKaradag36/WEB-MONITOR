#!/usr/bin/env bash
set -euo pipefail

# Simple helper script to run WatchDog monitor loop and TUI dashboard
# together on a local machine (non-Docker). Designed to handle tens or
# hundreds of targets without manual juggling of terminals.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WATCHDOG_DIR="${ROOT_DIR}/watchdog"

cd "${WATCHDOG_DIR}"

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
elif [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

echo "[WatchDog] Starting monitor loop in background..."
python main.py --monitor &
MONITOR_PID=$!

cleanup() {
  echo
  echo "[WatchDog] Stopping monitor loop (PID: ${MONITOR_PID})..."
  kill "${MONITOR_PID}" >/dev/null 2>&1 || true
}

trap cleanup INT TERM EXIT

echo "[WatchDog] Launching live dashboard (Ctrl+C to exit)..."
python main.py --monitor-dashboard

