#!/usr/bin/env bash
# ==============================================================================
#  tools/check_all.sh — ALLE Pruefungen, lokal genau wie in der CI
# ==============================================================================
#  Ein Befehl vor jedem Push. Die CI ruft dieselben Stufen auf — was hier
#  gruen ist, ist dort gruen (bis auf fehlende Werkzeuge, die hier sauber
#  uebersprungen statt rot gemeldet werden).
#
#    bash tools/check_all.sh            alles, was auf diesem Rechner geht
#    bash tools/check_all.sh lint       Syntax, Linting, Wire-Format, Skripte
#    bash tools/check_all.sh python     Selbsttest + Plotter-Vergleiche
#    bash tools/check_all.sh gui        Oberflaeche offscreen + Plotter-Budget
#    bash tools/check_all.sh teensy     Deskriptor auf dem Host + Firmware-Build
#
#  Mehrere Stufen gehen auch: bash tools/check_all.sh lint python
#
#  Was gebraucht wird (fehlt etwas, wird die Stufe uebersprungen):
#    python3, pyflakes                       -> lint
#    numpy, PyQt6 (+ Qt-Systembibliotheken)  -> python (Teile), gui
#    pyqtgraph                               -> gui
#    ShellCheck                              -> lint (Shell-Teil)
#    g++ / clang++                           -> teensy (Deskriptor)
#    pio (PlatformIO)                        -> teensy (Firmware)
# ==============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
PY="${PYTHON:-python3}"

FAILED=()
SKIPPED=()

run() {     # run "Name" befehl...
    local name="$1"; shift
    echo -e "\n\033[1m── ${name}\033[0m"
    if "$@"; then
        echo -e "\033[0;32m   ✔ ${name}\033[0m"
    else
        echo -e "\033[0;31m   ✘ ${name}\033[0m"
        FAILED+=("$name")
    fi
}

skip() { echo -e "\n\033[1;33m── ${1} übersprungen: ${2}\033[0m"; SKIPPED+=("$1"); }
have_py() { "$PY" -c "import $1" >/dev/null 2>&1; }

stage_lint() {
    if have_py pyflakes; then
        run "pyflakes" "$PY" -m pyflakes \
            rpi5_monitor/64Bit_Version/*.py rpi5_monitor/64Bit_Version/bridge/*.py \
            rpi_zero_node/*.py shared/*.py pc_flash_tool/*.py tools/*.py
    else
        skip "pyflakes" "pip install pyflakes"
    fi
    run "Wire-Format Teensy/Node/GUI" "$PY" tools/check_wire_format.py
    run "QML-Zugriffe gegen die Brücken" "$PY" tools/check_qml_bindings.py
    run "bt_flash_protocol: Kopie identisch" \
        cmp -s shared/bt_flash_protocol.py pc_flash_tool/bt_flash_protocol.py
    run "Shell-Syntax (bash -n)" bash -c \
        'for f in $(git ls-files "*.sh"); do bash -n "$f" || exit 1; done'
    if command -v shellcheck >/dev/null; then
        # shellcheck disable=SC2046
        run "shellcheck" shellcheck -S warning $(git ls-files '*.sh')
    else
        skip "shellcheck" "apt install shellcheck"
    fi
    run "Setup/Update/Deploy (Sandbox)" bash tools/update_test.sh
}

stage_python() {
    run "Selbsttest" "$PY" tools/selftest.py
    run "Plotter: Wert-für-Wert-Vergleiche" "$PY" tools/plotter_bench.py --verify
}

stage_gui() {
    if ! have_py PyQt6.QtQuick || ! have_py numpy; then
        skip "Oberfläche" "PyQt6/numpy fehlen (oder Qt-Systembibliotheken)"
        return
    fi
    if ! have_py pyqtgraph; then
        skip "Oberfläche" "pip install pyqtgraph"
        return
    fi
    run "Oberfläche offscreen (jede Qt-Warnung = Fehler)" "$PY" tools/qml_smoketest.py
    # Großzügig gewählt (lokal 3–6 ms): fängt einen Rückfall wie das
    # halbtransparente Gitter (45 ms), nicht das Rauschen eines CI-Rechners.
    run "Plotter-Budget" "$PY" tools/plotter_bench.py --render --budget-ms 25
}

stage_teensy() {
    run "Teensy-Deskriptor auf dem Host" "$PY" tools/desc_json_check.py
    if command -v pio >/dev/null; then
        run "Firmware (PlatformIO)" bash -c 'cd teensy_firmware && pio run -s'
        run "Bibliothek in mehreren Konfigurationen" bash tools/build_teensy_check.sh
    else
        skip "Firmware" "pip install platformio"
    fi
}

STAGES=("$@")
[[ ${#STAGES[@]} -gt 0 ]] || STAGES=(lint python gui teensy)
for s in "${STAGES[@]}"; do
    case "$s" in
        lint|python|gui|teensy) "stage_$s" ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "Unbekannte Stufe: $s (lint, python, gui, teensy)"; exit 2 ;;
    esac
done

echo ""
[[ ${#SKIPPED[@]} -gt 0 ]] && echo -e "\033[1;33mÜbersprungen: ${SKIPPED[*]}\033[0m"
if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo -e "\033[0;31mFEHLGESCHLAGEN: ${FAILED[*]}\033[0m"
    exit 1
fi
echo -e "\033[0;32mAlle Prüfungen bestanden.\033[0m"
