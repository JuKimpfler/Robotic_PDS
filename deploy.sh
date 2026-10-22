#!/usr/bin/env bash
# ==============================================================================
#  deploy.sh — den Stand DIESES Rechners auf Nodes / Haupt-Pi bringen
# ==============================================================================
#  Laeuft auf dem Entwicklungs-PC (Linux, macOS, Git-Bash unter Windows) oder
#  auf dem Haupt-Pi. Braucht nur ssh und tar — die Zielgeraete brauchen KEIN
#  Internet und kein git. Genau das ist am Spielfeld der Normalfall: die
#  Nodes haengen im Roboter-WLAN, nicht im Internet.
#
#    ./deploy.sh nodes                  beide Nodes aktualisieren
#    ./deploy.sh node1 monitor          Node 1 und den Haupt-Pi
#    ./deploy.sh all                    Nodes und Haupt-Pi
#    ./deploy.sh pi@192.168.42.11       beliebiges Ziel per ssh-Adresse
#    ./deploy.sh --no-restart nodes     nur installieren; Dienste/GUI laufen
#                                       mit dem alten Stand weiter bis zum
#                                       naechsten Neustart (z. B. mitten im Spiel)
#
#    ./deploy.sh --setup-node 1 pi@raspberrypi.local
#                                       FRISCHES Geraet komplett als Node 1
#                                       einrichten (Setup statt Update)
#    ./deploy.sh --setup-monitor pi@raspberrypi.local
#                                       frischen Haupt-Pi einrichten
#
#  Kurznamen und Benutzer:
#    node1   -> ${PDS_SSH_USER}@debug-node-1.local
#    node2   -> ${PDS_SSH_USER}@debug-node-2.local
#    monitor -> ${PDS_SSH_USER}@power-debug-monitor.local
#  Die Hostnamen vergeben die Setup-Skripte; .local loest avahi (mDNS) auf,
#  das auf Raspberry Pi OS vorinstalliert ist. PDS_SSH_USER ist "pi", falls
#  nicht gesetzt. Abweichende Adressen in deploy.conf neben diesem Skript:
#      NODE1=pi@192.168.42.11
#      NODE2=pi@192.168.42.12
#      MONITOR=pi@192.168.42.1
#
#  Ablauf je Ziel: Quellstand packen (nur Dateien, die git kennt, inkl.
#  lokaler Aenderungen) -> per ssh nach ~/pds_deploy entpacken -> dort
#  `sudo bash update.sh --no-pull` (bzw. das Setup). Fuer sudo ohne Passwort
#  ist nichts zu tun: der erste Benutzer von Raspberry Pi OS darf das.
#  Tipp: einmal `ssh-copy-id <ziel>`, dann fragt auch ssh nicht mehr.
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDS_SSH_USER="${PDS_SSH_USER:-pi}"
NODE1="${PDS_SSH_USER}@debug-node-1.local"
NODE2="${PDS_SSH_USER}@debug-node-2.local"
MONITOR="${PDS_SSH_USER}@power-debug-monitor.local"
# shellcheck disable=SC1091
[[ -f "$ROOT/deploy.conf" ]] && source "$ROOT/deploy.conf"

REMOTE_DIR="pds_deploy"
SSH_OPTS=(-o ConnectTimeout=8 -o ServerAliveInterval=5)

c_ok()   { echo -e "\033[0;32m✔\033[0m $*"; }
c_err()  { echo -e "\033[0;31m✘\033[0m $*" >&2; }
c_info() { echo -e "\033[0;36m→\033[0m $*"; }

usage() { sed -n '2,41p' "$0"; }

# ── Quellstand packen ─────────────────────────────────────────────────────────
#  Nur was git kennt (plus lokale Aenderungen daran): keine .pio-Builds,
#  keine __pycache__, keine settings.json des Entwicklungsrechners.
make_bundle() {
    local out="$1" version stage
    stage="$(mktemp -d)"
    if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
        version="$(git -C "$ROOT" describe --always --dirty --tags) ($(git -C "$ROOT" log -1 --format=%cs))"
        (cd "$ROOT" && git ls-files -z --cached --others --exclude-standard \
            | tar --null -T - -cf - ) | tar -C "$stage" -xf -
    else
        version="ohne git ($(date +%F))"
        tar -C "$ROOT" --exclude=.git --exclude=.pio --exclude=__pycache__ \
            --exclude=settings.json --exclude='settings.*.json' \
            --exclude=runtime_config -cf - . | tar -C "$stage" -xf -
    fi
    # VERSION mitschicken: auf dem Ziel gibt es kein .git, aus dem update.sh
    # die Version lesen koennte.
    echo "$version" > "$stage/VERSION"
    tar -C "$stage" -czf "$out" .
    rm -rf "$stage"
    echo "$version"
}

resolve() {
    case "$1" in
        node1)   echo "$NODE1" ;;
        node2)   echo "$NODE2" ;;
        monitor) echo "$MONITOR" ;;
        *)       echo "$1" ;;
    esac
}

# push ZIEL BEFEHL — Paket hinschieben, entpacken, Befehl mit sudo ausfuehren
push() {
    local target="$1" cmd="$2"
    c_info "$target: übertrage ..."
    # shellcheck disable=SC2029  # ~ und $REMOTE_DIR sollen auf dem Ziel gelten
    if ! ssh "${SSH_OPTS[@]}" "$target" \
            "rm -rf ~/$REMOTE_DIR && mkdir -p ~/$REMOTE_DIR && tar -xzf - -C ~/$REMOTE_DIR" \
            < "$BUNDLE"; then
        c_err "$target: nicht erreichbar oder Übertragung fehlgeschlagen."
        return 1
    fi
    c_info "$target: $cmd"
    # -t: sudo und die Setup-Skripte duerfen fragen, Farben bleiben erhalten
    # shellcheck disable=SC2029
    if ssh -t "${SSH_OPTS[@]}" "$target" "cd ~/$REMOTE_DIR && sudo bash $cmd"; then
        c_ok "$target: fertig."
    else
        c_err "$target: fehlgeschlagen (Ausgabe oben)."
        return 1
    fi
}

# ── Argumente ─────────────────────────────────────────────────────────────────
[[ $# -gt 0 ]] || { usage; exit 1; }
JOBS=()   # "ziel|befehl"
UPD="update.sh --no-pull"
for a in "$@"; do
    [[ "$a" == "--no-restart" ]] && UPD="update.sh --no-pull --no-restart"
done
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)       usage; exit 0 ;;
        --no-restart)    ;;   # oben schon ausgewertet
        nodes)           JOBS+=("$NODE1|$UPD" "$NODE2|$UPD") ;;
        all)             JOBS+=("$NODE1|$UPD" "$NODE2|$UPD" "$MONITOR|$UPD") ;;
        --setup-node)    nid="${2:?--setup-node braucht 1 oder 2}"
                         tgt="$(resolve "${3:?--setup-node braucht ein Ziel}")"
                         JOBS+=("$tgt|rpi_zero_node/setup_node.sh $nid"); shift 2 ;;
        --setup-monitor) tgt="$(resolve "${2:?--setup-monitor braucht ein Ziel}")"
                         JOBS+=("$tgt|setup_rpi5.sh"); shift ;;
        -*)              c_err "Unbekannte Option: $1"; exit 1 ;;
        *)               JOBS+=("$(resolve "$1")|$UPD") ;;
    esac
    shift
done

[[ ${#JOBS[@]} -gt 0 ]] || { c_err "Kein Ziel angegeben."; usage; exit 1; }

BUNDLE_DIR="$(mktemp -d)"
BUNDLE="$BUNDLE_DIR/pds.tar.gz"
trap 'rm -rf "$BUNDLE_DIR"' EXIT
VERSION_STR="$(make_bundle "$BUNDLE")"
c_info "Stand: $VERSION_STR  ($(du -h "$BUNDLE" | cut -f1))"

FAILED=()
for job in "${JOBS[@]}"; do
    push "${job%%|*}" "${job#*|}" || FAILED+=("${job%%|*}")
done

echo ""
if [[ ${#FAILED[@]} -eq 0 ]]; then
    c_ok "Alle Ziele aktualisiert."
else
    c_err "Fehlgeschlagen: ${FAILED[*]}"
    exit 1
fi
