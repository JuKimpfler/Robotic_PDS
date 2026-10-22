# shellcheck shell=bash
# ==============================================================================
#  scripts/pds_common.sh — gemeinsame Installationsschritte
# ==============================================================================
#  Wird von setup_rpi5.sh, rpi_zero_node/setup_node.sh und update.sh
#  eingebunden (source). Hier steht genau das, was beim ERSTEN Einrichten
#  und bei JEDEM Update gleich ablaufen muss: Code an seinen Platz kopieren,
#  Launcher/Dienste schreiben, Version vermerken. Vorher stand das nur in den
#  Setup-Skripten — ein Update hiess deshalb "Setup komplett neu laufen
#  lassen", mit apt, Rueckfragen und Eingriffen in die Bootkonfiguration.
#
#  Alles ist idempotent: zweimal hintereinander aufgerufen aendert sich
#  nichts. Pfade lassen sich fuer Tests umbiegen (PDS_CONF, PDS_SYSTEMD_DIR,
#  PDS_BIN_DIR, PDS_AUTOSTART_DIR) — die CI installiert damit in ein
#  temporaeres Verzeichnis, ohne root und ohne systemd.
# ==============================================================================

PDS_CONF="${PDS_CONF:-/etc/pds/pds.conf}"
PDS_SYSTEMD_DIR="${PDS_SYSTEMD_DIR:-/etc/systemd/system}"
PDS_BIN_DIR="${PDS_BIN_DIR:-/usr/local/bin}"
PDS_AUTOSTART_DIR="${PDS_AUTOSTART_DIR:-/etc/xdg/autostart}"

PDS_MONITOR_DEFAULT_DIR="/opt/power_debug_monitor"
PDS_NODE_DEFAULT_DIR="/opt/power_debug_node"

# Ausgabe — nur, falls das einbindende Skript keine eigene mitbringt.
declare -F info >/dev/null || info() { echo -e "\033[0;36m[INFO]\033[0m  $*"; }
declare -F ok   >/dev/null || ok()   { echo -e "\033[0;32m[OK]\033[0m    $*"; }
declare -F warn >/dev/null || warn() { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
declare -F err  >/dev/null || err()  { echo -e "\033[0;31m[ERR]\033[0m   $*" >&2; }

# ── Version des Quellstands ───────────────────────────────────────────────────
#  "v2.10-3-gabc1234 (2026-10-22)" aus git, sonst die VERSION-Datei, die
#  deploy.sh mitschickt (dort gibt es kein .git), sonst "unbekannt".
pds_version_of() {
    local repo="$1" v=""
    if command -v git >/dev/null && git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
        v="$(git -C "$repo" describe --always --dirty --tags 2>/dev/null) ($(git -C "$repo" log -1 --format=%cs 2>/dev/null))"
    elif [[ -f "$repo/VERSION" ]]; then
        v="$(head -n1 "$repo/VERSION")"
    fi
    echo "${v:-unbekannt}"
}

# ── Rollen-Datei /etc/pds/pds.conf ────────────────────────────────────────────
#  Merkt sich, WAS auf diesem Geraet installiert ist. update.sh braucht damit
#  keine einzige Angabe mehr.
pds_conf_write() {   # pds_conf_write ROLE=node NODE_ID=1 INSTALL_DIR=... ...
    mkdir -p "$(dirname "$PDS_CONF")"
    {
        echo "# Power Debug System — von setup/update geschrieben, nicht von Hand noetig"
        local kv
        for kv in "$@"; do
            printf '%s=%q\n' "${kv%%=*}" "${kv#*=}"
        done
    } > "$PDS_CONF"
}

pds_conf_load() {
    [[ -f "$PDS_CONF" ]] || return 1
    # shellcheck disable=SC1090
    source "$PDS_CONF"
}

# Installationen, die VOR der Rollen-Datei eingerichtet wurden, werden an
# ihren Spuren erkannt — ein altes Geraet laesst sich damit ohne neues
# Setup auf den Update-Weg bringen.
# Setzt ROLE, NODE_ID, INSTALL_DIR, SERVICE_USER fuer das aufrufende Skript.
# shellcheck disable=SC2034
pds_detect_legacy() {
    local svc="$PDS_SYSTEMD_DIR/uart-receiver.service"
    if [[ -f "$svc" ]]; then
        ROLE=node
        NODE_ID="$(sed -n 's/^Environment="NODE_ID=\([0-9]\)".*/\1/p' "$svc" | head -n1)"
        INSTALL_DIR="$(sed -n 's|^WorkingDirectory=||p' "$svc" | head -n1)"
        INSTALL_DIR="${INSTALL_DIR:-$PDS_NODE_DEFAULT_DIR}"
        return 0
    fi
    local launcher="$PDS_BIN_DIR/power-debug-monitor"
    if [[ -f "$launcher" ]]; then
        ROLE=monitor
        INSTALL_DIR="$(sed -n 's/^INSTALL_DIR="\(.*\)"$/\1/p' "$launcher" | head -n1)"
        INSTALL_DIR="${INSTALL_DIR:-$PDS_MONITOR_DEFAULT_DIR}"
        SERVICE_USER="$(stat -c %U "$INSTALL_DIR" 2>/dev/null || echo pi)"
        return 0
    fi
    return 1
}

# ── Sicherung / Rueckweg ──────────────────────────────────────────────────────
pds_backup() {      # Stand vor dem Update nach <dir>.prev
    local dir="$1"
    [[ -d "$dir" ]] || return 0
    rm -rf "${dir}.prev"
    cp -a "$dir" "${dir}.prev"
}

pds_restore() {     # <dir>.prev zurueckholen
    local dir="$1"
    [[ -d "${dir}.prev" ]] || { err "Keine Sicherung ${dir}.prev vorhanden."; return 1; }
    rm -rf "$dir"
    mv "${dir}.prev" "$dir"
}

# Jede installierte Python-Datei einmal uebersetzen. Ein Syntaxfehler
# faellt so VOR dem Neustart auf und nicht erst, wenn der Dienst nicht
# mehr hochkommt.
pds_verify_python() {
    # -f: immer neu uebersetzen. Ohne -f vergleicht compileall nur die
    # Aenderungszeit (Sekunden) mit dem vorhandenen Bytecode — ein Update in
    # derselben Sekunde galt dann als "schon geprueft", auch mit Syntaxfehler.
    python3 -m compileall -q -f "$1" >/dev/null
}

# ══════════════════════════════════════════════════════════════════════════════
#  Haupt-Pi (Monitor-GUI)
# ══════════════════════════════════════════════════════════════════════════════

# Code kopieren. Geraetespezifisches bleibt IMMER stehen: settings.json und
# die Profile, runtime_config/, controller_config.json, und param_defaults.h,
# sobald es im Ziel schon eine gibt (die GUI schreibt sie mit "Als Default
# speichern").
pds_install_monitor_files() {   # SRC_DIR DEST_DIR USER VERSION
    local src="$1" dest="$2" user="$3" version="$4"
    mkdir -p "$dest"
    local excludes=(--exclude=__pycache__ --exclude=starter.bat
                    --exclude=runtime_config --exclude=settings.json
                    --exclude='settings.*.json' --exclude=controller_config.json
                    --exclude='*.json.tmp' --exclude=VERSION)
    [[ -f "$dest/param_defaults.h" ]] && excludes+=(--exclude=./param_defaults.h)
    tar -C "$src" "${excludes[@]}" -cf - . | tar -C "$dest" -xf -
    echo "$version" > "$dest/VERSION"
    [[ -n "$user" ]] && chown -R "$user:$user" "$dest" 2>/dev/null || true
}

pds_write_monitor_launcher() {  # INSTALL_DIR
    local dir="$1"
    mkdir -p "$PDS_BIN_DIR"
    cat > "$PDS_BIN_DIR/power-debug-monitor" << LAUNCHER
#!/usr/bin/env bash
# Power Debug Monitor — Launcher (geschrieben von setup_rpi5.sh / update.sh)

# Beim Autostart kurz auf den Display-Server warten; update.sh startet die
# GUI mit PDS_NO_WAIT=1 neu, dort laeuft die Sitzung laengst.
[[ -n "\${PDS_NO_WAIT:-}" ]] || sleep 3

# Display-Erkennung: X11 vs. Wayland. Nur auf "xcb" bettet der Plotter sein
# Widget nativ ein; unter Wayland rastert er in ein Bild. Siehe
# README_QML.md, Abschnitt "Der Plotter: nativ oder als Bild".
if [[ -n "\${WAYLAND_DISPLAY:-}" ]]; then
    export QT_QPA_PLATFORM="wayland;xcb"
else
    export DISPLAY="\${DISPLAY:-:0}"
    export QT_QPA_PLATFORM="xcb"
fi

# Qt-Logging reduzieren (unterdrückt egl/xcb-Warnungen auf RPi)
export QT_LOGGING_RULES="qt.qpa.*=false;qt.network.*=false"

INSTALL_DIR="${dir}"
cd "\$INSTALL_DIR" || exit 1
exec python3 main_qml.py "\$@"
LAUNCHER
    chmod +x "$PDS_BIN_DIR/power-debug-monitor"
}

pds_write_monitor_autostart() {
    mkdir -p "$PDS_AUTOSTART_DIR"
    cat > "$PDS_AUTOSTART_DIR/power-debug-monitor.desktop" << 'DESKTOP'
[Desktop Entry]
Type=Application
Version=1.0
Name=Power Debug Monitor
GenericName=RoboCup Power Debugger
Comment=Wireless Telemetry & Firmware Flash System
Exec=/usr/local/bin/power-debug-monitor
Terminal=false
Categories=Utility;Science;
Keywords=debug;telemetry;robocup;
X-GNOME-Autostart-enabled=true
X-LXSession-Autostart-enabled=true
DESKTOP
}

# requirements.txt nur dann durch pip schicken, wenn sie sich seit dem
# letzten Lauf geaendert hat — sonst kostet jedes Update eine Minute pip
# und scheitert ohne Internet.
pds_monitor_requirements() {    # REQ_FILE
    local req="$1" stamp
    stamp="$(dirname "$PDS_CONF")/requirements.sha256"
    [[ -f "$req" ]] || return 0
    local now old=""
    now="$(sha256sum "$req" | cut -d' ' -f1)"
    [[ -f "$stamp" ]] && old="$(cat "$stamp")"
    if [[ "$now" == "$old" ]]; then
        info "requirements.txt unverändert — pip wird übersprungen."
        return 0
    fi
    local flags=()
    pip3 install --help 2>/dev/null | grep -q -- "--break-system-packages" \
        && flags+=(--break-system-packages)
    if pip3 install "${flags[@]}" -r "$req"; then
        mkdir -p "$(dirname "$stamp")"
        echo "$now" > "$stamp"
        ok "Python-Pakete aktualisiert."
    else
        warn "pip-Installation fehlgeschlagen (kein Internet?) — beim nächsten Update erneut."
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Node (Pi Zero 2 W)
# ══════════════════════════════════════════════════════════════════════════════

# Layout auf dem Node (so erwarten es die Dienste):
#   $dest/uart_receiver.py, $dest/status_leds.py
#   $dest/rpi_zero_node/bt_flash_receiver.py + bt_flash_protocol.py
#   $dest/shared/bt_flash_protocol.py
#   $dest/bt_flash_secret   (bleibt bei jedem Update unangetastet)
pds_install_node_files() {      # REPO_DIR DEST_DIR VERSION
    local repo="$1" dest="$2" version="$3"
    local node="$repo/rpi_zero_node" shared="$repo/shared"
    [[ -f "$node/uart_receiver.py" ]] || { err "uart_receiver.py fehlt in $node"; return 1; }
    mkdir -p "$dest/rpi_zero_node" "$dest/shared"
    touch "$dest/rpi_zero_node/__init__.py"
    install -m 0755 "$node/uart_receiver.py" "$dest/uart_receiver.py"
    [[ -f "$node/status_leds.py" ]] && install -m 0755 "$node/status_leds.py" "$dest/status_leds.py"
    if [[ -f "$node/bt_flash_receiver.py" ]]; then
        install -m 0755 "$node/bt_flash_receiver.py" "$dest/rpi_zero_node/bt_flash_receiver.py"
    fi
    if [[ -f "$shared/bt_flash_protocol.py" ]]; then
        install -m 0644 "$shared/bt_flash_protocol.py" "$dest/shared/bt_flash_protocol.py"
        install -m 0644 "$shared/bt_flash_protocol.py" "$dest/rpi_zero_node/bt_flash_protocol.py"
    fi
    echo "$version" > "$dest/VERSION"
}

# Dienste schreiben. Gibt 0 zurueck, wenn sich an einer Unit etwas
# geaendert hat (dann ist daemon-reload noetig).
pds_write_node_services() {     # NODE_ID DEST_DIR [BT_CHANNEL]
    local nid="$1" dest="$2" chan="${3:-4}" changed=1 tmp
    mkdir -p "$PDS_SYSTEMD_DIR"

    # Hinweise zu den Optionen:
    #   * Restart=always — auch nach einem sauberen Beenden wieder anlaufen.
    #   * StartLimit* gehoeren in [Unit]; in [Service] ignoriert systemd sie.
    #   * RestartSec=2s: der Node ist der einzige Weg zur Telemetrie.
    tmp="$(mktemp)"
    cat > "$tmp" << UNIT
[Unit]
Description=Power Debug UART Receiver (Node ${nid}) — RPi Zero 2 W
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60s
StartLimitBurst=10

[Service]
Type=simple
User=root
WorkingDirectory=${dest}
Environment="NODE_ID=${nid}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 ${dest}/uart_receiver.py
Restart=always
RestartSec=2s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=uart-receiver

[Install]
WantedBy=multi-user.target
UNIT
    _pds_place_unit "$tmp" uart-receiver.service && changed=0

    # Bluetooth-Flash: laeuft als root, damit es ohne udev-Regeln an
    # /dev/ttyACM* (Bootloader-Trigger) und den HalfKay-Bootloader kommt.
    if [[ -f "$dest/rpi_zero_node/bt_flash_receiver.py" ]]; then
        tmp="$(mktemp)"
        cat > "$tmp" << UNIT
[Unit]
Description=Power Debug Bluetooth Flash Receiver (Node ${nid}) — RPi Zero 2 W
After=bluetooth.target bluetooth.service dbus.service
Wants=bluetooth.target
Requires=dbus.service
StartLimitIntervalSec=60s
StartLimitBurst=5

[Service]
Type=simple
User=root
WorkingDirectory=${dest}/rpi_zero_node
Environment="NODE_ID=${nid}"
Environment="INSTALL_DIR=${dest}"
Environment="BT_FLASH_CHANNEL=${chan}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 ${dest}/rpi_zero_node/bt_flash_receiver.py
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bt-flash-receiver

[Install]
WantedBy=multi-user.target
UNIT
        _pds_place_unit "$tmp" bt-flash-receiver.service && changed=0
    fi
    return $changed
}

_pds_place_unit() {             # TMPFILE NAME -> 0 = geaendert
    local tmp="$1" target="$PDS_SYSTEMD_DIR/$2"
    if [[ -f "$target" ]] && cmp -s "$tmp" "$target"; then
        rm -f "$tmp"
        return 1
    fi
    install -m 0644 "$tmp" "$target"
    rm -f "$tmp"
    return 0
}
