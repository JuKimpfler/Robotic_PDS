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
#    1. Systempakete installieren (Python, pyserial, GPIO-Libs, ...)
#    2. UART freischalten (PL011 auf GPIO14/15, Bluetooth deaktivieren)
#    3. SPI deaktivieren (nicht genutzt)
#    4. WLAN zum RPi 5 konfigurieren (DHCP — IP kommt vom RPi-5-Hotspot)
#    5. USB-Gadget-Modus (RNDIS) für direkten PC-Zugriff einrichten
#    6. Projektdateien installieren (/opt/power_debug_node/)
#    7. Systemdienste anlegen (uart-receiver, flash-daemon)
#    8. Dienste aktivieren (starten automatisch bei jedem Boot)
#
#  WLAN-Zugang:
#    SSID:     RoboDebug          ← muss mit RPi 5 AP übereinstimmen
#    Passwort: robodebug123       ← muss mit RPi 5 AP übereinstimmen
#    IP:       per DHCP (vergeben vom RPi 5 Hotspot)
#
#  USB-Gadget (PC-Verbindung):
#    Node-IP:  192.168.7.2        ← statisch auf dem Node
#    PC-IP:    192.168.7.x        ← per DHCP (oder manuell)
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
SERVICE_FLASH="flash-daemon"
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
    curl

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

# Bluetooth deaktivieren → gibt PL011-UART frei
# (Funktioniert auf Pi Zero 2 W identisch zum Pi Zero W)
if ! grep -q "^dtoverlay=disable-bt" "$CONFIG"; then
    echo "" >> "$CONFIG"
    echo "# Power Debug System: PL011-UART freischalten" >> "$CONFIG"
    echo "# Bluetooth deaktiviert — Pi Zero 2 W identisch zu Pi Zero W" >> "$CONFIG"
    echo "dtoverlay=disable-bt" >> "$CONFIG"
    ok "dtoverlay=disable-bt eingetragen"
else
    ok "dtoverlay=disable-bt bereits vorhanden"
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

# Bluetooth-Dienste deaktivieren
info "Bluetooth-Dienste deaktivieren..."
systemctl disable hciuart.service bluetooth.service 2>/dev/null || true
ok "Bluetooth-Dienste deaktiviert"

# ══════════════════════════════════════════════════════════════════════════════
step "3 | USB-Gadget-Modus (RNDIS) für PC-Verbindung"
# ══════════════════════════════════════════════════════════════════════════════
#
#  Pi Zero 2 W unterstützt denselben dwc2 USB-OTG-Gadget-Modus wie Pi Zero W.
#  Der Micro-USB-Datenport (nicht der PWR-Port!) wird als virtuelle Netzwerkkarte
#  am PC sichtbar.
#
#  Node-Seite: statische IP 192.168.7.2
#  PC-Seite:   beliebige IP im Bereich 192.168.7.x (DHCP oder manuell)
#
info "Prüfe USB-Gadget-Einträge in $CONFIG ..."
if ! grep -q "dtoverlay=dwc2" "$CONFIG"; then
    echo "" >> "$CONFIG"
    echo "# USB-Gadget (RNDIS für PC-Zugriff per USB-C/Micro-USB)" >> "$CONFIG"
    echo "dtoverlay=dwc2,dr_mode=peripheral" >> "$CONFIG"
    ok "USB-Gadget-Overlay eingetragen"
else
    ok "USB-Gadget-Overlay bereits vorhanden"
fi

if ! grep -q "dwc2" "$CMDLINE"; then
    sed -i 's/rootwait/rootwait modules-load=dwc2,g_ether/' "$CMDLINE"
    ok "dwc2/g_ether in cmdline eingetragen"
else
    ok "dwc2 bereits in cmdline"
fi

info "USB-Gadget-Interface (usb0) mit statischer IP konfigurieren..."
nmcli connection delete id "USB-Gadget" 2>/dev/null || true
nmcli connection add \
    type ethernet \
    con-name "USB-Gadget" \
    ifname usb0 \
    ipv4.method manual \
    ipv4.addresses "192.168.7.2/24" \
    connection.autoconnect yes
ok "USB-Gadget konfiguriert (Node-IP: 192.168.7.2)"

# ══════════════════════════════════════════════════════════════════════════════
step "4 | WLAN zum RPi 5 konfigurieren (DHCP)"
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
step "5 | Projektdateien installieren nach $INSTALL_DIR"
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

# Flash-Daemon
if [[ -f "$PROJECT_SRC/flash_daemon.py" ]]; then
    cp "$PROJECT_SRC/flash_daemon.py" "$INSTALL_DIR/flash_daemon.py"
    ok "flash_daemon.py installiert"
else
    warn "flash_daemon.py nicht gefunden — Flash-Funktion nicht verfügbar"
fi

chmod +x "$INSTALL_DIR/"*.py 2>/dev/null || true
ok "Projektdateien installiert"

# ══════════════════════════════════════════════════════════════════════════════
step "6 | Systemdienst: uart-receiver"
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
step "7 | Systemdienst: flash-daemon"
# ══════════════════════════════════════════════════════════════════════════════

if [[ -f "$INSTALL_DIR/flash_daemon.py" ]]; then
    cat > /etc/systemd/system/${SERVICE_FLASH}.service << SVCEOF
[Unit]
Description=Power Debug Flash Daemon (Node ${NODE_ID}) — RPi Zero 2 W
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="NODE_ID=${NODE_ID}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/flash_daemon.py
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=flash-daemon

[Install]
WantedBy=multi-user.target
SVCEOF
    ok "flash-daemon.service erstellt"
else
    warn "flash_daemon.py fehlt — flash-daemon.service übersprungen"
fi

# ══════════════════════════════════════════════════════════════════════════════
step "8 | Dienste aktivieren"
# ══════════════════════════════════════════════════════════════════════════════

systemctl daemon-reload
systemctl enable ${SERVICE_RECV}.service
ok "uart-receiver aktiviert"

if [[ -f /etc/systemd/system/${SERVICE_FLASH}.service ]]; then
    systemctl enable ${SERVICE_FLASH}.service
    ok "flash-daemon aktiviert"
fi

warn "Dienste starten erst nach 'sudo reboot' (UART-Konfiguration braucht Neustart)"

# ══════════════════════════════════════════════════════════════════════════════
step "9 | Verifizierung"
# ══════════════════════════════════════════════════════════════════════════════

echo ""
info "──── $CONFIG (relevante Einträge) ────"
grep -E "dtoverlay|enable_uart|dtparam=spi|uart0|init_uart_clock" "$CONFIG" | \
    while IFS= read -r line; do echo "   $line"; done

echo ""
info "──── $CMDLINE ────"
echo "   $(cat "$CMDLINE")"

echo ""
info "──── Aktivierte Dienste ────"
systemctl is-enabled ${SERVICE_RECV}.service 2>/dev/null && \
    echo "   ✅ uart-receiver: enabled" || echo "   ❌ uart-receiver: NOT enabled"
[[ -f /etc/systemd/system/${SERVICE_FLASH}.service ]] && {
    systemctl is-enabled ${SERVICE_FLASH}.service 2>/dev/null && \
        echo "   ✅ flash-daemon:  enabled" || echo "   ❌ flash-daemon:  NOT enabled"
}

echo ""
info "──── Python-Pakete ────"
python3 -c "import serial; print(f'   ✅ pyserial {serial.VERSION}')" 2>/dev/null || \
    echo "   ❌ pyserial fehlt"
python3 -c "import RPi.GPIO as G; print(f'   ✅ RPi.GPIO {G.VERSION}')" 2>/dev/null || \
    echo "   ⚠️  RPi.GPIO nicht gefunden (LEDs deaktiviert)"
python3 -c "import lgpio; print('   ✅ lgpio (moderne GPIO-Alternative)')" 2>/dev/null || \
    echo "   ⚠️  lgpio nicht gefunden"

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
echo "║     ls -la /dev/ttyAMA0                                  ║"
echo "║     ip addr show wlan0                                   ║"
echo "║                                                          ║"
echo "║   Hinweis Verdrahtung:                                   ║"
echo "║     Teensy nutzt Serial3 (Pin 14/15), nicht Serial1!     ║"
echo "║     Baudrate: 1 Mbps (in spi_receiver.py + main.cpp)     ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"