#!/usr/bin/env bash
# cross_compile_bridge.sh — Cross-compiles spi_bridge for aarch64-linux-gnu.
# Prerequisites: sudo apt install gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/rpi-bridge/build"

echo "Bereite Cross-Compilation vor..."
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "Fuehre CMake mit aarch64-Toolchain-Konfiguration aus..."
cmake -DCMAKE_TOOLCHAIN_FILE="$PROJECT_ROOT/rpi-bridge/toolchain-aarch64.cmake" -DCMAKE_BUILD_TYPE=Release ..

echo "Baue Binaries..."
make -j$(nproc)

echo "Kompilierung erfolgreich beendet!"
echo "Binary liegt unter: $BUILD_DIR/spi_bridge"
