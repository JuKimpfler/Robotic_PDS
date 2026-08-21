#!/usr/bin/env bash
# ==============================================================================
#  tools/build_teensy_check.sh — schneller Syntax-/Warnungs-Check der
#  Teensy-Bibliothek OHNE vollstaendigen PlatformIO-Build.
#
#  Kompiliert PDS.cpp und main.cpp mit dem ARM-Toolchain, das PlatformIO
#  ohnehin schon installiert hat, in mehreren Konfigurationen:
#    1. Standard (mit channel_config.h)
#    2. ohne channel_config.h        -> testet den __has_include-Fallback
#    3. ACTIVE_CHANNELS=32, PDS_AUTO_CHANNEL_BASE=8, PDS_DESC_REPEAT_MS=0
#
#  Aufruf:  bash tools/build_teensy_check.sh
# ==============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIO_HOME="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}"
TC="$PIO_HOME/packages/toolchain-gccarmnoneeabi-teensy/bin/arm-none-eabi-g++"
CORE="$PIO_HOME/packages/framework-arduinoteensy/cores/teensy4"
[[ -x "$TC" || -x "$TC.exe" ]] || { echo "SKIP: ARM-Toolchain nicht gefunden ($TC)"; exit 0; }
[[ -d "$CORE" ]] || { echo "SKIP: Teensy-Core nicht gefunden ($CORE)"; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BASE=(-c -std=gnu++17 -fno-exceptions -fpermissive -felide-constructors -fno-rtti
      -Wall -O2 -mcpu=cortex-m7 -mfloat-abi=hard -mfpu=fpv5-d16 -mthumb
      -D__IMXRT1062__ -DTEENSYDUINO=159 -DARDUINO=10805 -DARDUINO_TEENSY40
      -DF_CPU=600000000 -DUSB_SERIAL -DLAYOUT_US_ENGLISH -I"$CORE")

fail=0
run() {
    local name="$1"; shift
    if "$TC" "${BASE[@]}" "$@" 2>"$TMP/err"; then
        echo "  OK   $name"
    else
        echo "  FAIL $name"; sed 's/^/       /' "$TMP/err" | head -25; fail=1
    fi
    if [[ -s "$TMP/err" ]]; then
        echo "  WARN $name:"; sed 's/^/       /' "$TMP/err" | head -25
    fi
}

echo "== 1) Standardkonfiguration =="
run "PDS.cpp"  -DACTIVE_CHANNELS=200 -I"$ROOT/teensy_firmware/src" "$ROOT/teensy_firmware/src/PDS.cpp"  -o "$TMP/1a.o"
run "main.cpp" -DACTIVE_CHANNELS=200 -I"$ROOT/teensy_firmware/src" "$ROOT/teensy_firmware/src/main.cpp" -o "$TMP/1b.o"

echo "== 2) ohne channel_config.h (Fallback) =="
mkdir -p "$TMP/nocfg"
cp "$ROOT/teensy_firmware/src/PDS.h" "$ROOT/teensy_firmware/src/PDS.cpp" \
   "$ROOT/teensy_firmware/src/params.h" "$TMP/nocfg/"
run "PDS.cpp (ohne channel_config.h)" -DACTIVE_CHANNELS=200 -I"$TMP/nocfg" "$TMP/nocfg/PDS.cpp" -o "$TMP/2a.o"

echo "== 3) kleine Konfiguration =="
run "PDS.cpp (32 Kanaele)" -DACTIVE_CHANNELS=32 -DPDS_AUTO_CHANNEL_BASE=8 \
    -DPDS_DESC_REPEAT_MS=0 -DPDS_DESC_BUF_BYTES=2048 -DPDS_NAME_CACHE_SIZE=16 \
    -I"$ROOT/teensy_firmware/src" "$ROOT/teensy_firmware/src/PDS.cpp" -o "$TMP/3a.o"

[[ $fail -eq 0 ]] && echo "Alle Teensy-Konfigurationen kompilieren sauber." || echo "FEHLER: siehe oben."
exit $fail
