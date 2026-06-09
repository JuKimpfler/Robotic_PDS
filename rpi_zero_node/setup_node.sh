#!/usr/bin/env bash
# ============================================================
#  Power Debug System — RPi Zero W Node Setup  (v2)
# ============================================================
#  Richtet einen RPi Zero W Debug-Node ein:
#    1. Hostname setzen
#    2. SPI aktivieren
#    3. Pakete installieren (inkl. teensy_loader_cli)
#    4. WLAN-Konfiguration (verbinde mit RPi-5-Hotspot)
#    5. Statische IP konfigurieren
#    6. Skripte installieren (inkl. status_leds.py)
#    7. systemd Services einrichten
#
#  Aufruf: sudo bash setup_node.sh <NODE_ID>
#          NODE_ID = 1  →  IP 192.168.42.11, Port 5001/6001
#          NODE_ID = 2  →  IP 192.168.42.12, Port 5002/6002
#
#  Voraussetzung: Raspberry Pi OS Lite (64-bit), frische Installation
#
#  LED-Belegung nach Setup (BCM-Pins):
#    GPIO 27 (Pin 13) → Grüne LED  (Heartbeat)
#    GPIO 22 (Pin 15) → Blaue LED  (WLAN-Status)
#    GPIO 24 (Pin 18) → Gelbe LED  (Daten-Aktivität)
#    GPIO 25 (Pin 22) → Rote LED   (Flash / Fehler)
#    Widerstand: 330 Ω in Serie pro LED
# ============================================================
set -euo pipefail

# ── Parameter & Prüfung ───────────────────────────────────────────────────────
NODE_ID="${1:-}"
if [[ -z "$NODE_ID" || ( "$NODE_ID" != "1" && "$NODE_ID" != "2" ) ]]; then
    echo "Fehler: NODE_ID muss 1 oder 2 sein."
    echo "Aufruf: sudo bash setup_node.sh <1|2>"
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "Fehler: Bitte als root ausführen (sudo)."
    exit 1
fi

HOSTNAME="debug-node-${NODE_ID}"
STATIC_IP="192.168.42.1${NODE_ID}"      # .11 oder .12
GATEWAY="192.168.42.1"                  # RPi 5 (AP)
SSID="PowerDebugAP"
PSK="HighSpeedDebug123"
INSTALL_DIR="/home/pi/power_debug"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  Power Debug System — RPi Zero W Node ${NODE_ID} Setup         ║"
echo "╠════════════════════════════════════════════════════════╣"
echo "║  Hostname : ${HOSTNAME}                       ║"
echo "║  IP       : ${STATIC_IP}                     ║"
echo "║  WLAN     : ${SSID}                    ║"
echo "║  SPI      : GPIO11/10/9/8, DATA_READY=GPIO17  ║"
echo "║  LEDs     : GPIO27/22/24/25 (je 330Ω)         ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""


# ── 1. Hostname ───────────────────────────────────────────────────────────────
echo "[1/7] Setze Hostname: ${HOSTNAME}"
echo "$HOSTNAME" > /etc/hostname
if grep -q "127\.0\.1\.1" /etc/hosts; then
    sed -i "s/127\.0\.1\.1.*/127.0.1.1\t${HOSTNAME}/" /etc/hosts
else
    echo "127.0.1.1	${HOSTNAME}" >> /etc/hosts
fi


# ── 2. SPI aktivieren ─────────────────────────────────────────────────────────
echo "[2/7] Aktiviere SPI-Interface"
BOOT_CONFIG="/boot/firmware/config.txt"
[[ -f "$BOOT_CONFIG" ]] || BOOT_CONFIG="/boot/config.txt"

if ! grep -q "^dtparam=spi=on" "$BOOT_CONFIG"; then
    echo ""                            >> "$BOOT_CONFIG"
    echo "# Power Debug: SPI für Teensy" >> "$BOOT_CONFIG"
    echo "dtparam=spi=on"              >> "$BOOT_CONFIG"
    echo "  → SPI aktiviert in ${BOOT_CONFIG}"
else
    echo "  → SPI bereits aktiviert."
fi


# ── 3. Pakete installieren ────────────────────────────────────────────────────
echo "[3/7] Installiere Pakete"
apt-get update -y -q
apt-get install -y -q \
    python3 python3-pip \
    git build-essential

# Python-Bibliotheken
pip3 install --break-system-packages spidev RPi.GPIO 2>/dev/null \
    || pip3 install spidev RPi.GPIO

# teensy_loader_cli: erst apt versuchen, dann aus Source bauen
if apt-get install -y -q teensy-loader-cli 2>/dev/null; then
    echo "  → teensy-loader-cli via apt installiert."
else
    echo "  → Baue teensy_loader_cli aus Source..."
    apt-get install -y -q libusb-dev
    if [[ ! -f /usr/local/bin/teensy_loader_cli ]]; then
        git clone --depth=1 https://github.com/PaulStoffregen/teensy_loader_cli \
            /tmp/teensy_loader_cli
        make -C /tmp/teensy_loader_cli
        cp /tmp/teensy_loader_cli/teensy_loader_cli /usr/local/bin/
        echo "  → teensy_loader_cli nach /usr/local/bin/ installiert."
    else
        echo "  → teensy_loader_cli bereits vorhanden."
    fi
fi


# ── 4. WLAN konfigurieren (verbinde mit RPi-5-Hotspot) ───────────────────────
echo "[4/7] Konfiguriere WLAN → ${SSID}"

# Prüfen ob NetworkManager oder dhcpcd/wpa_supplicant verwendet wird
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
    # NetworkManager-Variante (modernere Raspbian-Versionen)
    echo "  → Verwende NetworkManager"
    nmcli connection delete "$SSID" 2>/dev/null || true
    nmcli connection add \
        type wifi \
        con-name "$SSID" \
        ifname wlan0 \
        ssid "$SSID" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$PSK" \
        ipv4.method manual \
        ipv4.addresses "${STATIC_IP}/24" \
        ipv4.gateway "$GATEWAY" \
        ipv4.dns "$GATEWAY" \
        connection.autoconnect yes
    nmcli connection up "$SSID" 2>/dev/null || echo "  → WLAN wird nach Neustart verbunden."
else
    # wpa_supplicant-Variante (älteres Raspberry Pi OS)
    echo "  → Verwende wpa_supplicant"
    cat > /etc/wpa_supplicant/wpa_supplicant.conf << WPAEOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=DE

network={
    ssid="${SSID}"
    psk="${PSK}"
    key_mgmt=WPA-PSK
    priority=100
}
WPAEOF

    # ── 5a. Statische IP via dhcpcd ──────────────────────────────────────────
    echo "[5/7] Setze statische IP via dhcpcd: ${STATIC_IP}"
    sed -i '/^interface wlan0$/,/^$/d' /etc/dhcpcd.conf
    cat >> /etc/dhcpcd.conf << IPEOF

interface wlan0
static ip_address=${STATIC_IP}/24
static routers=${GATEWAY}
static domain_name_servers=${GATEWAY}
IPEOF
    echo "  → dhcpcd konfiguriert."
fi


# ── 5. Statische IP (für NetworkManager bereits in Schritt 4) ────────────────
echo "[5/7] Statische IP: ${STATIC_IP} — OK (in Schritt 4 konfiguriert)"


# ── 6. Skripte installieren ──────────────────────────────────────────────────
echo "[6/7] Installiere Power-Debug-Skripte → ${INSTALL_DIR}"
mkdir -p "$INSTALL_DIR"

# Quelldateien ermitteln (Skriptverzeichnis oder rpi_zero_node/)
SRC_DIR="$SCRIPT_DIR"
if [[ -d "${SCRIPT_DIR}/rpi_zero_node" ]]; then
    SRC_DIR="${SCRIPT_DIR}/rpi_zero_node"
fi

# Alle Node-Dateien kopieren
REQUIRED_FILES=("spi_receiver.py" "flash_daemon.py" "status_leds.py")
MISSING=()

for f in "${REQUIRED_FILES[@]}"; do
    if [[ -f "${SRC_DIR}/${f}" ]]; then
        cp "${SRC_DIR}/${f}" "${INSTALL_DIR}/"
        echo "  ✓ ${f}"
    elif [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/"
        echo "  ✓ ${f} (aus SCRIPT_DIR)"
    else
        MISSING+=("$f")
        echo "  ✗ ${f} NICHT GEFUNDEN"
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo ""
    echo "WARNUNG: Folgende Dateien fehlen und müssen manuell nach ${INSTALL_DIR}/ kopiert werden:"
    for f in "${MISSING[@]}"; do
        echo "  → ${f}"
    done
fi

chmod +x "${INSTALL_DIR}/"*.py 2>/dev/null || true

# NODE_ID als persistente Umgebungsvariable
if grep -q "^NODE_ID=" /etc/environment 2>/dev/null; then
    sed -i "s/^NODE_ID=.*/NODE_ID=${NODE_ID}/" /etc/environment
else
    echo "NODE_ID=${NODE_ID}" >> /etc/environment
fi

# RPI5_IP als Umgebungsvariable
if grep -q "^RPI5_IP=" /etc/environment 2>/dev/null; then
    sed -i "s/^RPI5_IP=.*/RPI5_IP=${GATEWAY}/" /etc/environment
else
    echo "RPI5_IP=${GATEWAY}" >> /etc/environment
fi

echo "  → Umgebungsvariablen: NODE_ID=${NODE_ID}, RPI5_IP=${GATEWAY}"


# ── 7. systemd Services ───────────────────────────────────────────────────────
echo "[7/7] Richte systemd Services ein"

# ── spi-receiver.service ──────────────────────────────────────────────────────
cat > /etc/systemd/system/spi-receiver.service << SVCEOF
[Unit]
Description=Power Debug SPI Receiver — Node ${NODE_ID}
Documentation=https://github.com/your-repo/power_debug_system
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
# Umgebungsvariablen aus /etc/environment laden
EnvironmentFile=/etc/environment
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/spi_receiver.py
Restart=always
RestartSec=5
# Ausgabe ins Journal
StandardOutput=journal
StandardError=journal
SyslogIdentifier=spi-receiver-n${NODE_ID}
# Sicherheits-Limits
LimitNOFILE=4096
Nice=-5

[Install]
WantedBy=multi-user.target
SVCEOF

# ── flash-daemon.service ──────────────────────────────────────────────────────
cat > /etc/systemd/system/flash-daemon.service << SVCEOF
[Unit]
Description=Power Debug Flash Daemon — Node ${NODE_ID}
Documentation=https://github.com/your-repo/power_debug_system
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
EnvironmentFile=/etc/environment
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/flash_daemon.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=flash-daemon-n${NODE_ID}
LimitNOFILE=1024

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable spi-receiver.service
systemctl enable flash-daemon.service
echo "  → Services aktiviert (starten nach Neustart automatisch)"


# ── Abschluss ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅  Setup für Node ${NODE_ID} abgeschlossen!                        ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Neustart:   sudo reboot                                     ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Services nach Neustart prüfen:                              ║"
echo "║    journalctl -u spi-receiver -f                             ║"
echo "║    journalctl -u flash-daemon  -f                            ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  LED-Bedeutung nach Boot:                                    ║"
echo "║    Alle 3× blinken → Dienste bereit                          ║"
echo "║    Grün blinkt 1Hz → System OK                               ║"
echo "║    Blau AN         → WLAN verbunden                          ║"
echo "║    Gelb blinkt     → Teensy sendet Daten                     ║"
echo "║    Rot AN/blinkt   → Flash-Vorgang / Fehler                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
