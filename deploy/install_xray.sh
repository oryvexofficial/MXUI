#!/usr/bin/env bash
# install_xray.sh — Cross-platform Xray Core installer for Linux & macOS
set -euo pipefail

XRAY_VERSION="${XRAY_VERSION:-v25.1.30}"
DEST="${XRAY_DEST:-/usr/local/bin}"
OS="${OS:-$(uname -s)}"
ARCH="$(uname -m)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

case "${OS}-${ARCH}" in
    Linux-x86_64)  ASSET="Xray-linux-64.zip" ;;
    Linux-aarch64) ASSET="Xray-linux-arm64-v8a.zip" ;;
    Linux-armv7*)  ASSET="Xray-linux-arm32-v7a.zip" ;;
    Darwin-arm64)  ASSET="Xray-macos-arm64-v8a.zip" ;;
    Darwin-x86_64) ASSET="Xray-macos-64.zip" ;;
    *) echo "Unsupported platform: ${OS}-${ARCH}"; exit 1 ;;
esac

mkdir -p "$DEST"
URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/${ASSET}"
echo "Downloading ${URL}..."
curl -fsSL -o "$TMP/xray.zip" "$URL"
unzip -o "$TMP/xray.zip" xray -d "$TMP"
install -m 0755 "$TMP/xray" "$DEST/xray"
"$DEST/xray" version
echo "Xray installed at $DEST/xray"
