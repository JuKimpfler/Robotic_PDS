#!/usr/bin/env bash
# ================================================================
#  Power Debug System — Raspberry Pi 5 Master Setup
# ================================================================
#  Richtet den RPi 5 als zentralen Debug-Monitor ein:
#    1. Hostname setzen
#    2. Systempakete + Python-Abhängigkeiten
#    3. Anwendungsdateien installieren
#    4. WLAN Access Point konfigurieren (PowerDebugAP)
#    5. USB-C Gadget Mode aktivieren (g_ether)
#    6. Launcher-Skript erstellen
#    7. Autostart für Desktop (XDG / LXDE / labwc)
#    8. Autologin konfigurieren
#    9. Zusammenfassung
#
#  Aufruf:  sudo bash setup_rpi5.sh [INSTALL_DIR]
#           Standard-Installationsverzeichnis: /opt/power_debug_monitor
#
#  Voraussetzung: Raspberry Pi OS Bookworm (64-bit, mit Desktop)
# ================================================================
set -euo pipefail

# ── Terminal-Farben ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERR]${NC}   $*" >&2; }
step()    { echo -e "\n${BOLD}${BLUE}━━━  $*  ━━━${NC}"; }


# ── Root-Prüfung ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Bitte als root ausführen:"
    err "  sudo bash setup_rpi5.sh"
    exit 1
fi

# ── Geräteerkennung ───────────────────────────────────────────────────────────
MODEL=""
[[ -f /proc/device-tree/model ]] && MODEL=$(tr -d '\0' < /proc/device-tree/model)
info "Gerät: ${MODEL:-Unbekannt}"
if [[ -n "$MODEL" && ! "$MODEL" =~ "Raspberry Pi 5" ]]; then
    warn "Dieses Skript ist für den RPi 5 optimiert (erkannt: ${MODEL})."
    read -rp "  Trotzdem fortfahren? [j/N] " CONT
    [[ "$CONT" =~ ^[jJ]$ ]] || exit 0
fi

# ── Variablen ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${1:-/opt/power_debug_monitor}"
SERVICE_USER="${SUDO_USER:-pi}"
HOME_DIR="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"

# Boot-Partition (Bookworm: /boot/firmware, ältere: /boot)
BOOT_DIR="/boot/firmware"
[[ -d "$BOOT_DIR" ]] || BOOT_DIR="/boot"
BOOT_CONFIG="${BOOT_DIR}/config.txt"
BOOT_CMDLINE="${BOOT_DIR}/cmdline.txt"

# Netzwerk-Konfiguration
AP_SSID="PowerDebugAP"
AP_PASS="HighSpeedDebug123"
AP_IP="192.168.42.1"
AP_SUBNET="192.168.42.0/24"
USB_IP="192.168.7.1"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Power Debug Monitor — RPi 5 Setup                   ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
printf  "${CYAN}║  %-56s║${NC}\n" "Install-Dir : ${INSTALL_DIR}"
printf  "${CYAN}║  %-56s║${NC}\n" "Service-User: ${SERVICE_USER}"
printf  "${CYAN}║  %-56s║${NC}\n" "Home-Dir    : ${HOME_DIR}"
printf  "${CYAN}║  %-56s║${NC}\n" "Boot-Config : ${BOOT_CONFIG}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${YELLOW}Weiter mit ENTER, STRG+C zum Abbrechen...${NC}"
read -r


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 1 — Hostname
# ════════════════════════════════════════════════════════════════════════════════
step "1/9  Hostname konfigurieren"
TARGET_HOSTNAME="power-debug-monitor"
echo "$TARGET_HOSTNAME" > /etc/hostname
if grep -q "127\.0\.1\.1" /etc/hosts; then
    sed -i "s/127\.0\.1\.1.*/127.0.1.1\t${TARGET_HOSTNAME}/" /etc/hosts
else
    echo "127.0.1.1	${TARGET_HOSTNAME}" >> /etc/hosts
fi
ok "Hostname: ${TARGET_HOSTNAME}"


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 2 — Systempakete
# ════════════════════════════════════════════════════════════════════════════════
step "2/9  Systempakete installieren"
apt-get update -y -q 2>&1 | tail -1
apt-get install -y -q \
    python3 python3-pip python3-venv git curl \
    network-manager \
    libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 \
    xorg lightdm
ok "Systempakete installiert."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 3 — Python-Abhängigkeiten
# ════════════════════════════════════════════════════════════════════════════════
step "3/9  Python-Pakete installieren"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"
if [[ -f "$REQ_FILE" ]]; then
    pip3 install --break-system-packages -r "$REQ_FILE"
    ok "Pakete aus requirements.txt installiert."
else
    warn "requirements.txt nicht gefunden — Pakete direkt installieren."
    pip3 install --break-system-packages \
        "PyQt6>=6.4.0" \
        "pyqtgraph>=0.13.3" \
        "numpy>=1.24.0"
fi
ok "Python-Abhängigkeiten bereit."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 4 — Anwendungsdateien installieren
# ════════════════════════════════════════════════════════════════════════════════
step "4/9  Anwendungsdateien → ${INSTALL_DIR}"

mkdir -p "${INSTALL_DIR}/gui"

# RPi-5-Hauptdateien kopieren
RPi5_SRC="${SCRIPT_DIR}/rpi5_monitor"
if [[ -d "$RPi5_SRC" ]]; then
    # Verzeichnisstruktur wie im README
    for f in main.py network_worker.py config.py; do
        [[ -f "${RPi5_SRC}/${f}" ]] && cp "${RPi5_SRC}/${f}" "${INSTALL_DIR}/" && info "  ✓ ${f}"
    done
    GUI_SRC="${RPi5_SRC}/gui"
    if [[ -d "$GUI_SRC" ]]; then
        for f in main_window.py tab_table.py tab_plotter.py tab_visuals.py tab_params.py; do
            [[ -f "${GUI_SRC}/${f}" ]] && cp "${GUI_SRC}/${f}" "${INSTALL_DIR}/gui/" && info "  ✓ gui/${f}"
        done
        [[ -f "${GUI_SRC}/__init__.py" ]] && cp "${GUI_SRC}/__init__.py" "${INSTALL_DIR}/gui/"
    fi
else
    # Flache Struktur (alle Dateien im Skriptverzeichnis)
    warn "rpi5_monitor/ nicht gefunden — suche Dateien in ${SCRIPT_DIR}"
    for f in main.py network_worker.py config.py; do
        [[ -f "${SCRIPT_DIR}/${f}" ]] && cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/" && info "  ✓ ${f}"
    done
    for f in main_window.py tab_table.py tab_plotter.py tab_visuals.py tab_params.py; do
        [[ -f "${SCRIPT_DIR}/${f}" ]] && cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/gui/" && info "  ✓ gui/${f}"
    done
fi

# __init__.py sicherstellen
touch "${INSTALL_DIR}/gui/__init__.py"

# Berechtigungen setzen
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
ok "Dateien nach ${INSTALL_DIR} installiert."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 5 — WLAN Access Point
# ════════════════════════════════════════════════════════════════════════════════
step "5/9  WLAN Access Point konfigurieren (${AP_SSID})"

# Sicherstellen dass NetworkManager läuft
systemctl enable --now NetworkManager 2>/dev/null || true

# Bestehende AP-Verbindungen bereinigen
for CON in "PowerDebugAP" "Hotspot" "WiFi-AP"; do
    nmcli connection delete "$CON" 2>/dev/null && info "  Alt-Verbindung '${CON}' entfernt." || true
done

# Neuen Hotspot anlegen
nmcli connection add \
    type            wifi \
    ifname          wlan0 \
    con-name        "PowerDebugAP" \
    autoconnect     yes \
    ssid            "$AP_SSID" \
    mode            ap \
    ipv4.method     shared \
    ipv4.addresses  "${AP_IP}/24" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk    "$AP_PASS" \
    wifi.band       bg \
    wifi.channel    6

# Direkt starten (falls möglich)
nmcli connection up "PowerDebugAP" 2>/dev/null \
    && ok "AP gestartet: SSID=${AP_SSID}  IP=${AP_IP}" \
    || warn "AP wird nach Neustart aktiv."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 6 — USB-C Gadget Mode (g_ether)
# ════════════════════════════════════════════════════════════════════════════════
step "6/9  USB-C Gadget Mode (PC ↔ RPi 5)"

# /boot/firmware/config.txt anpassen
if ! grep -q "dtoverlay=dwc2" "$BOOT_CONFIG"; then
    {
        echo ""
        echo "# ─── Power Debug Monitor: USB OTG Gadget Mode ───"
        echo "dtoverlay=dwc2,dr_mode=peripheral"
    } >> "$BOOT_CONFIG"
    ok "config.txt: dtoverlay=dwc2 hinzugefügt."
else
    warn "dtoverlay=dwc2 bereits in ${BOOT_CONFIG} — übersprungen."
fi

# /boot/firmware/cmdline.txt anpassen
if ! grep -q "modules-load=dwc2" "$BOOT_CMDLINE"; then
    # Modul-Ladung hinter rootwait einfügen (alles eine Zeile!)
    sed -i 's/\(rootwait\)/\1 modules-load=dwc2,g_ether/' "$BOOT_CMDLINE"
    ok "cmdline.txt: modules-load=dwc2,g_ether hinzugefügt."
else
    warn "modules-load=dwc2 bereits in ${BOOT_CMDLINE} — übersprungen."
fi

# usb0-Netzwerkverbindung konfigurieren (aktiv nach erstem Neustart)
nmcli connection delete "usb-gadget" 2>/dev/null || true
nmcli connection add \
    type        ethernet \
    con-name    "usb-gadget" \
    ifname      usb0 \
    ipv4.addresses "${USB_IP}/24" \
    ipv4.method    manual \
    connection.autoconnect yes 2>/dev/null \
    && ok "usb-gadget Verbindung angelegt (${USB_IP})." \
    || warn "usb0 noch nicht vorhanden — wird nach Neustart konfiguriert."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 7 — Launcher-Skript
# ════════════════════════════════════════════════════════════════════════════════
step "7/9  Launcher-Skript erstellen"

cat > /usr/local/bin/power-debug-monitor << LAUNCHER_SCRIPT
#!/usr/bin/env bash
# Power Debug Monitor — Launcher-Wrapper
# Startet die PyQt6-GUI mit korrekten Umgebungsvariablen

# Warte kurz auf Display-Server (wichtig beim Autostart)
sleep 3

# Display-Erkennung: X11 vs. Wayland
if [[ -n "\${WAYLAND_DISPLAY:-}" ]]; then
    export QT_QPA_PLATFORM="wayland;xcb"
else
    export DISPLAY="\${DISPLAY:-:0}"
    export QT_QPA_PLATFORM="xcb"
fi

# Qt-Logging reduzieren (unterdrückt egl/xcb-Warnungen auf RPi)
export QT_LOGGING_RULES="qt.qpa.*=false;qt.network.*=false"

# Anwendungsverzeichnis
INSTALL_DIR="${INSTALL_DIR}"

cd "\$INSTALL_DIR" || exit 1
exec python3 main.py "\$@"
LAUNCHER_SCRIPT

chmod +x /usr/local/bin/power-debug-monitor
ok "Launcher: /usr/local/bin/power-debug-monitor"


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 8 — Autostart konfigurieren
# ════════════════════════════════════════════════════════════════════════════════
step "8/9  Autostart für Desktop konfigurieren"

# ── A: XDG-Autostart (universell, funktioniert bei LXDE, GNOME, labwc) ───────
mkdir -p /etc/xdg/autostart
cat > /etc/xdg/autostart/power-debug-monitor.desktop << DESKTOP_FILE
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
DESKTOP_FILE
ok "XDG-Autostart: /etc/xdg/autostart/power-debug-monitor.desktop"

# ── B: LXDE-Autostart (RPi OS Bullseye/Bookworm mit LXDE-Desktop) ────────────
LXDE_DIR="${HOME_DIR}/.config/lxsession/LXDE-pi"
mkdir -p "$LXDE_DIR"
LXDE_AUTOSTART="${LXDE_DIR}/autostart"
if ! grep -q "power-debug-monitor" "$LXDE_AUTOSTART" 2>/dev/null; then
    echo "@/usr/local/bin/power-debug-monitor" >> "$LXDE_AUTOSTART"
    ok "LXDE-Autostart konfiguriert."
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${HOME_DIR}/.config"

# ── C: labwc-Autostart (Bookworm Standard-Desktop seit 2023) ─────────────────
LABWC_DIR="${HOME_DIR}/.config/labwc"
mkdir -p "$LABWC_DIR"
if ! grep -q "power-debug-monitor" "${LABWC_DIR}/autostart" 2>/dev/null; then
    echo "/usr/local/bin/power-debug-monitor &" >> "${LABWC_DIR}/autostart"
    ok "labwc-Autostart konfiguriert."
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "$LABWC_DIR"

# ── D: systemd User-Service (alternative Startvariante) ──────────────────────
SYSTEMD_USER_DIR="${HOME_DIR}/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
cat > "${SYSTEMD_USER_DIR}/power-debug-monitor.service" << SVCFILE
[Unit]
Description=Power Debug Monitor GUI
After=graphical-session.target network-online.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStartPre=/bin/sleep 4
ExecStart=/usr/local/bin/power-debug-monitor
Restart=on-failure
RestartSec=15
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/%(UID)s

[Install]
WantedBy=graphical-session.target
SVCFILE
# UID einsetzen
SUID=$(id -u "$SERVICE_USER")
sed -i "s|%(UID)s|${SUID}|g" "${SYSTEMD_USER_DIR}/power-debug-monitor.service"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${HOME_DIR}/.config/systemd"
ok "systemd User-Service: ${SYSTEMD_USER_DIR}/power-debug-monitor.service"
info "  Aktivierung: loginctl enable-linger ${SERVICE_USER}"
info "               su ${SERVICE_USER} -c 'systemctl --user enable power-debug-monitor'"


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 9 — Autologin aktivieren
# ════════════════════════════════════════════════════════════════════════════════
step "9/9  Desktop-Autologin"

AUTOLOGIN_SET=false

# Option A: lightdm.conf
if [[ -f /etc/lightdm/lightdm.conf ]]; then
    sed -i \
        -e "s/^#*autologin-user=.*/autologin-user=${SERVICE_USER}/" \
        -e "s/^#*autologin-user-timeout=.*/autologin-user-timeout=0/" \
        /etc/lightdm/lightdm.conf
    ok "LightDM-Autologin für '${SERVICE_USER}' aktiviert."
    AUTOLOGIN_SET=true
fi

# Option B: raspi-config (nur auf echtem RPi verfügbar)
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_boot_behaviour B4 2>/dev/null \
        && { ok "raspi-config: Autologin Desktop aktiviert."; AUTOLOGIN_SET=true; } \
        || warn "raspi-config Autologin: manuell einstellen (raspi-config → System → Boot)."
fi

$AUTOLOGIN_SET || warn "Autologin nicht automatisch konfiguriert → manuell via 'sudo raspi-config'."


# ════════════════════════════════════════════════════════════════════════════════
#  Abschlussmeldung
# ════════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅  Raspberry Pi 5 Setup ERFOLGREICH ABGESCHLOSSEN!         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
printf "${GREEN}║  %-62s║${NC}\n" "WLAN-Hotspot  : ${AP_SSID} → ${AP_IP}"
printf "${GREEN}║  %-62s║${NC}\n" "USB-Gadget    : ${USB_IP} (nach Neustart)"
printf "${GREEN}║  %-62s║${NC}\n" "Anwendung     : ${INSTALL_DIR}"
printf "${GREEN}║  %-62s║${NC}\n" "Manuell Start : power-debug-monitor"
printf "${GREEN}║  %-62s║${NC}\n" "Simulate-Mode : power-debug-monitor --simulate"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  ⚠  NEUSTART ERFORDERLICH für:                               ║${NC}"
echo -e "${GREEN}║     • USB-C Gadget Mode (g_ether)                            ║${NC}"
echo -e "${GREEN}║     • Hostname-Änderung                                      ║${NC}"
echo -e "${GREEN}║  → sudo reboot                                               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
