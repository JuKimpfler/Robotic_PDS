#!/usr/bin/env python3
"""
flash_daemon.py — RPi Zero W Node  (v2 — mit Status-LEDs)
===========================================================
TCP-Server: wartet auf eine .hex-Datei vom RPi 5,
speichert sie lokal und ruft teensy_loader_cli auf.

Protokoll (RPi 5 → RPi Zero):
    1. 4 Bytes big-endian uint32  : Dateigröße in Bytes
    2. N Bytes                    : .hex-Dateiinhalt
    Antwort (RPi Zero → RPi 5):
    OK          : Erfolgreich geflasht
    ERR:<msg>   : Fehler mit Beschreibung

LED-Verhalten:
    Beim Empfang einer Datei   → Rote LED AN
    Flash erfolgreich          → Rote LED 3× langsames Blinken
    Flash Fehler               → Rote LED 10× schnelles Blinken
    Heartbeat immer aktiv      → Grüne LED blinkt 1 Hz

Umgebungsvariablen:
    NODE_ID = 1 oder 2  (Standard: 1)
"""

import os
import struct
import socket
import subprocess
import threading
import logging
import time

from rpi_zero_node.status_leds import StatusLEDs

# ── Konfiguration ─────────────────────────────────────────────────────────────
NODE_ID       = int(os.environ.get("NODE_ID", "1"))
FLASH_PORT    = 6000 + NODE_ID           # 6001 oder 6002
FIRMWARE_PATH = f"/tmp/node{NODE_ID}_fw.hex"
MCU           = "TEENSY40"
TEENSY_CLI    = "teensy_loader_cli"      # muss in $PATH sein

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format=f"[flash_daemon N{NODE_ID}] %(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger()

# Verhindert parallele Flash-Vorgänge
_flash_lock = threading.Lock()

# Globaler LED-Controller (wird in main() initialisiert)
_leds: StatusLEDs | None = None


# ══════════════════════════════════════════════════════════════════════════════
#  Protokoll-Helfer
# ══════════════════════════════════════════════════════════════════════════════

def _receive_all(conn: socket.socket, n: int) -> bytes:
    """Liest exakt n Bytes aus der Verbindung (blockierend, robust)."""
    buf      = bytearray(n)
    view     = memoryview(buf)
    received = 0
    while received < n:
        chunk = conn.recv_into(view[received:], n - received)
        if not chunk:
            raise ConnectionError(
                f"Verbindung abgebrochen (erwartet {n}, erhalten {received} Bytes)"
            )
        received += chunk
    return bytes(buf)


# ══════════════════════════════════════════════════════════════════════════════
#  Client-Handler
# ══════════════════════════════════════════════════════════════════════════════

def _handle_client(conn: socket.socket, addr: tuple) -> None:
    """
    Verarbeitet eine eingehende Flash-Anfrage in einem eigenen Thread.
    LED-Ablauf:
        1. Rote LED AN  → Empfang läuft
        2a. Flash OK    → 3× langsames Blinken, dann AUS
        2b. Flash ERR   → 10× schnelles Blinken, dann AUS
    """
    global _leds
    log.info(f"Flash-Anfrage von {addr[0]}:{addr[1]}")
    start_ts = time.monotonic()

    # Rote LED einschalten: Empfang/Flash-Vorgang gestartet
    if _leds:
        _leds.set_flash_active(True)

    try:
        # ── Schritt 1: Dateigröße lesen ──────────────────────────────────────
        size_raw  = _receive_all(conn, 4)
        file_size = struct.unpack(">I", size_raw)[0]

        if file_size == 0 or file_size > 10 * 1024 * 1024:   # max 10 MB
            raise ValueError(f"Ungültige Dateigröße: {file_size} Bytes")

        log.info(f"Empfange {file_size:,} Bytes Firmware...")

        # ── Schritt 2: .hex-Datei empfangen ──────────────────────────────────
        hex_data     = _receive_all(conn, file_size)
        elapsed_recv = time.monotonic() - start_ts
        log.info(f"Empfang OK ({elapsed_recv:.2f}s) → {FIRMWARE_PATH}")

        # ── Schritt 3: Auf Disk speichern ─────────────────────────────────────
        with open(FIRMWARE_PATH, "wb") as f:
            f.write(hex_data)

        # ── Schritt 4: Teensy flashen (serialisiert via Lock) ─────────────────
        with _flash_lock:
            # -s = Soft-Reboot (automatisch in den Bootloader wechseln)
            cmd = [TEENSY_CLI, f"--mcu={MCU}", "-w", "-s", "-v", FIRMWARE_PATH]
            log.info(f"Starte: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=90      # 90 s Timeout inkl. Hardware-Reset
            )

        elapsed_total = time.monotonic() - start_ts

        if result.returncode == 0:
            log.info(f"✅  Flash ERFOLGREICH ({elapsed_total:.1f}s)")
            conn.sendall(b"OK")
            # LED: 3× langsames Blinken = Erfolg
            if _leds:
                _leds.set_flash_active(False)
                _leds.flash_success()
        else:
            err = (result.stderr or result.stdout).strip()[:200]
            log.error(f"❌  Flash FEHLGESCHLAGEN: {err}")
            conn.sendall(f"ERR:{err}".encode("utf-8"))
            # LED: 10× schnelles Blinken = Fehler
            if _leds:
                _leds.set_flash_active(False)
                _leds.flash_error()

    except subprocess.TimeoutExpired:
        msg = "Flash-Timeout nach 90s"
        log.error(msg)
        if _leds:
            _leds.set_flash_active(False)
            _leds.flash_error()
        try:
            conn.sendall(f"ERR:{msg}".encode())
        except OSError:
            pass

    except Exception as exc:
        log.error(f"Fehler: {exc}")
        if _leds:
            _leds.set_flash_active(False)
            _leds.flash_error()
        try:
            conn.sendall(f"ERR:{exc}".encode("utf-8"))
        except OSError:
            pass

    finally:
        conn.close()
        log.debug("Verbindung geschlossen.")


# ══════════════════════════════════════════════════════════════════════════════
#  Hauptfunktion
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    global _leds

    # ── LED-Controller initialisieren ────────────────────────────────────────
    _leds = StatusLEDs()
    _leds.start()

    # ── TCP-Server aufbauen ───────────────────────────────────────────────────
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", FLASH_PORT))
    server.listen(1)

    log.info(f"Flash Daemon bereit | Port: {FLASH_PORT} | MCU: {MCU}")

    # ── Startup-Sequenz ───────────────────────────────────────────────────────
    _leds.startup_sequence()

    try:
        while True:
            conn, addr = server.accept()
            conn.settimeout(120)    # 120 s Gesamt-Timeout pro Verbindung
            t = threading.Thread(
                target=_handle_client,
                args=(conn, addr),
                daemon=True,
                name=f"Flash-Client-{addr[0]}",
            )
            t.start()

    except KeyboardInterrupt:
        log.info("Flash Daemon gestoppt (KeyboardInterrupt).")
    finally:
        _leds.stop()
        server.close()
        log.info("Ressourcen freigegeben.")


if __name__ == "__main__":
    main()
