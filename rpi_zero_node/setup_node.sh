#!/usr/bin/env bash
# ==============================================================================
#  setup_node.sh — Einrichtungsskript für Raspberry Pi Zero 2 W
#  Power Debug System | RoboCup Junior Soccer
#  Zielplattform: RPi Zero 2 W | Pi OS Lite 64-bit (Bookworm / Debian 12)
# ==============================================================================
#
#  AUFRUF:
#    sudo bash setup_node_zero2w.sh 1    → Node 1 einrichten (DHCP via RPi 5 AP)
#    sudo bash setup_node_zero2w.sh 2    → Node 2 einrichten (DHCP via RPi 5 AP)
#
#  WICHTIGER UNTERSCHIED ZUM PI ZERO W:
#    • 64-bit OS (arm64/aarch64) statt 32-bit (armhf/armv6)
#    • python3-rpi.gpio ist deprecated → lgpio wird zusätzlich installiert
#    • status_leds.py nutzt RPi.GPIO → funktioniert weiterhin, lgpio als Fallback
#    • Höhere Baudraten (bis 8 Mbps) zuverlässiger auf BCM2710A1
#    • Quad-Core: Python-Services laufen paralleler ohne GIL-Probleme
#
#  WAS DIESES SKRIPT TUT:
#    1. Systempakete installieren (Python, pyserial, GPIO-Libs, BlueZ/D-Bus, ...)
#    2. UART freischalten (PL011 auf GPIO14/15), Bluetooth auf Mini-UART
#       (dtoverlay=miniuart-bt) — Bluetooth bleibt AKTIV fuer das Wireless-
#       Flash-Feature (Windows-PC -> Bluetooth -> USB -> Teensy 4.0)
#    3. SPI deaktivieren (nicht genutzt)
#    4. WLAN zum RPi 5 konfigurieren (DHCP — IP kommt vom RPi-5-Hotspot)
#    5. Projektdateien installieren (/opt/power_debug_node/), Auth-Token fuer
#       den Bluetooth-Flash-Kanal generieren
#    6. Systemdienste anlegen (uart-receiver, bt-flash-receiver)
#    7. Dienste aktivieren (starten automatisch bei jedem Boot)
#
#  WIRELESS-FLASH-FEATURE (siehe Flash_Implementierung.md im Projekt-Root):
#    Nach Abschluss + reboot gibt dieses Skript MAC-Adresse, Auth-Token und
#    RFCOMM-Kanal aus — diese Werte in
#    pc_setup/pc_flash_tool/bt_targets.json auf dem Windows-PC eintragen.
#
#    Seit der Ergänzung um trigger_bootloader_mode() in bt_flash_receiver.py
#    versetzt der Node den Teensy 4.0 VOR jedem Flash-Vorgang per Software in
#    den HalfKay-Bootloader (Öffnen des USB-CDC-Ports mit Baudrate 134) — der
#    Bootloader-Taster muss dafür in aller Regel NICHT mehr gedrückt werden.
#    Voraussetzungen dafür (pyserial + Root-Rechte für /dev/ttyACM*) werden
#    von diesem Skript bereits mitgebracht — siehe Schritt 1 und 5b unten.
#    Funktioniert nur, wenn die aktuell auf dem Teensy laufende Firmware den
#    USB-Typ "Serial" (oder eine Kombination mit Serial) nutzt; andernfalls
#    bleibt der manuelle Knopfdruck als Fallback nötig (siehe Fehlermeldung
#    von bt_flash_receiver.py / check_teensy_present()).
#
#  WLAN-Zugang:
#    SSID:     RoboDebug          ← muss mit RPi 5 AP übereinstimmen
#    Passwort: robodebug123       ← muss mit RPi 5 AP übereinstimmen
#    IP:       per DHCP (vergeben vom RPi 5 Hotspot)
#
#
#  NACH DEM SKRIPT:
#    → sudo reboot
#    → Blaue LED leuchtet wenn WLAN-Verbindung zu RPi 5 steht
#    → Gelbe LED blinkt wenn Teensy Daten sendet
#
#  VORAUSSETZUNG:
#    • Raspberry Pi OS Lite 64-bit (Bookworm, Debian 12)
#    • Internetverbindung für apt/pip (Ersteinrichtung)
#    • Projektordner liegt in ~/power_debug_system/ auf dem RPi Zero 2 W
#
# ==============================================================================
set -euo pipefail

# ── Farben ────────────────────────────────────────────────────────────────────
RED='\033[0;31m';  GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m';     NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}══ $* ══${NC}"; }

# ── Argument prüfen ───────────────────────────────────────────────────────────
NODE_ID="${1:-}"
if [[ "$NODE_ID" != "1" && "$NODE_ID" != "2" ]]; then
    error "Bitte Node-ID angeben: sudo bash setup_node_zero2w.sh 1  ODER  2"
fi

# ── Prüfen: läuft das Skript auf einem Pi Zero 2 W? ──────────────────────────
# (Warnung bei falschem Board — bricht nicht ab)
if command -v raspi-config &>/dev/null || [[ -f /proc/device-tree/model ]]; then
    BOARD_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "unknown")
    if echo "$BOARD_MODEL" | grep -qi "Zero 2"; then
        ok "Board erkannt: $BOARD_MODEL"
    elif echo "$BOARD_MODEL" | grep -qi "Zero W"; then
        warn "Board ist ein Pi Zero W (nicht Zero 2 W)!"
        warn "Dieses Skript ist für den Pi Zero 2 W optimiert."
        warn "Für Pi Zero W bitte setup_node.sh (32-bit Version) verwenden."
        warn "Fortfahren in 5 Sekunden... (Strg+C zum Abbrechen)"
        sleep 5
    fi
fi

# ── Prüfen: 64-bit OS? ────────────────────────────────────────────────────────
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" ]]; then
    warn "Architektur: $ARCH — erwartet: aarch64 (64-bit)"
    warn "Auf Pi Zero 2 W wird 64-bit Pi OS Lite (Bookworm) empfohlen."
    warn "Fortfahren in 5 Sekunden..."
    sleep 5
else
    ok "Architektur: $ARCH (64-bit) ✓"
fi

# ── Abgeleitete Werte ─────────────────────────────────────────────────────────
RPI5_IP="192.168.42.1"             # IP des RPi 5 WLAN-Hotspots
AP_SSID="RoboDebug"                # SSID des RPi 5 Access Points
AP_PASS="robodebug123"             # Passwort des RPi 5 Access Points
INSTALL_DIR="/opt/power_debug_node"
SERVICE_RECV="uart-receiver"
PROJECT_SRC="$(dirname "$(realpath "$0")")"

# ── Root-Check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Bitte mit sudo ausführen: sudo bash setup_node_zero2w.sh $NODE_ID"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Power Debug System — Node ${NODE_ID} Setup                       ║"
echo "║   Zielplattform: Raspberry Pi Zero 2 W (64-bit OS)       ║"
echo "║   WLAN-SSID: ${AP_SSID}  |  RPi5: ${RPI5_IP}           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
info "Projektverzeichnis: $PROJECT_SRC"
info "Installationsziel:  $INSTALL_DIR"
info "Board-Architektur:  $ARCH"
sleep 1

# ══════════════════════════════════════════════════════════════════════════════
step "1 | Systempakete aktualisieren & installieren"
# ══════════════════════════════════════════════════════════════════════════════
info "apt-get update..."
apt-get update -qq

info "Installiere Pakete (arm64)..."
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-serial \
    python3-gpiozero \
    python3-lgpio \
    wireless-tools \
    network-manager \
    iproute2 \
    usbutils \
    avrdude \
    teensy-loader-cli \
    git \
    curl \
    bluez \
    python3-dbus \
    python3-gi

# Hinweis Bluetooth-Flash-Feature (siehe Flash_Implementierung.md, Abweichung):
#   Es wird bewusst NICHT auf `bluez-tools`/`bt-agent` bzw. `sdptool` gesetzt,
#   da deren Verfügbarkeit auf "Raspberry Pi OS Lite (Legacy, 64-bit)" nicht
#   zuverlässig garantiert ist. bt_flash_receiver.py registriert Pairing-Agent
#   und SPP-Profil stattdessen direkt über D-Bus (python3-dbus/python3-gi),
#   die auf Legacy- wie auf aktuellen Images identisch verfügbar sind.

# ── RPi.GPIO: auf 64-bit Pi OS Bookworm noch verfügbar, aber deprecated ───────
# Für status_leds.py wird RPi.GPIO benötigt (direkter GPIO-Zugriff)
# lgpio ist die moderne Alternative, status_leds.py würde aber Anpassungen brauchen.
# Wir installieren beide — RPi.GPIO für bestehenden Code, lgpio für zukünftige Änderungen.
info "Installiere GPIO-Bibliotheken..."
if apt-get install -y --no-install-recommends python3-rpi.gpio 2>/dev/null; then
    ok "python3-rpi.gpio installiert (für status_leds.py Kompatibilität)"
else
    warn "python3-rpi.gpio nicht im apt-Repo gefunden (auf 64-bit deprecated)"
    warn "Versuche Installation via pip..."
    pip3 install --break-system-packages RPi.GPIO && ok "RPi.GPIO via pip installiert" \
        || warn "RPi.GPIO nicht installierbar — status_leds.py-LEDs werden deaktiviert"
fi

# pip-Pakete die nicht als apt-Paket verfügbar sind
info "Installiere Python-Pakete via pip..."
pip3 install --break-system-packages \
    pyserial

ok "Pakete installiert"

# ── pyserial: serial.tools.list_ports wird vom Software-Bootloader-Trigger ──
# in bt_flash_receiver.py benötigt (trigger_bootloader_mode() sucht darüber
# den Teensy-CDC-Port anhand von VID/PID). python3-serial (apt) UND pyserial
# (pip, s.o.) bringen dieses Submodul standardmäßig mit — hier nur zur
# Absicherung nochmal explizit geprüft.
if python3 -c "import serial.tools.list_ports" 2>/dev/null; then
    ok "serial.tools.list_ports verfügbar (Software-Bootloader-Trigger einsatzbereit)"
else
    warn "serial.tools.list_ports NICHT verfügbar — Software-Bootloader-Trigger"
    warn "für den Teensy-Flash faellt auf manuellen Knopfdruck zurueck."
fi

# ── Paketversionen zur Diagnose ausgeben ──────────────────────────────────────
python3 -c "import serial; print(f'   pyserial:  {serial.VERSION}')" 2>/dev/null || true
python3 -c "import RPi.GPIO as G; print(f'   RPi.GPIO:  {G.VERSION}')" 2>/dev/null || \
    python3 -c "import lgpio; print(f'   lgpio:     (verfügbar)')" 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════════════════
step "2 | UART freischalten (PL011 auf GPIO14/15)"
# ══════════════════════════════════════════════════════════════════════════════
#
#  Identisch zum Pi Zero W: der Pi Zero 2 W (BCM2710A1) hat denselben Aufbau:
#    - PL011 UART (ttyAMA0): standardmäßig vom Bluetooth-Chip belegt
#    - mini UART  (ttyS0):   zu wenig Pufferfähigkeit für hohe Baudraten
#
#  dtoverlay=disable-bt:    Bluetooth vom PL011-UART trennen
#  enable_uart=1:           PL011 auf GPIO14/15 aktivieren
#  init_uart_clock=64000000: UART-Basistakt auf 64 MHz anheben
#                            → ermöglicht exakte 1 Mbps und bis zu 4 Mbps Baudraten
#                            → Pi Zero 2 W unterstützt zuverlässig auch 4 Mbps+
#  dtoverlay=uart0:         GPIO14/15 als UART0/PL011 konfigurieren
#
#  Hinweis Verdrahtung (Baudrate muss in spi_receiver.py UND main.cpp übereinstimmen):
#    Teensy Serial3 TX (Pin 14) → RPi GPIO15 (Pin 10, UART RX)  ← aktuell Serial3!
#    Teensy Serial3 RX (Pin 15) ← RPi GPIO14 (Pin 8,  UART TX)  ← optional
#    GND                        ─  RPi GND   (Pin 6)
#
CONFIG="/boot/firmware/config.txt"
CMDLINE="/boot/firmware/cmdline.txt"
# Fallback für ältere Pi OS Versionen (pre-Bookworm)
[[ ! -f "$CONFIG" ]] && CONFIG="/boot/config.txt"
[[ ! -f "$CMDLINE" ]] && CMDLINE="/boot/cmdline.txt"

info "Bearbeite $CONFIG ..."

# SPI deaktivieren (wird nicht genutzt)
if grep -q "^dtparam=spi=on" "$CONFIG"; then
    sed -i 's/^dtparam=spi=on/dtparam=spi=off/' "$CONFIG"
    info "SPI deaktiviert (war aktiv)"
elif ! grep -q "dtparam=spi" "$CONFIG"; then
    echo "dtparam=spi=off" >> "$CONFIG"
fi

# Bluetooth NICHT mehr komplett deaktivieren, sondern auf Mini-UART umlegen
# → gibt PL011 (GPIO14/15) weiterhin exklusiv fuer den Teensy frei, UND laesst
#   Bluetooth (Wireless-Flash-Feature) parallel ueber die Mini-UART laufen.
# (Abweichung vom urspruenglichen "disable-bt"-Verhalten dieses Skripts — siehe
#  Flash_Implementierung.md Abschnitt 3.1/6. Ein evtl. aus einem aelteren Lauf
#  vorhandener disable-bt-Eintrag wird dabei automatisch ersetzt.)
if grep -q "^dtoverlay=disable-bt" "$CONFIG"; then
    sed -i 's/^dtoverlay=disable-bt/dtoverlay=miniuart-bt/' "$CONFIG"
    ok "dtoverlay=disable-bt -> dtoverlay=miniuart-bt umgestellt (alter Eintrag ersetzt)"
elif ! grep -q "^dtoverlay=miniuart-bt" "$CONFIG"; then
    echo "" >> "$CONFIG"
    echo "# Power Debug System: PL011-UART fuer Teensy freischalten," >> "$CONFIG"
    echo "# Bluetooth auf Mini-UART (fuer Wireless-Flash-Feature, siehe Flash_Implementierung.md)" >> "$CONFIG"
    echo "dtoverlay=miniuart-bt" >> "$CONFIG"
    ok "dtoverlay=miniuart-bt eingetragen"
else
    ok "dtoverlay=miniuart-bt bereits vorhanden"
fi

# UART aktivieren
if ! grep -q "^enable_uart=1" "$CONFIG"; then
    echo "enable_uart=1" >> "$CONFIG"
    ok "enable_uart=1 eingetragen"
else
    ok "enable_uart=1 bereits vorhanden"
fi

# UART-Basistakt erhöhen
# Pi Zero 2 W (BCM2710A1): default 3 MHz → 64 MHz für präzise hohe Baudraten
# Bei 64 MHz: 1 Mbps = Divisor 64 (exakt), 4 Mbps = Divisor 16 (exakt)
if ! grep -q "^init_uart_clock=64000000" "$CONFIG"; then
    echo "init_uart_clock=64000000" >> "$CONFIG"
    ok "init_uart_clock=64000000 eingetragen (Pi Zero 2 W: bis 4+ Mbps stabil)"
fi

# GPIO14/15 als UART konfigurieren
if ! grep -q "dtoverlay=uart0" "$CONFIG"; then
    echo "dtoverlay=uart0" >> "$CONFIG"
    ok "dtoverlay=uart0 eingetragen"
fi

# ── cmdline.txt: Serielle Konsole auf GPIO14/15 entfernen ────────────────────
info "Bearbeite $CMDLINE ..."
if grep -q "console=serial0" "$CMDLINE"; then
    sed -i 's/console=serial0,[0-9]*\s*//g' "$CMDLINE"
    ok "Serielle Konsole (console=serial0) entfernt"
else
    ok "Serielle Konsole war nicht aktiv"
fi
if grep -q "console=ttyAMA0" "$CMDLINE"; then
    sed -i 's/console=ttyAMA0,[0-9]*\s*//g' "$CMDLINE"
    ok "ttyAMA0-Konsole entfernt"
fi

# Bluetooth-Dienste aktivieren (Wireless-Flash-Feature — siehe Flash_Implementierung.md)
# Zuvor deaktivierte dieses Skript hciuart/bluetooth komplett; das ist mit
# dtoverlay=miniuart-bt (siehe oben) nicht mehr noetig bzw. wuerde das neue
# Feature verhindern.
info "Bluetooth-Dienste aktivieren..."
systemctl unmask hciuart.service bluetooth.service 2>/dev/null || true
systemctl enable hciuart.service bluetooth.service 2>/dev/null || true
ok "Bluetooth-Dienste aktiviert (hciuart, bluetooth)"


# ══════════════════════════════════════════════════════════════════════════════
step "3 | WLAN zum RPi 5 konfigurieren (DHCP)"
# ══════════════════════════════════════════════════════════════════════════════
#
#  Der Node verbindet sich mit dem WLAN-Hotspot des RPi 5.
#  Die IP-Adresse wird per DHCP vom RPi 5 vergeben (NICHT statisch konfiguriert).
#  Der RPi 5 dhcp-Server vergibt typischerweise 192.168.42.11 / .12,
#  aber das hängt von der RPi-5-Konfiguration ab.
#
#  WICHTIG: SSID und Passwort müssen exakt mit dem RPi 5 AP übereinstimmen.
#           Prüfe auf RPi 5: nmcli connection show PowerDebugAP (oder RoboDebug)
#
info "WLAN-Verbindung '$AP_SSID' anlegen..."
nmcli connection delete "$AP_SSID" 2>/dev/null && \
    info "Alte '$AP_SSID'-Verbindung gelöscht" || true

nmcli connection add \
    type wifi \
    ifname wlan0 \
    con-name "$AP_SSID" \
    ssid "$AP_SSID" \
    -- \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$AP_PASS" \
    ipv4.method auto \
    connection.autoconnect yes \
    connection.autoconnect-priority 100

ok "WLAN-Profil '$AP_SSID' erstellt (IP per DHCP vom RPi 5)"

# ── Hostname setzen ───────────────────────────────────────────────────────────
HOSTNAME="debug-node-${NODE_ID}"
info "Hostname: $HOSTNAME"
echo "$HOSTNAME" > /etc/hostname
sed -i "s/127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts 2>/dev/null || \
    echo "127.0.1.1   $HOSTNAME" >> /etc/hosts
ok "Hostname gesetzt: $HOSTNAME"

# ══════════════════════════════════════════════════════════════════════════════
step "4 | Projektdateien installieren nach $INSTALL_DIR"
# ══════════════════════════════════════════════════════════════════════════════

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/rpi_zero_node"
touch "$INSTALL_DIR/rpi_zero_node/__init__.py"

# status_leds.py — GPIO-Controller (RPi.GPIO)
if [[ -f "$PROJECT_SRC/status_leds.py" ]]; then
    cp "$PROJECT_SRC/status_leds.py" "$INSTALL_DIR/rpi_zero_node/"
    cp "$PROJECT_SRC/status_leds.py" "$INSTALL_DIR/rpi_zero_node/status_leds.py"
    ok "status_leds.py installiert"
else
    warn "status_leds.py nicht gefunden — LEDs deaktiviert"
fi

# UART-Receiver (spi_receiver.py)
if [[ -f "$PROJECT_SRC/spi_receiver.py" ]]; then
    cp "$PROJECT_SRC/spi_receiver.py" "$INSTALL_DIR/uart_receiver.py"
    ok "uart_receiver.py installiert (aus spi_receiver.py)"
elif [[ -f "$PROJECT_SRC/uart_receiver.py" ]]; then
    cp "$PROJECT_SRC/uart_receiver.py" "$INSTALL_DIR/uart_receiver.py"
    ok "uart_receiver.py installiert"
else
    warn "uart_receiver.py / spi_receiver.py nicht gefunden!"
fi


# bt_flash_receiver.py + gemeinsames Protokoll (Wireless-Flash-Feature)
SHARED_SRC="$(dirname "$PROJECT_SRC")/shared"
mkdir -p "$INSTALL_DIR/shared"
if [[ -f "$PROJECT_SRC/bt_flash_receiver.py" ]]; then
    cp "$PROJECT_SRC/bt_flash_receiver.py" "$INSTALL_DIR/rpi_zero_node/"
    ok "bt_flash_receiver.py installiert"
else
    warn "bt_flash_receiver.py nicht gefunden — Wireless-Flash-Feature nicht verfuegbar"
fi
if [[ -f "$SHARED_SRC/bt_flash_protocol.py" ]]; then
    cp "$SHARED_SRC/bt_flash_protocol.py" "$INSTALL_DIR/shared/"
    cp "$SHARED_SRC/bt_flash_protocol.py" "$INSTALL_DIR/rpi_zero_node/"
    ok "bt_flash_protocol.py installiert"
else
    warn "bt_flash_protocol.py (shared/) nicht gefunden — Wireless-Flash-Feature nicht verfuegbar"
fi

# Auth-Token fuer den Bluetooth-Flash-Kanal generieren (einmalig, bleibt ueber
# spaetere Setup-Laeufe hinweg erhalten, damit bt_targets.json auf dem PC nicht
# staendig neu gepflegt werden muss)
SECRET_FILE="$INSTALL_DIR/bt_flash_secret"
if [[ ! -f "$SECRET_FILE" ]]; then
    python3 -c "import secrets; print(secrets.token_hex(16))" > "$SECRET_FILE"
    chmod 600 "$SECRET_FILE"
    ok "Neuer Auth-Token fuer Bluetooth-Flash generiert: $SECRET_FILE"
else
    ok "Auth-Token bereits vorhanden: $SECRET_FILE"
fi

chmod +x "$INSTALL_DIR/"*.py "$INSTALL_DIR/rpi_zero_node/"*.py 2>/dev/null || true
ok "Projektdateien installiert"

# ══════════════════════════════════════════════════════════════════════════════
step "5 | Systemdienst: uart-receiver"
# ══════════════════════════════════════════════════════════════════════════════

cat > /etc/systemd/system/${SERVICE_RECV}.service << SVCEOF
[Unit]
Description=Power Debug UART Receiver (Node ${NODE_ID}) — RPi Zero 2 W
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="NODE_ID=${NODE_ID}"
Environment="RPI5_IP=${RPI5_IP}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/uart_receiver.py
Restart=on-failure
RestartSec=5s
StartLimitInterval=60s
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=uart-receiver

[Install]
WantedBy=multi-user.target
SVCEOF

ok "uart-receiver.service erstellt"

# ══════════════════════════════════════════════════════════════════════════════
step "5b | Systemdienst: bt-flash-receiver (Wireless-Flash-Feature)"
# ══════════════════════════════════════════════════════════════════════════════
SERVICE_BT="bt-flash-receiver"
BT_CHANNEL="${BT_FLASH_CHANNEL:-4}"

# Hinweis Software-Bootloader-Trigger (trigger_bootloader_mode() in
# bt_flash_receiver.py): Der Dienst läuft unten bewusst als User=root, damit
# er ohne zusätzliche udev-Regeln/Gruppenmitgliedschaft sowohl auf den
# Teensy-CDC-Serial-Port (/dev/ttyACM*, für das Setzen der Baudrate 134) als
# auch auf den HalfKay-Bootloader (raw USB, für teensy_loader_cli) zugreifen
# kann. Bei einem spaeteren Wechsel auf einen unprivilegierten Service-User
# muesste dieser zusaetzlich der Gruppe `dialout` hinzugefuegt werden
# (sudo usermod -aG dialout <user>) und ggf. eine udev-Regel fuer den
# HalfKay-Bootloader (16c0:0478) angelegt werden.
if [[ -f "$INSTALL_DIR/rpi_zero_node/bt_flash_receiver.py" ]]; then
cat > /etc/systemd/system/${SERVICE_BT}.service << SVCEOF
[Unit]
Description=Power Debug Bluetooth Flash Receiver (Node ${NODE_ID}) — RPi Zero 2 W
After=bluetooth.target bluetooth.service dbus.service
Wants=bluetooth.target
Requires=dbus.service

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}/rpi_zero_node
Environment="NODE_ID=${NODE_ID}"
Environment="INSTALL_DIR=${INSTALL_DIR}"
Environment="BT_FLASH_CHANNEL=${BT_CHANNEL}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/rpi_zero_node/bt_flash_receiver.py
Restart=on-failure
RestartSec=5s
StartLimitInterval=60s
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bt-flash-receiver

[Install]
WantedBy=multi-user.target
SVCEOF
    ok "${SERVICE_BT}.service erstellt (Kanal ${BT_CHANNEL})"
else
    warn "bt_flash_receiver.py nicht installiert — ${SERVICE_BT}.service wird uebersprungen"
    SERVICE_BT=""
fi

# ══════════════════════════════════════════════════════════════════════════════
step "6 | Dienste aktivieren"
# ══════════════════════════════════════════════════════════════════════════════

systemctl daemon-reload
systemctl enable ${SERVICE_RECV}.service
ok "uart-receiver aktiviert"

if [[ -n "$SERVICE_BT" ]]; then
    systemctl enable ${SERVICE_BT}.service
    ok "bt-flash-receiver aktiviert"
fi

warn "Dienste starten erst nach 'sudo reboot' (UART/Bluetooth-Konfiguration braucht Neustart)"

# ══════════════════════════════════════════════════════════════════════════════
step "7 | Verifizierung"
# ══════════════════════════════════════════════════════════════════════════════

echo ""
info "──── $CONFIG (relevante Einträge) ────"
grep -E "dtoverlay|enable_uart|dtparam=spi|uart0|init_uart_clock" "$CONFIG" | \
    while IFS= read -r line; do echo "   $line"; done

echo ""
info "──── $CMDLINE ────"
echo "   $(cat "$CMDLINE")"

echo ""
systemctl is-enabled ${SERVICE_RECV}.service 2>/dev/null && \
    echo "   ✅ uart-receiver: enabled" || echo "   ❌ uart-receiver: NOT enabled"

echo ""
info "──── Python-Pakete ────"
python3 -c "import serial; print(f'   ✅ pyserial {serial.VERSION}')" 2>/dev/null || \
    echo "   ❌ pyserial fehlt"
python3 -c "import RPi.GPIO as G; print(f'   ✅ RPi.GPIO {G.VERSION}')" 2>/dev/null || \
    echo "   ⚠️  RPi.GPIO nicht gefunden (LEDs deaktiviert)"
python3 -c "import lgpio; print('   ✅ lgpio (moderne GPIO-Alternative)')" 2>/dev/null || \
    echo "   ⚠️  lgpio nicht gefunden"

echo ""
info "──── Bluetooth-Flash-Feature ────"
if command -v bluetoothctl &>/dev/null; then
    BT_MAC=$(bluetoothctl show 2>/dev/null | awk -F': ' '/Controller/ {print $2; exit}')
    echo "   Controller-MAC: ${BT_MAC:-nicht ermittelbar (bluetooth.service evtl. erst nach Reboot aktiv)}"
else
    echo "   ⚠️  bluetoothctl nicht gefunden"
fi
systemctl is-enabled ${SERVICE_BT:-bt-flash-receiver}.service 2>/dev/null && \
    echo "   ✅ bt-flash-receiver: enabled" || echo "   ❌ bt-flash-receiver: NOT enabled"
if [[ -f "$SECRET_FILE" ]]; then
    echo "   Auth-Token (für bt_targets.json auf dem PC):"
    echo "     $(cat "$SECRET_FILE")"
fi
echo "   RFCOMM-Kanal: ${BT_CHANNEL}"
echo "   Geraetename:  PDS-Node${NODE_ID}-BT (sichtbar erst NACH sudo reboot)"
echo "   Pairing-PIN:  0000 (Auto-Accept-Agent, siehe bt_flash_receiver.py)"
echo ""
echo "   -> Diese drei Werte (MAC, Token, Kanal) in bt_targets.json auf dem"
echo "      Windows-PC eintragen (pc_setup/pc_flash_tool/bt_targets.json)."

echo ""
info "──── Software-Bootloader-Trigger (kein Knopfdruck mehr nötig) ────"
python3 -c "import serial.tools.list_ports; print('   ✅ serial.tools.list_ports verfügbar')" 2>/dev/null || \
    echo "   ❌ serial.tools.list_ports fehlt — Trigger faellt auf manuellen Knopfdruck zurueck"
if command -v lsusb &>/dev/null; then
    if lsusb 2>/dev/null | grep -qi "16c0:04"; then
        echo "   ℹ️  Teensy aktuell am USB erkannt: $(lsusb | grep -i '16c0:04')"
    else
        echo "   ℹ️  Aktuell kein Teensy am USB erkannt (ok, falls gerade nicht angeschlossen)"
    fi
else
    echo "   ⚠️  lsusb (usbutils) nicht gefunden"
fi

echo ""
info "──── Verdrahtung (Teensy ↔ RPi Zero 2 W) ────"
echo "   ACHTUNG: main.cpp nutzt Serial3 (nicht Serial1)!"
echo "   Teensy Pin 14 (TX3) → RPi GPIO15 (Pin 10, UART RX)"
echo "   Teensy Pin 15 (RX3) ← RPi GPIO14 (Pin 8,  UART TX)  [optional]"
echo "   GND                 ─  RPi GND   (Pin 6)"
echo ""
echo "   Baudrate in spi_receiver.py und main.cpp: 1.000.000 Baud (1 Mbps)"
echo "   Pi Zero 2 W unterstützt zuverlässig bis 4 Mbps (Kabel < 20 cm)"

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ✅  Setup Node ${NODE_ID} (RPi Zero 2 W) abgeschlossen!         ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║   Nächste Schritte:                                      ║"
echo "║     1. sudo reboot                                       ║"
echo "║                                                          ║"
echo "║   LEDs nach Reboot:                                      ║"
echo "║     🔵 Blau AN      → WLAN zu RPi 5 verbunden           ║"
echo "║     🟡 Gelb blinkt  → Teensy sendet UART-Daten          ║"
echo "║     🟢 Grün blinkt  → Dienste laufen normal             ║"
echo "║                                                          ║"
echo "║   Diagnose:                                              ║"
echo "║     journalctl -u uart-receiver -f                       ║"
echo "║     journalctl -u bt-flash-receiver -f                   ║"
echo "║     ls -la /dev/ttyAMA0                                  ║"
echo "║     ip addr show wlan0                                   ║"
echo "║     bluetoothctl show                                    ║"
echo "║                                                          ║"
echo "║   Wireless-Flash ohne Knopfdruck:                        ║"
echo "║     Teensy wird vor dem Flashen per Software in den      ║"
echo "║     Bootloader versetzt (siehe bt_flash_receiver.py).    ║"
echo "║     Klappt nur bei Sketches mit USB-Typ 'Serial'.        ║"
echo "║                                                          ║"
echo "║   Hinweis Verdrahtung:                                   ║"
echo "║     Teensy nutzt Serial3 (Pin 14/15), nicht Serial1!     ║"
echo "║     Baudrate: 1 Mbps (in spi_receiver.py + main.cpp)     ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"