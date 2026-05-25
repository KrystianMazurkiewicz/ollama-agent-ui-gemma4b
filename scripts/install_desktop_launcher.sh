#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/ollama-local-chat.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ollama Local Chat
Comment=Local browser interface for Ollama
Exec=$APP_DIR/scripts/launch_firefox_profile.sh
Path=$APP_DIR
Terminal=false
Categories=Utility;Development;
EOF
chmod +x "$DESKTOP_DIR/ollama-local-chat.desktop"
chmod +x "$APP_DIR"/scripts/*.sh
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true
echo "Installed. Open 'Ollama Local Chat' from the Linux Mint menu."
