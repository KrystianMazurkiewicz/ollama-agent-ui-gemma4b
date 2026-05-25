#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
mkdir -p "$APP_DIR/data/firefox-profile"

# Avoid accidentally opening an older copy of the app still running on port 8765.
"$APP_DIR/scripts/stop.sh" >/dev/null 2>&1 || true
nohup python3 -m ollama_chat.app > "$APP_DIR/data/server.log" 2>&1 &

for _ in $(seq 1 80); do
  if python3 - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen('http://127.0.0.1:8765/api/config', timeout=0.2).read()
PY
  then
    break
  fi
  sleep 0.1
done

exec firefox --no-remote --profile "$APP_DIR/data/firefox-profile" --new-window 'http://127.0.0.1:8765'
