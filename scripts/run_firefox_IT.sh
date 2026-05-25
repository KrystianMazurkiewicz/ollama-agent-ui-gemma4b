#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
"$APP_DIR/scripts/stop.sh" >/dev/null 2>&1 || true
nohup python3 -m ollama_chat.app > "$APP_DIR/data/server.log" 2>&1 &
sleep 0.5
exec firefox --no-remote -P IT --new-window 'http://127.0.0.1:8765'
