#!/usr/bin/env bash
# Universal startup script for VPS, Wispbyte, Lucity, Render, Railway, Fly, and Docker
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

export PORT="${PORT:-${SERVER_PORT:-8080}}"

if ! command -v xray >/dev/null 2>&1 && [ ! -x "$APP_DIR/bin/xray" ]; then
    echo "[MX-UI] Xray binary not found; attempting local install to $APP_DIR/bin..."
    if command -v curl >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then
        XRAY_DEST="$APP_DIR/bin" bash "$APP_DIR/deploy/install_xray.sh" || echo "[MX-UI] Warning: Xray auto-install failed, continuing in panel mode."
    fi
fi

exec python3 main.py
