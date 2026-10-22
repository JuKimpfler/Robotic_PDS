#!/usr/bin/env bash
# ================================================================
#  Power Debug System — Raspberry Pi 4 (2 GB) / Pi 5 Setup
# ================================================================
#  Richtet den Raspberry Pi (Pi 4 2GB / Pi 5) als zentralen Debug-Monitor ein:
#    1. Hostname setzen
#    2. Systempakete
#    3. Python-Abhängigkeiten
#    4. Anwendungsdateien installieren
#    5. WLAN: externes Netz (Standard) ODER eigener Access Point (--ap)
#    6. Launcher-Skript erstellen
#    7. Autostart für Desktop (XDG / LXDE / labwc)
#    8. Autologin konfigurieren
#
#  Installiert/startet die PyQt6 + Qt Quick/QML-Oberfläche
#  (rpi5_monitor/64Bit_Version/main_qml.py). Der Live-Plotter nutzt
#  pyqtgraph (siehe bridge/plot_host.py) — eine PFLICHT-Abhängigkeit
#  (requirements.txt), die zwingend QApplication braucht.
#
#  Aufruf:  sudo bash setup_rpi5.sh [--ap] [--yes] [INSTALL_DIR]
#           --ap    den Pi selbst als WLAN-Access-Point betreiben
#                   (SSID/Passwort wie in rpi_zero_node/setup_node.sh,
#                   Pi unter 192.168.42.1). Ohne --ap wird nur ein
#                   Client-Profil für ein EXTERNES WLAN gleichen Namens
#                   angelegt (Router am Spielfeld) — so wie es seit der
#                   Umstellung auf ein externes Netz Standard ist.
#           --yes   keine Rückfragen (für unbeaufsichtigte Installation)
#           Standard-Installationsverzeichnis: /opt/power_debug_monitor
#
#  Voraussetzung: Raspberry Pi OS Bookworm oder Trixie (64-bit, mit Desktop)
#
#  Das Skript ist wiederholbar: ein erneuter Lauf (z. B. nach `git pull`)
#  aktualisiert den Code, lässt aber settings.json, die Profile,
#  runtime_config/, controller_config.json und param_defaults.h im
#  Installationsverzeichnis unangetastet.
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


# ── Argumente ────────────────────────────────────────────────────────────────
SETUP_AP=false
ASSUME_YES=false
INSTALL_DIR="/opt/power_debug_monitor"
for arg in "$@"; do
    case "$arg" in
        --ap)       SETUP_AP=true ;;
        -y|--yes)   ASSUME_YES=true ;;
        -h|--help)  sed -n '2,32p' "$0"; exit 0 ;;
        -*)         err "Unbekannte Option: $arg"; exit 1 ;;
        *)          INSTALL_DIR="$arg" ;;
    esac
done
# Ohne Terminal (z. B. per ssh-Befehl oder Pipe) gibt es niemanden, der
# antworten koennte — `read` liefe dann ins Dateiende und `set -e` braeche
# das Skript an genau dieser Stelle kommentarlos ab.
[[ -t 0 ]] || ASSUME_YES=true

confirm() {   # confirm "Frage" -> 0 = ja
    $ASSUME_YES && return 0
    local answer=""
    read -rp "  $1 [j/N] " answer || return 1
    [[ "$answer" =~ ^[jJyY]$ ]]
}

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
if [[ -n "$MODEL" && ! "$MODEL" =~ Raspberry\ Pi\ [45] ]]; then
    warn "Dieses Skript ist für Raspberry Pi 4 / Pi 5 gedacht (erkannt: ${MODEL})."
    confirm "Trotzdem fortfahren?" || exit 0
fi

# ── Variablen ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Gemeinsame Installationsschritte mit update.sh (Code kopieren, Launcher,
# Autostart, Rollen-Datei) — siehe scripts/pds_common.sh.
# shellcheck source=scripts/pds_common.sh
source "${SCRIPT_DIR}/scripts/pds_common.sh"
SERVICE_USER="${SUDO_USER:-pi}"
if ! HOME_DIR="$(getent passwd "$SERVICE_USER" | cut -d: -f6)" || [[ -z "$HOME_DIR" ]]; then
    err "Benutzer '${SERVICE_USER}' existiert nicht — bitte per 'sudo' aus dem"
    err "Desktop-Benutzerkonto starten (SUDO_USER bestimmt, wer die GUI startet)."
    exit 1
fi

# Netzwerk-Konfiguration
# WICHTIG: SSID/Passwort MÜSSEN mit rpi_zero_node/setup_node.sh (AP_SSID/
# AP_PASS) übereinstimmen. Wird die GUI stattdessen auf einem Windows-PC
# betrieben, muss dessen Mobile Hotspot dieselbe SSID/dasselbe Passwort
# verwenden (siehe README, Abschnitt "PC Setup").
AP_SSID="RoboDebug"
AP_PASS="robodebug123"
AP_IP="192.168.42.1"
WIFI_COUNTRY="DE"   # Regulatory-Domain — ohne diese startet der AP oft nicht

if $SETUP_AP; then WLAN_MODE="Access Point ${AP_SSID} (${AP_IP})"
else WLAN_MODE="externes WLAN ${AP_SSID} (Client)"; fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Power Debug Monitor — Raspberry Pi 4/5 Setup         ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
printf  "${CYAN}║  %-56s║${NC}\n" "Install-Dir : ${INSTALL_DIR}"
printf  "${CYAN}║  %-56s║${NC}\n" "Service-User: ${SERVICE_USER}"
printf  "${CYAN}║  %-56s║${NC}\n" "Home-Dir    : ${HOME_DIR}"
printf  "${CYAN}║  %-56s║${NC}\n" "WLAN        : ${WLAN_MODE}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
confirm "Installation starten?" || exit 0


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 1 — Hostname
# ════════════════════════════════════════════════════════════════════════════════
step "1/8  Hostname konfigurieren"
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
step "2/8  Systempakete installieren"
apt-get update -y -q 2>&1 | tail -1
# libxcb-cursor0: von der Qt6-XCB-Plattform (PyQt6/Qt Quick) benötigt —
# ohne dieses Paket startet main_qml.py auf schlanken Images gar nicht
# ("could not load the Qt platform plugin xcb").
apt-get install -y -q \
    python3 python3-pip python3-venv git curl \
    network-manager \
    libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 \
    libxcb-cursor0 \
    xorg lightdm
ok "Systempakete installiert."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 3 — Python-Abhängigkeiten
# ════════════════════════════════════════════════════════════════════════════════
step "3/8  Python-Pakete installieren"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"

# PyQt6, numpy und pyqtgraph zuerst aus dem apt-Repo: die Pakete sind fuer
# den Pi vorkompiliert, waehrend pip auf arm64 im schlechtesten Fall
# stundenlang aus dem Quelltext baut. Einzeln, damit ein fehlendes Paket
# (z. B. pyqtgraph auf einem aelteren Image) die anderen nicht mitreisst —
# pip ergaenzt danach, was noch fehlt oder zu alt ist.
info "PyQt6/numpy/pyqtgraph bevorzugt aus dem apt-Repo..."
for PKG in python3-pyqt6 python3-pyqt6.qtquick python3-numpy python3-pyqtgraph; do
    apt-get install -y -q "$PKG" >/dev/null 2>&1 \
        && ok "  ${PKG} (apt)" \
        || warn "  ${PKG} nicht im apt-Repo — pip übernimmt."
done

# Fehlendes/zu altes ergaenzen. Ein Fehlschlag darf das Setup NICHT
# abbrechen (set -e): pygame ist optional, und selbst ein fehlgeschlagenes
# PyQt6 soll die restliche Einrichtung (WLAN, Autostart) nicht verhindern —
# die Fehlermeldung steht dann klar im Log.
# --break-system-packages: seit Bookworm (PEP 668) verweigert pip sonst die
# Installation ins System-Python. Aeltere pip-Versionen kennen die Option
# nicht — dann ohne.
PIP_FLAGS=()
pip3 install --help 2>/dev/null | grep -q -- "--break-system-packages" \
    && PIP_FLAGS+=(--break-system-packages)
if [[ -f "$REQ_FILE" ]]; then
    # Merkt sich den Stand von requirements.txt: update.sh ruft pip danach
    # nur noch auf, wenn sich die Datei geaendert hat.
    rm -f "$(dirname "$PDS_CONF")/requirements.sha256"
    pds_monitor_requirements "$REQ_FILE"
else
    warn "requirements.txt nicht gefunden — Pakete direkt installieren."
    pip3 install "${PIP_FLAGS[@]}" "PyQt6>=6.4.0" "numpy>=1.24.0" "pyqtgraph>=0.13.0" \
        || warn "PyQt6/numpy/pyqtgraph konnten nicht per pip installiert werden."
    # pygame ist OPTIONAL (nur PS4-Controller) — nie ein Abbruchgrund.
    pip3 install "${PIP_FLAGS[@]}" "pygame>=2.5.0" \
        || warn "pygame nicht installierbar — GUI läuft ohne Controller-Unterstützung."
fi

# Endkontrolle: ohne PyQt6/pyqtgraph startet die GUI nicht bzw. ohne
# Plotter, das muss auffallen.
if python3 -c "import PyQt6.QtQuick" 2>/dev/null; then
    ok "PyQt6 (inkl. QtQuick) verfügbar."
else
    err "PyQt6/QtQuick fehlt — main_qml.py wird nicht starten."
    err "  Nachinstallieren: sudo apt install python3-pyqt6 python3-pyqt6.qtquick"
fi
python3 -c "import pyqtgraph" 2>/dev/null \
    && ok "pyqtgraph verfügbar (Live-Plotter)." \
    || err "pyqtgraph fehlt — der Plotter-Tab bleibt leer (pip3 install pyqtgraph)."
python3 -c "import pygame" 2>/dev/null \
    && ok "pygame verfügbar (PS4-Controller einsatzbereit)." \
    || warn "pygame fehlt — Fast-Params bleiben per Touch bedienbar."
ok "Python-Abhängigkeiten bereit."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 4 — Anwendungsdateien installieren
# ════════════════════════════════════════════════════════════════════════════════
step "4/8  Anwendungsdateien → ${INSTALL_DIR}"

# Quelle: rpi5_monitor/64Bit_Version/ (die PyQt6 + Qt Quick/QML-Oberfläche).
# main_qml.py erwartet config.py/network_worker.py/param_io.py, die
# *_config.json-/*.h-Dateien, visuals_overlays.json und bild/ FLACH im
# selben Verzeichnis (relativ zu __file__ gesucht), sowie die Ordner
# qml/ (inkl. qml/components/) und bridge/ direkt daneben — deshalb wird
# hier bewusst der komplette Ordner 1:1 gespiegelt statt einzelne
# Dateien aufzulisten (bei einer festen Liste wären z.B. qml/UiState.qml
# oder qml/components/BodiesField.qml bei künftigen Erweiterungen sonst
# stillschweigend nicht mit installiert worden).
QML_SRC="${SCRIPT_DIR}/rpi5_monitor/64Bit_Version"
[[ -d "$QML_SRC" ]] || QML_SRC="${SCRIPT_DIR}/64Bit_Version"   # Fallback: flache Struktur

if [[ ! -d "$QML_SRC" ]]; then
    err "Quellverzeichnis nicht gefunden: erwartet rpi5_monitor/64Bit_Version/ neben diesem Skript."
    exit 1
fi
mkdir -p "$INSTALL_DIR"

# Geraetespezifisches bleibt dabei IMMER stehen (settings.json, Profile,
# runtime_config/, controller_config.json, gespeicherte param_defaults.h) —
# siehe pds_install_monitor_files in scripts/pds_common.sh.
VERSION_STR="$(pds_version_of "$SCRIPT_DIR")"
pds_install_monitor_files "$QML_SRC" "$INSTALL_DIR" "$SERVICE_USER" "$VERSION_STR"
ok "qml/, bridge/ und alle Kerndateien nach ${INSTALL_DIR} kopiert (${VERSION_STR})."

# main_qml.py auf Vorhandensein prüfen — ohne diese Datei läuft der
# Launcher (Schritt 6) später ins Leere.
if [[ ! -f "${INSTALL_DIR}/main_qml.py" ]]; then
    err "main_qml.py fehlt in ${INSTALL_DIR} — Installation unvollständig."
    exit 1
fi

ok "Dateien nach ${INSTALL_DIR} installiert."


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 5 — WLAN: externes Netz (Standard) oder eigener Access Point (--ap)
# ════════════════════════════════════════════════════════════════════════════════
#  Die Nodes verbinden sich mit der SSID ${AP_SSID} (rpi_zero_node/setup_node.sh)
#  und bekommen ihre Adresse per DHCP. Wer die SSID stellt, ist egal:
#    * Standard: ein Router am Spielfeld. Der Pi bekommt hier nur ein
#      Client-Profil für dieses Netz. Die Nodes lernen die Adresse der GUI
#      aus den Paketen (Discovery), eine feste IP ist nicht noetig.
#    * --ap: der Pi spannt das Netz selbst auf (NetworkManager "shared",
#      DHCP inklusive, Pi unter ${AP_IP}).
step "5/8  WLAN konfigurieren (${WLAN_MODE})"

systemctl enable --now NetworkManager 2>/dev/null || true

# Regulatory-Domain setzen — ohne gesetztes WLAN-Land verweigert der Kernel
# den AP-Modus haeufig (0 dBm / kein Broadcast) und blockiert auf frischen
# Images das WLAN ganz (rfkill).
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_wifi_country "$WIFI_COUNTRY" \
        && ok "WLAN-Land gesetzt: ${WIFI_COUNTRY}" \
        || warn "WLAN-Land konnte nicht per raspi-config gesetzt werden."
fi
rfkill unblock wifi 2>/dev/null || true

# Bestehende Profile frueherer Laeufe bereinigen (inkl. altem Namen
# "PowerDebugAP"), damit nie AP- und Client-Profil gleichzeitig existieren.
for CON in "PowerDebugAP" "$AP_SSID" "${AP_SSID}-AP" "Hotspot" "WiFi-AP"; do
    nmcli connection delete "$CON" &>/dev/null && info "  Alt-Verbindung '${CON}' entfernt." || true
done

if $SETUP_AP; then
    if nmcli connection add \
            type              wifi \
            ifname            wlan0 \
            con-name          "${AP_SSID}-AP" \
            autoconnect       yes \
            ssid              "$AP_SSID" \
            mode              ap \
            ipv4.method       shared \
            ipv4.addresses    "${AP_IP}/24" \
            wifi-sec.key-mgmt wpa-psk \
            wifi-sec.psk      "$AP_PASS" \
            wifi.band         bg \
            wifi.channel      6 >/dev/null; then
        nmcli connection up "${AP_SSID}-AP" &>/dev/null \
            && ok "AP gestartet: SSID=${AP_SSID}  IP=${AP_IP}" \
            || warn "AP-Profil angelegt, wird nach dem Neustart aktiv."
    else
        err "AP-Profil konnte nicht angelegt werden (nmcli) — WLAN bitte von Hand einrichten."
    fi
else
    # Nur anlegen, NICHT aktivieren: laeuft das Setup selbst gerade ueber
    # ein anderes WLAN (Internet fuer apt/pip), wuerde ein sofortiger
    # Wechsel die eigene Verbindung kappen. NetworkManager verbindet sich
    # automatisch, sobald das Netz in Reichweite ist.
    if nmcli connection add \
            type              wifi \
            ifname            wlan0 \
            con-name          "$AP_SSID" \
            ssid              "$AP_SSID" \
            wifi-sec.key-mgmt wpa-psk \
            wifi-sec.psk      "$AP_PASS" \
            ipv4.method       auto \
            connection.autoconnect yes \
            connection.autoconnect-priority 100 >/dev/null; then
        ok "Client-Profil '${AP_SSID}' angelegt (verbindet automatisch, sobald in Reichweite)."
    else
        warn "Client-Profil konnte nicht angelegt werden — mit '${AP_SSID}' bitte von Hand verbinden."
    fi
fi


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 6 — Launcher-Skript
# ════════════════════════════════════════════════════════════════════════════════
step "6/8  Launcher-Skript erstellen"

pds_write_monitor_launcher "$INSTALL_DIR"
ok "Launcher: /usr/local/bin/power-debug-monitor"


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 7 — Autostart konfigurieren
# ════════════════════════════════════════════════════════════════════════════════
step "7/8  Autostart für Desktop konfigurieren"

# ── A: XDG-Autostart (einziger aktiver Mechanismus) ───────────────────────
# Wird von so gut wie jeder Desktop-Session verarbeitet — auf Raspberry Pi
# OS Bookworm auch vom Standard-Wayland-Compositor (labwc/wayfire), UND
# von klassischem LXDE/X11. Vorher wurde die GUI hier ZUSÄTZLICH noch
# separat in ~/.config/lxsession/LXDE-pi/autostart UND
# ~/.config/labwc/autostart eingetragen — auf Bookworm verarbeitet die
# Desktop-Session i.d.R. aber BEIDES (das XDG-Verzeichnis UND ihre eigene
# autostart-Datei), wodurch power-debug-monitor zweimal gestartet wurde
# ("Doppel-Start"). Jetzt gibt es nur noch diesen einen Eintrag.
pds_write_monitor_autostart
ok "XDG-Autostart: /etc/xdg/autostart/power-debug-monitor.desktop"

# ── Aufräumen: Einträge früherer Skript-Läufe entfernen ───────────────────
# Falls dieses Skript vorher schon einmal (mit der alten, doppelten
# Autostart-Logik) auf diesem Gerät lief, stehen dort noch die
# überflüssigen Zusatz-Einträge — die entfernen wir jetzt, sonst bliebe
# der Doppel-Start trotz des Fixes oben bestehen.
LXDE_AUTOSTART="${HOME_DIR}/.config/lxsession/LXDE-pi/autostart"
if [[ -f "$LXDE_AUTOSTART" ]] && grep -q "power-debug-monitor" "$LXDE_AUTOSTART" 2>/dev/null; then
    sed -i '/power-debug-monitor/d' "$LXDE_AUTOSTART"
    info "  Alten LXDE-Autostart-Eintrag entfernt."
fi
LABWC_AUTOSTART="${HOME_DIR}/.config/labwc/autostart"
if [[ -f "$LABWC_AUTOSTART" ]] && grep -q "power-debug-monitor" "$LABWC_AUTOSTART" 2>/dev/null; then
    sed -i '/power-debug-monitor/d' "$LABWC_AUTOSTART"
    info "  Alten labwc-Autostart-Eintrag entfernt."
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${HOME_DIR}/.config" 2>/dev/null || true
ok "Nur noch EIN Autostart-Mechanismus aktiv (verhindert Doppel-Start)."

# ── B: systemd User-Service (ALTERNATIVE, nicht standardmäßig aktiv) ─────
# Wird nur als Datei angelegt, aber NICHT aktiviert — bewusst eine
# Alternative zu Mechanismus A, keine Ergänzung. Nur verwenden, wenn A
# (XDG-Autostart) stattdessen deaktiviert wird, sonst startet die GUI
# wieder doppelt.
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
ok "systemd User-Service (optional, deaktiviert): ${SYSTEMD_USER_DIR}/power-debug-monitor.service"
info "  NUR als Ersatz für den XDG-Autostart verwenden, nicht zusätzlich:"
info "    sudo rm /etc/xdg/autostart/power-debug-monitor.desktop"
info "    loginctl enable-linger ${SERVICE_USER}"
info "    su ${SERVICE_USER} -c 'systemctl --user enable --now power-debug-monitor'"


# ════════════════════════════════════════════════════════════════════════════════
#  SCHRITT 8 — Autologin aktivieren
# ════════════════════════════════════════════════════════════════════════════════
step "8/8  Desktop-Autologin"

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


# Rollen-Datei: update.sh weiss damit ohne jede Angabe, was hier liegt.
pds_conf_write ROLE=monitor INSTALL_DIR="$INSTALL_DIR" \
               SERVICE_USER="$SERVICE_USER" REPO_DIR="$SCRIPT_DIR"
ok "Rollen-Datei: ${PDS_CONF}"


# ════════════════════════════════════════════════════════════════════════════════
#  Abschlussmeldung
# ════════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅  Raspberry Pi Setup ERFOLGREICH ABGESCHLOSSEN!           ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
printf "${GREEN}║  %-62s║${NC}\n" "WLAN          : ${WLAN_MODE}"
printf "${GREEN}║  %-62s║${NC}\n" "Anwendung     : ${INSTALL_DIR}"
printf "${GREEN}║  %-62s║${NC}\n" "Manuell Start : power-debug-monitor"
printf "${GREEN}║  %-62s║${NC}\n" "Simulate-Mode : power-debug-monitor --simulate"
printf "${GREEN}║  %-62s║${NC}\n" "Update        : sudo bash update.sh"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  ⚠  NEUSTART ERFORDERLICH für:                               ║${NC}"
echo -e "${GREEN}║     • Hostname-Änderung, WLAN-Land, Autologin                ║${NC}"
echo -e "${GREEN}║  → sudo reboot                                               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
