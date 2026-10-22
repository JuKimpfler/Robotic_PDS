#!/usr/bin/env bash
# ==============================================================================
#  update.sh — Power Debug System auf DIESEM Geraet aktualisieren
# ==============================================================================
#  Ein Befehl fuer Node und Haupt-Pi. Was hier installiert ist, steht in
#  /etc/pds/pds.conf (vom Setup geschrieben; aeltere Installationen werden
#  an ihren Diensten erkannt).
#
#    sudo bash update.sh              neuen Stand holen (git pull), installieren,
#                                     Dienste bzw. GUI neu starten
#    sudo bash update.sh --no-pull    nur das installieren, was hier liegt
#                                     (so ruft deploy.sh es auf)
#    sudo bash update.sh --rollback   den Stand VOR dem letzten Update zurueck
#    sudo bash update.sh --status     anzeigen, was installiert ist
#
#  Weitere Optionen:
#    --branch NAME     vor dem Pull auf diesen Branch wechseln
#    --no-restart      installieren, aber nichts neu starten
#
#  Was ein Update NICHT anfasst: Bootkonfiguration (UART/Bluetooth), WLAN,
#  apt-Pakete, settings.json/Profile, runtime_config/, controller_config.json,
#  gespeicherte param_defaults.h und den Bluetooth-Auth-Token. Dafuer ist das
#  Setup da — und es muss dafuer nie wieder laufen.
#
#  Sicherheitsnetz: vor dem Kopieren wird der alte Stand nach <dir>.prev
#  gesichert. Laesst sich der neue Code nicht uebersetzen oder kommt der
#  Node-Dienst danach nicht hoch, wird automatisch zurueckgerollt.
# ==============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pds_common.sh
source "$REPO_DIR/scripts/pds_common.sh"

step() { echo -e "\n\033[1m━━━  $*  ━━━\033[0m"; }

DO_PULL=true
DO_RESTART=true
BRANCH=""
MODE=update
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pull)    DO_PULL=false ;;
        --no-restart) DO_RESTART=false ;;
        --branch)     BRANCH="${2:?--branch braucht einen Namen}"; shift ;;
        --rollback)   MODE=rollback ;;
        --status)     MODE=status ;;
        -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
        *)            err "Unbekannte Option: $1"; exit 1 ;;
    esac
    shift
done

if [[ $EUID -ne 0 && -z "${PDS_ALLOW_NONROOT:-}" ]]; then
    err "Bitte mit sudo ausführen: sudo bash $0 $*"
    exit 1
fi

# ── Was ist hier installiert? ─────────────────────────────────────────────────
ROLE="" NODE_ID="" INSTALL_DIR="" SERVICE_USER="" BT_CHANNEL=""
# Die Rollen-Datei nennt auch das Repository, aus dem zuletzt installiert
# wurde. Massgeblich ist aber IMMER der Ordner, in dem dieses update.sh
# liegt — sonst installierte ein per deploy.sh geschickter Stand den alten.
SOURCE_DIR="$REPO_DIR"
if ! pds_conf_load; then
    if pds_detect_legacy; then
        info "Ältere Installation erkannt (${ROLE}${NODE_ID:+ $NODE_ID}) — Rollen-Datei wird angelegt."
    else
        err "Auf diesem Gerät ist noch nichts installiert."
        err "  Haupt-Pi:  sudo bash setup_rpi5.sh"
        err "  Node:      cd rpi_zero_node && sudo bash setup_node.sh <1|2>"
        exit 1
    fi
fi
BT_CHANNEL="${BT_CHANNEL:-4}"
REPO_DIR="$SOURCE_DIR"

save_conf() {
    if [[ "$ROLE" == node ]]; then
        pds_conf_write ROLE=node NODE_ID="$NODE_ID" INSTALL_DIR="$INSTALL_DIR" \
                       BT_CHANNEL="$BT_CHANNEL" REPO_DIR="$REPO_DIR"
    else
        pds_conf_write ROLE=monitor INSTALL_DIR="$INSTALL_DIR" \
                       SERVICE_USER="$SERVICE_USER" REPO_DIR="$REPO_DIR"
    fi
}

describe() {
    echo "Gerät:       ${ROLE}${NODE_ID:+ (Node $NODE_ID)}"
    echo "Installiert: ${INSTALL_DIR}"
    echo "Version:     $(head -n1 "$INSTALL_DIR/VERSION" 2>/dev/null || echo unbekannt)"
    [[ -d "${INSTALL_DIR}.prev" ]] && \
        echo "Rückweg:     $(head -n1 "${INSTALL_DIR}.prev/VERSION" 2>/dev/null || echo 'älterer Stand') (--rollback)"
    if [[ "$ROLE" == node ]] && command -v systemctl >/dev/null; then
        echo "uart-receiver:     $(systemctl is-active uart-receiver 2>/dev/null || true)"
        echo "bt-flash-receiver: $(systemctl is-active bt-flash-receiver 2>/dev/null || true)"
    fi
    return 0
}

if [[ "$MODE" == status ]]; then
    describe
    exit 0
fi

# ── Neustart: Node-Dienste bzw. laufende GUI ──────────────────────────────────
restart_node() {
    local svc ok_all=true
    systemctl daemon-reload
    for svc in uart-receiver bt-flash-receiver; do
        [[ -f "$PDS_SYSTEMD_DIR/$svc.service" ]] || continue
        systemctl enable "$svc" >/dev/null 2>&1 || true
        systemctl restart "$svc" || true
    done
    sleep 3
    if ! systemctl is-active --quiet uart-receiver; then
        ok_all=false
        err "uart-receiver läuft nach dem Neustart nicht:"
        journalctl -u uart-receiver -n 15 --no-pager 2>/dev/null || true
    fi
    $ok_all
}

# Die GUI laeuft in der Desktop-Sitzung des Benutzers, nicht als Dienst. Um
# sie neu zu starten, wird ihre Umgebung (Display, Wayland-Socket, ...) aus
# dem laufenden Prozess uebernommen, der Prozess beendet und der Launcher
# mit genau dieser Umgebung neu gestartet.
restart_monitor() {
    local pid envs=() var
    pid="$(pgrep -f "python3 main_qml.py" | head -n1 || true)"
    if [[ -z "$pid" ]]; then
        info "Die GUI läuft gerade nicht — sie startet mit dem neuen Stand beim nächsten Login."
        return 0
    fi
    local user
    user="$(ps -o user= -p "$pid" | tr -d ' ')"
    for var in DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS XAUTHORITY; do
        local val
        val="$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | sed -n "s/^${var}=//p" | head -n1)"
        [[ -n "$val" ]] && envs+=("${var}=${val}")
    done
    info "Beende laufende GUI (PID $pid, Benutzer $user) ..."
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
    sudo -u "$user" env "${envs[@]}" PDS_NO_WAIT=1 \
        setsid "$PDS_BIN_DIR/power-debug-monitor" >/dev/null 2>&1 < /dev/null &
    sleep 4
    if pgrep -f "python3 main_qml.py" >/dev/null; then
        ok "GUI mit dem neuen Stand gestartet."
    else
        warn "GUI ist nicht wieder hochgekommen — von Hand starten: power-debug-monitor"
        warn "  (Fehlermeldungen dann direkt im Terminal)"
    fi
}

restart_all() {
    $DO_RESTART || { info "Neustart übersprungen (--no-restart)."; return 0; }
    if [[ "$ROLE" == node ]]; then restart_node; else restart_monitor; fi
}

# ── Rueckweg ──────────────────────────────────────────────────────────────────
if [[ "$MODE" == rollback ]]; then
    step "Zurück auf den vorherigen Stand"
    pds_restore "$INSTALL_DIR"
    ok "Wiederhergestellt: $(head -n1 "$INSTALL_DIR/VERSION" 2>/dev/null || echo 'vorheriger Stand')"
    restart_all
    exit 0
fi

# ── 1) Neuen Stand holen ──────────────────────────────────────────────────────
step "1/4  Quellstand"
if $DO_PULL && git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    # Als Besitzer des Repos ausfuehren: git verweigert sonst als root die
    # Arbeit in einem fremden Verzeichnis ("dubious ownership").
    OWNER="$(stat -c %U "$REPO_DIR")"
    as_owner() { if [[ "$OWNER" == "$(id -un)" ]]; then "$@"; else sudo -u "$OWNER" "$@"; fi; }
    if [[ -n "$BRANCH" ]]; then
        as_owner git -C "$REPO_DIR" fetch origin "$BRANCH"
        as_owner git -C "$REPO_DIR" checkout "$BRANCH"
    fi
    if as_owner git -C "$REPO_DIR" pull --ff-only; then
        ok "git pull erfolgreich."
    else
        warn "git pull nicht möglich (kein Internet oder lokale Änderungen) — installiere den vorhandenen Stand."
    fi
else
    info "Kein git pull (--no-pull oder kein git-Repository)."
fi
VERSION_STR="$(pds_version_of "$REPO_DIR")"
info "Stand: ${VERSION_STR}"

# ── 2) Sichern und installieren ───────────────────────────────────────────────
step "2/4  Installieren nach ${INSTALL_DIR}"
pds_backup "$INSTALL_DIR"
if [[ "$ROLE" == node ]]; then
    pds_install_node_files "$REPO_DIR" "$INSTALL_DIR" "$VERSION_STR"
    if pds_write_node_services "$NODE_ID" "$INSTALL_DIR" "$BT_CHANNEL"; then
        info "Dienst-Definitionen aktualisiert."
    fi
else
    pds_install_monitor_files "$REPO_DIR/rpi5_monitor/64Bit_Version" "$INSTALL_DIR" \
                              "$SERVICE_USER" "$VERSION_STR"
    pds_write_monitor_launcher "$INSTALL_DIR"
    pds_write_monitor_autostart
    pds_monitor_requirements "$REPO_DIR/requirements.txt"
fi
save_conf
ok "Dateien installiert."

# ── 3) Pruefen ────────────────────────────────────────────────────────────────
step "3/4  Prüfen"
if ! pds_verify_python "$INSTALL_DIR"; then
    err "Der neue Stand lässt sich nicht übersetzen — zurück auf den alten."
    pds_restore "$INSTALL_DIR"
    exit 1
fi
ok "Python-Dateien übersetzen fehlerfrei."

# ── 4) Neu starten ────────────────────────────────────────────────────────────
step "4/4  Neu starten"
if ! restart_all; then
    if [[ "$ROLE" == node && -d "${INSTALL_DIR}.prev" ]]; then
        err "Neuer Stand läuft nicht — automatischer Rückweg."
        pds_restore "$INSTALL_DIR"
        restart_node || true
    fi
    exit 1
fi

echo ""
describe
ok "Update abgeschlossen."
