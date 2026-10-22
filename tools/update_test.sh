#!/usr/bin/env bash
# ==============================================================================
#  tools/update_test.sh — Setup-/Update-Weg ohne Raspberry Pi pruefen
# ==============================================================================
#  Fuehrt update.sh fuer beide Rollen (Node, Haupt-Pi) gegen ein temporaeres
#  Verzeichnis aus — ohne root, ohne systemd, ohne Netz. Geprueft wird, was
#  bei einem Update auf keinen Fall schiefgehen darf:
#
#    * der Code landet vollstaendig und uebersetzbar am Ziel
#    * Geraetespezifisches bleibt stehen (Auth-Token, settings.json,
#      runtime_config/, gespeicherte param_defaults.h)
#    * Dienst-Definitionen enthalten die richtige Node-ID
#    * eine alte Installation ohne Rollen-Datei wird erkannt
#    * --rollback holt den vorherigen Stand zurueck
#    * ein kaputter Stand wird gar nicht erst aktiv (automatischer Rueckweg)
#
#  Aufruf: bash tools/update_test.sh       (laeuft auch in der CI)
# ==============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILS=0
CHECKS=0
check() {   # check "Name" <befehl...>
    local name="$1"; shift
    CHECKS=$((CHECKS + 1))
    if "$@" >/dev/null 2>&1; then
        echo "  [ ok ] $name"
    else
        echo "  [FAIL] $name"
        FAILS=$((FAILS + 1))
    fi
}

export PDS_ALLOW_NONROOT=1
export PDS_SYSTEMD_DIR="$WORK/systemd"
export PDS_BIN_DIR="$WORK/bin"
export PDS_AUTOSTART_DIR="$WORK/autostart"
export PDS_CONF="$WORK/etc/pds.conf"

run_update() { bash "$ROOT/update.sh" --no-pull --no-restart "$@" > "$WORK/last.log" 2>&1; }

# ── Node ──────────────────────────────────────────────────────────────────────
echo "== Node =="
NODE_DIR="$WORK/node"
mkdir -p "$NODE_DIR" "$(dirname "$PDS_CONF")"
echo "geheim" > "$NODE_DIR/bt_flash_secret"
printf 'ROLE=node\nNODE_ID=2\nINSTALL_DIR=%q\n' "$NODE_DIR" > "$PDS_CONF"

check "update.sh laeuft durch"            run_update
check "uart_receiver.py installiert"      test -f "$NODE_DIR/uart_receiver.py"
check "status_leds.py daneben"            test -f "$NODE_DIR/status_leds.py"
check "bt_flash_receiver.py installiert"  test -f "$NODE_DIR/rpi_zero_node/bt_flash_receiver.py"
check "Protokoll in shared/ und daneben"  test -f "$NODE_DIR/shared/bt_flash_protocol.py" -a \
                                               -f "$NODE_DIR/rpi_zero_node/bt_flash_protocol.py"
check "Auth-Token unangetastet"           grep -qx geheim "$NODE_DIR/bt_flash_secret"
check "VERSION geschrieben"               test -s "$NODE_DIR/VERSION"
check "Dienst traegt Node-ID 2"           grep -q 'NODE_ID=2' "$PDS_SYSTEMD_DIR/uart-receiver.service"
check "BT-Dienst angelegt"                test -f "$PDS_SYSTEMD_DIR/bt-flash-receiver.service"
check "Sicherung fuer --rollback"         test -d "$NODE_DIR.prev"

echo "alt" > "$NODE_DIR.prev/VERSION"
check "--rollback laeuft durch"           bash "$ROOT/update.sh" --rollback --no-restart
check "--rollback holt alten Stand"       grep -qx alt "$NODE_DIR/VERSION"

# Alte Installation (vor der Rollen-Datei): an der Dienst-Unit erkennen
rm -f "$PDS_CONF"
check "Altinstallation wird erkannt"      run_update
check "Rollen-Datei nachgetragen"         grep -q '^ROLE=node' "$PDS_CONF"
check "Node-ID aus der alten Unit"        grep -q '^NODE_ID=2' "$PDS_CONF"

# Kaputter Stand: darf nicht aktiv werden
BROKEN="$WORK/broken_repo"
mkdir -p "$BROKEN"
cp -r "$ROOT/update.sh" "$ROOT/scripts" "$ROOT/rpi_zero_node" "$ROOT/shared" "$BROKEN/"
echo "def kaputt(:" >> "$BROKEN/rpi_zero_node/uart_receiver.py"
before="$(md5sum < "$NODE_DIR/uart_receiver.py")"
CHECKS=$((CHECKS + 1))
if bash "$BROKEN/update.sh" --no-pull --no-restart > "$WORK/last.log" 2>&1; then
    echo "  [FAIL] Syntaxfehler wird abgewiesen"; FAILS=$((FAILS + 1))
else
    echo "  [ ok ] Syntaxfehler wird abgewiesen"
fi
check "... und der alte Stand bleibt aktiv" test "$before" = "$(md5sum < "$NODE_DIR/uart_receiver.py")"

# ── deploy.sh (ssh nachgebaut: entpackt lokal in ein Test-Home) ────────────
echo "== deploy.sh =="
FAKEBIN="$WORK/fakebin"
mkdir -p "$FAKEBIN" "$WORK/remote_home"
cat > "$FAKEBIN/ssh" << 'FAKE'
#!/usr/bin/env bash
# Optionen und Ziel ueberspringen, den Rest lokal ausfuehren — "sudo" faellt
# weg, HOME zeigt auf das Test-Home.
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) shift 2 ;;
        -t) shift ;;
        *)  echo "$1" >> "$FAKE_SSH_LOG"; shift; break ;;
    esac
done
cmd="${*//sudo bash/bash}"
HOME="$FAKE_HOME" exec bash -c "$cmd"
FAKE
chmod +x "$FAKEBIN/ssh"
export FAKE_HOME="$WORK/remote_home" FAKE_SSH_LOG="$WORK/ssh_targets"
printf 'ROLE=node\nNODE_ID=1\nINSTALL_DIR=%q\n' "$NODE_DIR" > "$PDS_CONF"
rm -rf "$NODE_DIR.prev"
check "deploy.sh node1 laeuft durch" \
      env PATH="$FAKEBIN:$PATH" PDS_SSH_USER=tester bash "$ROOT/deploy.sh" --no-restart node1
check "Kurzname node1 -> tester@debug-node-1.local" \
      grep -qx "tester@debug-node-1.local" "$WORK/ssh_targets"
check "Stand liegt auf dem Ziel unter ~/pds_deploy" \
      test -f "$WORK/remote_home/pds_deploy/update.sh"
check "VERSION mitgeschickt"         test -s "$WORK/remote_home/pds_deploy/VERSION"
check "keine settings.json mitgeschickt" \
      test ! -e "$WORK/remote_home/pds_deploy/rpi5_monitor/64Bit_Version/settings.json"
check "Ziel hat den Stand installiert" \
      grep -q 'NODE_ID=1' "$PDS_SYSTEMD_DIR/uart-receiver.service"
check "installierte Version = mitgeschickte" \
      cmp -s "$WORK/remote_home/pds_deploy/VERSION" "$NODE_DIR/VERSION"
CHECKS=$((CHECKS + 1))
if env PATH="$FAKEBIN:$PATH" bash "$ROOT/deploy.sh" --gibtsnicht >/dev/null 2>&1; then
    echo "  [FAIL] unbekannte Option wird abgewiesen"; FAILS=$((FAILS + 1))
else
    echo "  [ ok ] unbekannte Option wird abgewiesen"
fi

# ── Haupt-Pi ──────────────────────────────────────────────────────────────────
echo "== Haupt-Pi =="
MON_DIR="$WORK/monitor"
mkdir -p "$MON_DIR/runtime_config/node1"
echo '{"mein": "profil"}' > "$MON_DIR/settings.json"
echo '{"x": 1}'           > "$MON_DIR/runtime_config/node1/param_config.json"
echo "// meine Defaults"  > "$MON_DIR/param_defaults.h"
printf 'ROLE=monitor\nINSTALL_DIR=%q\nSERVICE_USER=%q\n' "$MON_DIR" "$(id -un)" > "$PDS_CONF"
# pip nicht anfassen: Stempel der aktuellen requirements.txt vorab setzen
sha256sum "$ROOT/requirements.txt" | cut -d' ' -f1 > "$(dirname "$PDS_CONF")/requirements.sha256"

check "update.sh laeuft durch"            run_update
check "main_qml.py installiert"           test -f "$MON_DIR/main_qml.py"
check "qml/ und bridge/ installiert"      test -f "$MON_DIR/qml/Main.qml" -a -f "$MON_DIR/bridge/app_bridge.py"
check "settings.json unangetastet"        grep -q profil "$MON_DIR/settings.json"
check "runtime_config/ unangetastet"      test -f "$MON_DIR/runtime_config/node1/param_config.json"
check "param_defaults.h unangetastet"     grep -q "meine Defaults" "$MON_DIR/param_defaults.h"
check "Launcher geschrieben"              test -x "$PDS_BIN_DIR/power-debug-monitor"
check "Launcher zeigt aufs Ziel"          grep -q "INSTALL_DIR=\"$MON_DIR\"" "$PDS_BIN_DIR/power-debug-monitor"
check "Autostart geschrieben"             test -f "$PDS_AUTOSTART_DIR/power-debug-monitor.desktop"
check "pip uebersprungen (unveraendert)"  grep -q "pip wird übersprungen" "$WORK/last.log"
check "--status zeigt die Rolle"          bash -c "bash '$ROOT/update.sh' --status | grep -q monitor"

echo ""
if [[ $FAILS -eq 0 ]]; then
    echo "Alle $CHECKS Pruefungen bestanden."
else
    echo "$FAILS von $CHECKS Pruefungen FEHLGESCHLAGEN — letzte Ausgabe:"
    cat "$WORK/last.log"
    exit 1
fi
