#!/usr/bin/env bash
set -euo pipefail
pids="$(pgrep -f 'python3 -m ollama_chat.app' 2>/dev/null || true)"
if [ -z "$pids" ]; then
  echo "No Ollama Local Chat server found."
  exit 0
fi
for pid in $pids; do
  if [ "$pid" != "$$" ]; then
    kill "$pid" 2>/dev/null || true
  fi
done
echo "Stopped Ollama Local Chat server."
