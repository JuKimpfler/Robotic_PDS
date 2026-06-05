#!/usr/bin/env bash
# deploy.sh — Build (if needed) and deploy spi_bridge to Raspberry Pi
#
# Usage:
#   ./deploy.sh [--rpi-host pi@192.168.137.x] [--skip-build]
#
# Prerequisites:
#   - Cross-compiler installed: aarch64-linux-gnu-gcc
#   - cmake, make available
#   - SSH access to the RPi

set -euo pipefail

RPI_HOST="${1:-pi@192.168.137.2}"
SKIP_BUILD=0

for arg in "$@"; do
  case $arg in
    --rpi-host=*) RPI_HOST="${arg#*=}" ;;
    --skip-build) SKIP_BUILD=1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
BINARY="$BUILD_DIR/spi_bridge"

# ── Build ──────────────────────────────────────────────────────────────────────
if [ "$SKIP_BUILD" -eq 0 ]; then
    echo "==> Configuring cross-build..."
    cmake -DCMAKE_TOOLCHAIN_FILE="$SCRIPT_DIR/toolchain-aarch64.cmake" \
          -DCMAKE_BUILD_TYPE=Release \
          -S "$SCRIPT_DIR" \
          -B "$BUILD_DIR"

    echo "==> Building..."
    cmake --build "$BUILD_DIR" -j"$(nproc)"
fi

if [ ! -f "$BINARY" ]; then
    echo "ERROR: Binary not found: $BINARY"
    exit 1
fi

echo "==> Deploying to $RPI_HOST ..."
scp "$BINARY" "$RPI_HOST":/tmp/spi_bridge_new

# Atomically replace binary and restart service
ssh "$RPI_HOST" 'bash -s' << 'REMOTE'
    sudo mv /tmp/spi_bridge_new /usr/local/bin/spi_bridge
    sudo chmod +x /usr/local/bin/spi_bridge
    sudo systemctl restart spi-bridge.service || true
    echo "==> Deployed. Service status:"
    sudo systemctl status spi-bridge.service --no-pager | head -20
REMOTE

echo "==> Done."
