#!/usr/bin/env bash
# ==============================================================================
#  setup_node.sh — Einrichtungsskript für RPi Zero W (UART-Version)
#  Power Debug System | RoboCup Junior Soccer
# ==============================================================================
#
#  AUFRUF:
#    sudo bash setup_node.sh 1    → Node 1 einrichten (IP: 192.168.42.11)
#    sudo bash setup_node.sh 2    → Node 2 einrichten (IP: 192.168.42.12)
#
#  WAS DIESES SKRIPT TUT:
#    1. Systempakete installieren (Python, pyserial, RPi.GPIO, ...)
#    2. UART freischalten (PL011 auf GPIO14/15, Bluetooth deaktivieren)
#    3. SPI deaktivieren (wird nicht mehr benötigt)
#    4. WLAN zum RPi 5 konfigurieren (statische IP)
#    5. USB-Gadget-Modus (RNDIS) für PC-Verbindung einrichten
#    6. Projektdateien installieren (/opt/power_debug_node/)
#    7. Systemdienste anlegen (uart-receiver, flash-daemon)
#    8. Dienste aktivieren (starten automatisch bei jedem Boot)
#
#  NACH DEM SKRIPT:
#    → sudo reboot
#    → Blaue LED leuchtet wenn WLAN-Verbindung zu RPi 5 steht
#    → Gelbe LED blinkt wenn Teensy Daten sendet
#
#  VORAUSSETZUNG:
#    • Raspberry Pi OS Lite 64-bit (Bookworm)
#    • Internetverbindung für apt/pip (bei der Ersteinrichtung)
#    • Projektordner liegt in ~/power_debug_system/ auf dem RPi Zero
#
# ==============================================================================

set -euo pipefail   # Skript bricht bei Fehler ab, undefinierte Vars = Fehler

# ── Farben für lesbare Terminal-Ausgabe ───────────────────────────────────────
RED='\033[0;31m';  GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m';     NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()    { echo -e "\n${BOLD}══ $* ══${NC}"; }

# ── Argument prüfen ───────────────────────────────────────────────────────────
NODE_ID="${1:-}"
if [[ "$NODE_ID" != "1" && "$NODE_ID" != "2" ]]; then
    error "Bitte Node-ID angeben: sudo bash setup_node.sh 1  ODER  sudo bash setup_node.sh 2"
fi

# ── Abgeleitete Werte ─────────────────────────────────────────────────────────
NODE_IP="192.168.42.1${NODE_ID}"          # 192.168.42.11 oder .12
RPI5_IP="192.168.42.1"                    # RPi 5 Hotspot-Gateway
AP_SSID="PowerDebugAP"                    # WLAN-Netz des RPi 5
AP_PASS="HighSpeedDebug123"               # WLAN-Passwort
INSTALL_DIR="/opt/power_debug_node"       # Installations-Ziel
SERVICE_RECV="uart-receiver"              # Name des Empfangsdiensts
SERVICE_FLASH="flash-daemon"              # Name des Flash-Diensts
PROJECT_SRC="$(dirname "$(realpath "$0")")"  # Verzeichnis dieses Skripts

# ── Root-Check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Bitte mit sudo ausführen: sudo bash setup_node.sh $NODE_ID"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Power Debug System — Node ${NODE_ID} Setup (UART)          ║"
echo "║   IP: ${NODE_IP}    RPi5: ${RPI5_IP}                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
info "Projektverzeichnis: $PROJECT_SRC"
info "Installationsziel:  $INSTALL_DIR"
sleep 1

# ══════════════════════════════════════════════════════════════════════════════
step "1 | Systempakete aktualisieren & installieren"
# ══════════════════════════════════════════════════════════════════════════════

info "apt-get update..."
apt-get update -qq

info "Installiere Pakete..."
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-rpi.gpio \
    python3-serial \
    python3-gpiozero \
    wireless-tools \
    network-manager \
    iproute2 \
    usbutils \
    avrdude \
    teensy-loader-cli \
    git \
    curl

# Python-Pakete die nicht als apt-Paket verfügbar sind
info "Installiere Python-Pakete via pip..."
pip3 install --break-system-packages \
    pyserial \
    RPi.GPIO

ok "Pakete installiert"

# ══════════════════════════════════════════════════════════════════════════════
step "2 | UART freischalten (PL011 auf GPIO14/15)"
# ══════════════════════════════════════════════════════════════════════════════
#
#  Hintergrund:
#  Der RPi Zero W hat zwei UART-Hardware-Controller:
#    - mini UART (ttyS0):  an GPIO14/15 — Standard, hat Takt-Probleme bei
#                          hohen Baudraten, NICHT geeignet für 4 Mbps
#    - PL011 UART (ttyAMA0): vollwertig, stabil auch bei 4 Mbps — aber
#                            standardmäßig vom Bluetooth-Chip belegt
#
#  Lösung: Bluetooth deaktivieren → PL011 frei → auf GPIO14/15 legen
#
#  dtoverlay=disable-bt     → Bluetooth-Modul vom UART trennen
#  enable_uart=1            → PL011 UART auf GPIO14/15 aktivieren
#
CONFIG="/boot/firmware/config.txt"
CMDLINE="/boot/firmware/cmdline.txt"

# Fallback: älterer Pfad (Pi OS vor Bookworm)
[[ ! -f "$CONFIG" ]] && CONFIG="/boot/config.txt"
[[ ! -f "$CMDLINE" ]] && CMDLINE="/boot/cmdline.txt"

info "Bearbeite $CONFIG ..."

# SPI deaktivieren (wird nicht mehr benötigt)
if grep -q "^dtparam=spi=on" "$CONFIG"; then
    sed -i 's/^dtparam=spi=on/dtparam=spi=off/' "$CONFIG"
    info "SPI deaktiviert (war aktiv)"
else
    # Falls die Zeile fehlt, explizit off setzen
    if ! grep -q "dtparam=spi" "$CONFIG"; then
        echo "dtparam=spi=off" >> "$CONFIG"
    fi
fi

# Bluetooth deaktivieren (gibt PL011-UART frei)
if ! grep -q "^dtoverlay=disable-bt" "$CONFIG"; then
    echo "" >> "$CONFIG"
    echo "# Power Debug System: PL011-UART freischalten (BT deaktiviert)" >> "$CONFIG"
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

# GPIO14/15 als UART konfigurieren (alt0 = UART0/PL011)
if ! grep -q "dtoverlay=uart0" "$CONFIG"; then
    echo "dtoverlay=uart0" >> "$CONFIG"
    ok "dtoverlay=uart0 eingetragen"
fi

# ── cmdline.txt: Serielle Konsole entfernen ───────────────────────────────────
#  Ohne diese Änderung würde der RPi seinen Boot-Text auf GPIO14/15 senden,
#  was den UART-Stream zum Teensy hin korrumpiert.
info "Bearbeite $CMDLINE ..."
if grep -q "console=serial0" "$CMDLINE"; then
    # Entfernt 'console=serial0,XXXXX' aus der einzeiligen Datei
    sed -i 's/console=serial0,[0-9]*\s*//g' "$CMDLINE"
    ok "Serielle Konsole (console=serial0) entfernt"
else
    ok "Serielle Konsole war nicht aktiv — nichts zu tun"
fi

# Prüfe ob ttyAMA0 in cmdline noch auftaucht (ältere Systeme)
if grep -q "console=ttyAMA0" "$CMDLINE"; then
    sed -i 's/console=ttyAMA0,[0-9]*\s*//g' "$CMDLINE"
    ok "ttyAMA0-Konsole ebenfalls entfernt"
fi

# ── Bluetooth-Dienst deaktivieren ────────────────────────────────────────────
info "Bluetooth-Dienste deaktivieren..."
systemctl disable hciuart.service bluetooth.service 2>/dev/null || true
ok "Bluetooth-Dienste deaktiviert"

# ══════════════════════════════════════════════════════════════════════════════
step "3 | USB-Gadget-Modus (RNDIS) für PC-Verbindung einrichten"
# ══════════════════════════════════════════════════════════════════════════════
#
#  Ermöglicht direkten Zugriff vom PC per USB-C — ohne WLAN.
#  Nützlich für die Ersteinrichtung, Debugging oder wenn kein RPi 5 dabei ist.
#  Der PC sieht den RPi Zero als Netzwerkadapter (IP: 192.168.7.2).

info "Prüfe USB-Gadget-Einträge in $CONFIG ..."
if ! grep -q "dtoverlay=dwc2" "$CONFIG"; then
    echo "" >> "$CONFIG"
    echo "# USB-Gadget (RNDIS für PC-Zugriff per USB)" >> "$CONFIG"
    echo "dtoverlay=dwc2,dr_mode=peripheral" >> "$CONFIG"
    ok "USB-Gadget-Overlay eingetragen"
else
    ok "USB-Gadget-Overlay bereits vorhanden"
fi

# dwc2-Modul beim Boot laden
if ! grep -q "dwc2" "$CMDLINE"; then
    # Fügt 'modules-load=dwc2,g_ether' vor 'rootwait' ein
    sed -i 's/rootwait/rootwait modules-load=dwc2,g_ether/' "$CMDLINE"
    ok "dwc2/g_ether Module in cmdline eingetragen"
else
    ok "dwc2 bereits in cmdline vorhanden"
fi

info "Statische IP für USB-Gadget-Interface (usb0) konfigurieren..."

# Falls eine alte Verbindung existiert, löschen
nmcli connection delete id "USB-Gadget" 2>/dev/null || true

# Neue Verbindung für das usb0-Interface mit statischer IP anlegen
nmcli connection add type ethernet con-name "USB-Gadget" ifname usb0 ipv4.method manual ipv4.addresses "192.168.7.2/24"

ok "USB-Gadget-Interface erfolgreich über NetworkManager konfiguriert."
# ══════════════════════════════════════════════════════════════════════════════
step "4 | WLAN zum RPi 5 konfigurieren (Node ${NODE_ID} → statische IP)"
# ══════════════════════════════════════════════════════════════════════════════

info "WLAN-Verbindung '$AP_SSID' anlegen..."

# Bestehende Verbindung entfernen falls vorhanden
nmcli connection delete "$AP_SSID" 2>/dev/null && \
    info "Alte '$AP_SSID'-Verbindung gelöscht" || true

# Neue WLAN-Verbindung anlegen
nmcli connection add \
    type wifi \
    ifname wlan0 \
    con-name "$AP_SSID" \
    ssid "$AP_SSID" \
    -- \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$AP_PASS" \
    ipv4.method manual \
    ipv4.addresses "${NODE_IP}/24" \
    ipv4.gateway "$RPI5_IP" \
    ipv4.dns "$RPI5_IP" \
    connection.autoconnect yes \
    connection.autoconnect-priority 100

ok "WLAN-Profil '$AP_SSID' erstellt (IP: $NODE_IP)"
info "Verbindung wird aktiv sobald RPi 5 den Hotspot aufspannt."

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

# Python-Paket kopieren
info "Kopiere Python-Paket..."
if [[ -d "$PROJECT_SRC/rpi_zero_node" ]]; then
    cp -r "$PROJECT_SRC/rpi_zero_node/"* "$INSTALL_DIR/rpi_zero_node/"
else
    warn "rpi_zero_node/ Verzeichnis nicht gefunden — bitte manuell kopieren"
fi

# UART-Receiver-Skript (ehemals spi_receiver.py — Name beibehalten für
# Kompatibilität mit bestehenden Dienst-Referenzen im Projekt)
info "Kopiere uart-receiver (spi_receiver.py → uart_receiver.py)..."
if [[ -f "$PROJECT_SRC/spi_receiver.py" ]]; then
    cp "$PROJECT_SRC/spi_receiver.py" "$INSTALL_DIR/uart_receiver.py"
    ok "uart_receiver.py installiert"
else
    warn "spi_receiver.py nicht gefunden — bitte $INSTALL_DIR/uart_receiver.py manuell ablegen"
fi

# Flash-Daemon
if [[ -f "$PROJECT_SRC/flash_daemon.py" ]]; then
    cp "$PROJECT_SRC/flash_daemon.py" "$INSTALL_DIR/flash_daemon.py"
    ok "flash_daemon.py installiert"
else
    warn "flash_daemon.py nicht gefunden — Flash-Funktion nicht verfügbar"
fi

# Ausführbar machen
chmod +x "$INSTALL_DIR/"*.py 2>/dev/null || true

# __init__.py für Python-Paket
touch "$INSTALL_DIR/rpi_zero_node/__init__.py"

ok "Projektdateien installiert"

# ══════════════════════════════════════════════════════════════════════════════
step "6 | Systemdienst: uart-receiver (startet bei jedem Boot)"
# ══════════════════════════════════════════════════════════════════════════════
#
#  Ein systemd-Service läuft automatisch nach dem Boot, überwacht den Prozess
#  und startet ihn bei Absturz neu. Logs sind abrufbar mit:
#    journalctl -u uart-receiver -f

cat > /etc/systemd/system/${SERVICE_RECV}.service << SVCEOF
[Unit]
Description=Power Debug UART Receiver (Node ${NODE_ID})
Documentation=https://github.com/dein-projekt/power-debug
# Erst starten wenn Netzwerk verfügbar (WLAN-Verbindung steht)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}

# NODE_ID und RPI5_IP als Umgebungsvariablen (werden in uart_receiver.py gelesen)
Environment="NODE_ID=${NODE_ID}"
Environment="RPI5_IP=${RPI5_IP}"
Environment="PYTHONUNBUFFERED=1"

# Startbefehl
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/uart_receiver.py

# Bei Fehler: nach 5 Sekunden neu starten (max. 5× pro Minute)
Restart=on-failure
RestartSec=5s
StartLimitInterval=60s
StartLimitBurst=5

# Ausgabe ins Journal (abrufbar mit: journalctl -u uart-receiver)
StandardOutput=journal
StandardError=journal
SyslogIdentifier=uart-receiver

[Install]
# Wird beim normalen Systemstart aktiviert
WantedBy=multi-user.target
SVCEOF

ok "uart-receiver.service erstellt"

# ══════════════════════════════════════════════════════════════════════════════
step "7 | Systemdienst: flash-daemon (Firmware-OTA-Flash)"
# ══════════════════════════════════════════════════════════════════════════════

if [[ -f "$INSTALL_DIR/flash_daemon.py" ]]; then
    cat > /etc/systemd/system/${SERVICE_FLASH}.service << SVCEOF
[Unit]
Description=Power Debug Flash Daemon (Node ${NODE_ID})
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
    warn "flash_daemon.py fehlt — flash-daemon.service wird übersprungen"
fi

# ══════════════════════════════════════════════════════════════════════════════
step "8 | Dienste aktivieren & starten"
# ══════════════════════════════════════════════════════════════════════════════

# systemd-Konfiguration neu laden
systemctl daemon-reload

# uart-receiver aktivieren (startet ab nächstem Boot automatisch)
systemctl enable ${SERVICE_RECV}.service
ok "uart-receiver aktiviert (startet bei Boot)"

# Flash-Daemon aktivieren (falls vorhanden)
if [[ -f /etc/systemd/system/${SERVICE_FLASH}.service ]]; then
    systemctl enable ${SERVICE_FLASH}.service
    ok "flash-daemon aktiviert (startet bei Boot)"
fi

# ── Optional: Jetzt sofort starten ───────────────────────────────────────────
#  Der UART (ttyAMA0) ist erst nach dem Reboot korrekt konfiguriert.
#  Der Dienst wird deshalb erst NACH dem Reboot automatisch gestartet.
warn "Dienste werden erst nach 'sudo reboot' gestartet"
warn "(UART-Konfiguration erfordert Neustart)"

# ══════════════════════════════════════════════════════════════════════════════
step "9 | Konfiguration verifizieren"
# ══════════════════════════════════════════════════════════════════════════════

echo ""
info "──── Einträge in $CONFIG ────"
grep -E "dtoverlay|enable_uart|dtparam=spi|uart0" "$CONFIG" | \
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
    echo "   ❌ pyserial nicht gefunden"
python3 -c "import RPi.GPIO as G; print(f'   ✅ RPi.GPIO {G.VERSION}')" 2>/dev/null || \
    echo "   ❌ RPi.GPIO nicht gefunden"

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║   ✅  Setup Node ${NODE_ID} abgeschlossen!                   ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║   Nächste Schritte:                                  ║"
echo "║     1. sudo reboot                                   ║"
echo "║     2. Auf LEDs achten:                              ║"
echo "║        🔵 Blau AN     = WLAN zu RPi 5 verbunden      ║"
echo "║        🟡 Gelb blinkt = Teensy sendet UART-Daten     ║"
echo "║                                                      ║"
echo "║   Diagnose nach Reboot:                              ║"
echo "║     journalctl -u uart-receiver -f                   ║"
echo "║     ls -la /dev/ttyAMA0                              ║"
echo "║                                                      ║"
echo "║   Verdrahtung Teensy ↔ RPi Zero W:                   ║"
echo "║     Teensy Pin 1 (TX) → RPi Pin 10 (GPIO15, RX)     ║"
echo "║     Teensy Pin 0 (RX) ← RPi Pin  8 (GPIO14, TX)     ║"
echo "║     GND               ─  RPi Pin  6 (GND)           ║"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
