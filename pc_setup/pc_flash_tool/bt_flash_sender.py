#!/usr/bin/env python3
"""
bt_flash_sender.py
===================
Windows-PC-Seite des Wireless-Flash-Features (siehe Flash_Implementierung.md).

Sendet ein kompiliertes Teensy-4.0-Firmware-Image (.hex) per Bluetooth Classic
(RFCOMM/SPP) an einen oder beide RPi Zero 2 W Nodes, die die Datei per
`bt_flash_receiver.py` entgegennehmen und via `teensy_loader_cli` flashen.

VORAUSSETZUNG (einmalig, manuell):
  Der/die Node(s) müssen vorher über Windows-Einstellungen
  -> Bluetooth & Geräte -> Gerät hinzufügen -> "PDS-Node1-BT" / "PDS-Node2-BT"
  auswählen und mit PIN koppeln (die PIN wird beim setup_node.sh-Lauf auf dem
  Pi ausgegeben). Siehe README.md in diesem Ordner für die genaue Anleitung.

Verwendung:
    python bt_flash_sender.py firmware.hex --target both
    python bt_flash_sender.py firmware.hex --target node1
    python bt_flash_sender.py firmware.hex --target node2 --targets-file meine_targets.json

Voraussetzungen:
  - Python 3.9+ unter Windows 10/11 (AF_BLUETOOTH/BTPROTO_RFCOMM ist seit
    Python 3.9 nativ unter Windows verfügbar — siehe CPython bpo-36590).
  - Kein PyBluez / keine weiteren Pakete nötig (nur Standardbibliothek).
  - bt_targets.json (im selben Ordner) mit MAC-Adressen/Kanal/Token je Node.

Exit-Code: 0 = alle gewählten Ziele erfolgreich geflasht, 1 = mindestens
ein Ziel fehlgeschlagen, 2 = Konfigurationsfehler (z. B. bt_targets.json fehlt).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import time
from pathlib import Path

# shared/bt_flash_protocol.py liegt zwei Ebenen über diesem Skript
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
try:
    from bt_flash_protocol import Cmd, ProtocolError, recv_frame, send_frame
except ImportError as exc:  # pragma: no cover
    print(f"[FEHLER] bt_flash_protocol.py nicht gefunden ({exc}).")
    print("         Erwartet unter: <Projektwurzel>/shared/bt_flash_protocol.py")
    sys.exit(2)

CHUNK_SIZE = 8192
CONNECT_TIMEOUT = 8.0
HELLO_TIMEOUT = 5.0
CHUNK_TIMEOUT = 10.0
RESULT_TIMEOUT = 30.0  # teensy_loader_cli braucht auf dem Pi etwas Zeit

TARGETS_FILE_DEFAULT = Path(__file__).resolve().parent / "bt_targets.json"

TEMPLATE = {
    "node1": {"mac": "AA:BB:CC:DD:EE:01", "channel": 4, "token": "CHANGE_ME_NODE1_TOKEN"},
    "node2": {"mac": "AA:BB:CC:DD:EE:02", "channel": 4, "token": "CHANGE_ME_NODE2_TOKEN"},
}


def load_targets(path: Path) -> dict:
    if not path.exists():
        path.write_text(json.dumps(TEMPLATE, indent=2), encoding="utf-8")
        print(f"[!] {path} existierte nicht — eine Vorlage wurde angelegt.")
        print("    Bitte MAC-Adresse, Kanal und Auth-Token je Node eintragen.")
        print("    Diese Werte gibt setup_node.sh am Ende des Setup-Laufs auf dem")
        print("    jeweiligen Pi aus (Abschnitt 6/7 im Implementierungsplan).")
        raise SystemExit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def flash_one(
    node_name: str,
    cfg: dict,
    hex_path: Path,
    log_cb=None,
    progress_cb=None,
) -> bool:
    """Verbindet sich mit einem Node und flasht die Datei.

    log_cb(str)                                    -- Textzeile fürs Log
    progress_cb(pct:int, sent:int, size:int, kbs:float) -- Fortschritt je Chunk

    Wenn keine Callbacks übergeben werden, wird auf print() (mit \\r-Fortschritt
    für die Konsole) zurückgefallen — Verhalten der CLI bleibt unverändert.
    """
    log = log_cb or print
    mac = cfg["mac"]
    channel = int(cfg["channel"])
    token = cfg["token"]
    log(f"=== {node_name} ({mac}, Kanal {channel}) ===")

    data = hex_path.read_bytes()
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()

    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    try:
        sock.settimeout(CONNECT_TIMEOUT)
        log("Verbinde ...")
        sock.connect((mac, channel))

        # --- Handshake / Auth ---------------------------------------------
        sock.settimeout(HELLO_TIMEOUT)
        send_frame(sock, Cmd.HELLO, token.encode("utf-8"))
        cmd, payload = recv_frame(sock)
        ack = json.loads(payload.decode("utf-8"))
        if cmd != Cmd.HELLO_ACK or not ack.get("ok"):
            log(f"[FEHLER] Auth/Handshake fehlgeschlagen: {ack.get('msg', payload)}")
            return False
        log(f"Verbunden mit Node {ack.get('node_id', '?')}")

        # --- Flash-Start ankündigen -----------------------------------------
        meta = {"filename": hex_path.name, "size": size, "sha256": sha256}
        send_frame(sock, Cmd.FLASH_START, json.dumps(meta).encode("utf-8"))
        cmd, payload = recv_frame(sock)
        start_ack = json.loads(payload.decode("utf-8"))
        if cmd != Cmd.FLASH_START_ACK or not start_ack.get("ok"):
            log(f"[FEHLER] {start_ack.get('msg', 'FLASH_START wurde abgelehnt')}")
            return False
        log(f"Node bereit: {start_ack.get('msg', '')}")

        # --- Datei in Chunks senden (Stop-and-Wait) --------------------------
        sock.settimeout(CHUNK_TIMEOUT)
        sent = 0
        t0 = time.monotonic()
        while sent < size:
            chunk = data[sent: sent + CHUNK_SIZE]
            send_frame(sock, Cmd.DATA_CHUNK, chunk)
            cmd, payload = recv_frame(sock)
            ack = json.loads(payload.decode("utf-8"))
            if cmd != Cmd.DATA_CHUNK_ACK or not ack.get("ok"):
                log(f"[FEHLER] Chunk nicht bestätigt: {ack}")
                return False
            sent += len(chunk)
            pct = sent * 100 // size
            elapsed = max(time.monotonic() - t0, 0.001)
            speed_kbs = (sent / 1024) / elapsed
            if progress_cb:
                progress_cb(pct, sent, size, speed_kbs)
            else:
                print(f"\r  Übertrage: {pct:3d}% ({sent}/{size} Bytes, {speed_kbs:.1f} KB/s)",
                      end="", flush=True)
        if not progress_cb:
            print()

        # --- Abschluss + Flash-Ergebnis abwarten -----------------------------
        send_frame(sock, Cmd.FLASH_END)
        sock.settimeout(RESULT_TIMEOUT)
        cmd, payload = recv_frame(sock)
        result = json.loads(payload.decode("utf-8"))
        if cmd == Cmd.FLASH_RESULT and result.get("ok"):
            log(f"[OK] Flash erfolgreich auf {node_name}.")
            return True

        log(f"[FEHLER] Flash fehlgeschlagen (Exit-Code {result.get('returncode')}):")
        log(result.get("output", "(keine Ausgabe)"))
        return False

    except (OSError, socket.timeout, ProtocolError) as exc:
        log(f"[FEHLER] Verbindung zu {node_name} ({mac}) fehlgeschlagen: {exc}")
        log("         Ist der Node gepaart, eingeschaltet und in Reichweite?")
        return False
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Teensy 4.0 Firmware per Bluetooth auf RPi Zero 2 W Node(s) flashen"
    )
    parser.add_argument("hex_file", type=Path, help="Pfad zur kompilierten .hex-Datei")
    parser.add_argument("--target", choices=["node1", "node2", "both"], default="both",
                         help="Zielnode (Default: both = sequenziell node1 dann node2)")
    parser.add_argument("--targets-file", type=Path, default=TARGETS_FILE_DEFAULT,
                         help="Pfad zu bt_targets.json (Default: neben diesem Skript)")
    args = parser.parse_args()

    if not args.hex_file.exists():
        print(f"[FEHLER] Datei nicht gefunden: {args.hex_file}")
        return 1
    if args.hex_file.suffix.lower() != ".hex":
        print(f"[WARNUNG] Datei hat keine .hex-Endung ({args.hex_file.name}) — fahre trotzdem fort.")

    targets = load_targets(args.targets_file)
    names = ["node1", "node2"] if args.target == "both" else [args.target]

    results: dict[str, bool] = {}
    for name in names:
        if name not in targets:
            print(f"[FEHLER] '{name}' fehlt in {args.targets_file}")
            results[name] = False
            continue
        results[name] = flash_one(name, targets[name], args.hex_file)

    print("\n=== Zusammenfassung ===")
    for name, ok in results.items():
        print(f"  {name}: {'OK' if ok else 'FEHLGESCHLAGEN'}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
