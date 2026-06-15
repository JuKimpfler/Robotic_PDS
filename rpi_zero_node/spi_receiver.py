#!/usr/bin/env python3
"""
spi_receiver.py — RPi Zero W Node  (v3 — UART statt SPI)
==========================================================
Liest Binärpakete vom Teensy 4.0 über UART und leitet
sie sofort als UDP-Datagramm an den RPi 5 weiter.

Kein SPI, kein DATA_READY-Signal — der Teensy sendet kontinuierlich.
Paketsynchronisation erfolgt über den Magic-Header (0xDEADBEEF).

Umgebungsvariablen:
    NODE_ID  = 1 oder 2  (Standard: 1)
    RPI5_IP  = IP des RPi 5 (Standard: 192.168.42.1)

Paket-Format (vom Teensy):
    [Header: 4 Bytes = 0xDEADBEEF][Timestamp: 4 Bytes][Data: 400 × float32]
    Gesamt: 1608 Bytes

Verdrahtung:
    RPi GPIO15 (Pin 10, UART RX) ←── Teensy Pin 1 (TX1)
    RPi GPIO14 (Pin  8, UART TX) ──→ Teensy Pin 0 (RX1)  [optional]
    GND (Pin 6)                  ───  GND

UART-Einrichtung (RPi Zero W, einmalig):
    /boot/firmware/config.txt:
        dtoverlay=disable-bt    ← PL011 UART auf GPIO14/15 (BT deaktiviert)
        enable_uart=1
    /boot/firmware/cmdline.txt:
        console=serial0,115200  ← DIESE ZEILE ENTFERNEN (kein Login-Prompt)
    Danach: sudo reboot

LED-Status (GPIO BCM):
    GPIO 27 — Heartbeat  (grün,  blinkt 1 Hz = läuft)
    GPIO 22 — Netzwerk   (blau,  AN = WiFi OK)
    GPIO 24 — Daten      (gelb,  blinkt = Paket empfangen)
    GPIO 25 — Flash/Err  (rot,   aus bei normalem Betrieb)
"""

import os
import time
import socket
import struct
import logging
import threading
import subprocess

import serial
import RPi.GPIO as GPIO

from rpi_zero_node.status_leds import StatusLEDs

# ── Konfiguration ─────────────────────────────────────────────────────────────
NODE_ID      = int(os.environ.get("NODE_ID", "1"))
RPI5_IP      = os.environ.get("RPI5_IP", "192.168.42.1")
UDP_PORT     = 5000 + NODE_ID          # 5001 oder 5002

UART_PORT    = "/dev/ttyAMA0"          # PL011 Full-UART (nach dtoverlay=disable-bt)
UART_BAUD    = 2_000_000               # 2 Mbps — stabiler für Steckkabel als 4 Mbps

MAX_FLOATS   = 400                     # Muss mit Teensy main.cpp übereinstimmen!
HEADER_SIZE  = 8                       # uint32 magic + uint32 timestamp
PACKET_BYTES = HEADER_SIZE + MAX_FLOATS * 4   # 1608 Bytes

MAGIC        = 0xDEAD_BEEF
MAGIC_BYTES  = struct.pack("<I", MAGIC)       # b'\xef\xbe\xad\xde' (little-endian)

# Netzwerk-Prüfintervall in Sekunden
NET_CHECK_INTERVAL = 15.0

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format=f"[uart_rx Node{NODE_ID}] %(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger()


# ══════════════════════════════════════════════════════════════════════════════
#  Paket-Synchronisation
# ══════════════════════════════════════════════════════════════════════════════

def _read_exactly(ser: serial.Serial, n: int) -> bytes | None:
    """
    Liest exakt n Bytes aus dem UART.
    Gibt None zurück bei Timeout oder unvollständigem Empfang.
    Intern: mehrere read()-Aufrufe bis alle n Bytes da sind.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            return None   # Timeout
        buf.extend(chunk)
    return bytes(buf)


def _sync_to_magic(ser: serial.Serial) -> bool:
    """
    Schiebt ein 4-Byte-Fenster Byte für Byte durch den UART-Stream,
    bis das Magic-Pattern 0xDEADBEEF gefunden wird.

    Normal-Fall (kein Fehler): Magic steht direkt am Paket-Anfang —
    dann kehrt diese Funktion nach 4 Bytes zurück.

    Fehler-Fall (verlorene Synchronisation): Suche kann viele Bytes dauern.
    Bei Timeout wird False zurückgegeben.

    Returns:
        True  — Magic gefunden, nächste Bytes sind Timestamp + Daten
        False — Timeout ohne Magic-Fund
    """
    window = bytearray(4)
    bytes_searched = 0

    while True:
        b = ser.read(1)
        if not b:
            return False   # Timeout

        # Fenster verschieben und neues Byte anhängen
        window[0:3] = window[1:4]
        window[3]   = b[0]
        bytes_searched += 1

        if bytes(window) == MAGIC_BYTES:
            if bytes_searched > 4:
                log.warning(f"Re-Sync nach {bytes_searched} Bytes")
            return True


# ══════════════════════════════════════════════════════════════════════════════
#  Netzwerk-Monitor (Hintergrundthread)
# ══════════════════════════════════════════════════════════════════════════════

def _check_wlan_connected(expected_ip: str = "") -> bool:
    """Prüft ob wlan0 die erwartete IP besitzt (ohne Netzwerkzugriff)."""
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=3,
        )
        output = result.stdout
        return (expected_ip in output) if expected_ip else ("inet " in output)
    except Exception:
        return False


def _network_monitor_thread(
    leds: StatusLEDs,
    stop_event: threading.Event,
) -> None:
    """Prüft WLAN-Verbindung alle NET_CHECK_INTERVAL Sekunden."""

    while not stop_event.is_set():
        # Leerer String ("") bedeutet: Prüfe nur, ob überhaupt eine IP zugewiesen wurde (DHCP erfolgreich)
        connected = _check_wlan_connected("")
        leds.set_network(connected)

        if not connected:
            log.warning("WLAN nicht verbunden (keine IP-Adresse auf wlan0 erhalten)")

        for _ in range(int(NET_CHECK_INTERVAL)):
            if stop_event.is_set():
                break
            time.sleep(1.0)


# ══════════════════════════════════════════════════════════════════════════════
#  Hauptfunktion
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info(
        f"Starte | NODE_ID={NODE_ID} | UDP→{RPI5_IP}:{UDP_PORT} | "
        f"UART {UART_PORT} @ {UART_BAUD // 1_000_000} Mbps | "
        f"{PACKET_BYTES} Bytes/Paket | {MAX_FLOATS} Floats"
    )

    # ── LED-Controller ────────────────────────────────────────────────────────
    leds = StatusLEDs()
    leds.start()

    # ── UART öffnen ───────────────────────────────────────────────────────────
    try:
        ser = serial.Serial(
            port         = UART_PORT,
            baudrate     = UART_BAUD,
            bytesize     = serial.EIGHTBITS,
            parity       = serial.PARITY_NONE,
            stopbits     = serial.STOPBITS_ONE,
            timeout      = 2.0,    # Gesamt-Read-Timeout [s]
            xonxoff      = False,  # Kein Software-Handshake
            rtscts       = False,  # Kein Hardware-Handshake
            dsrdtr       = False,
        )
    except serial.SerialException as exc:
        log.error(f"UART {UART_PORT} konnte nicht geöffnet werden: {exc}")
        log.error("→ Prüfe: dtoverlay=disable-bt in /boot/firmware/config.txt?")
        log.error("→ Prüfe: console=serial0,... in cmdline.txt entfernt?")
        raise SystemExit(1)

    # Eingangspuffer leeren (Reste aus vorherigen Starts verwerfen)
    ser.reset_input_buffer()
    log.info(f"UART {UART_PORT} geöffnet — warte auf ersten Teensy-Frame...")

    # ── UDP Socket ────────────────────────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # ── Netzwerk-Monitor ──────────────────────────────────────────────────────
    stop_event = threading.Event()
    net_thread = threading.Thread(
        target=_network_monitor_thread,
        args=(leds, stop_event),
        daemon=True,
        name="NetworkMonitor",
    )
    net_thread.start()

    # ── Startup-Sequenz ───────────────────────────────────────────────────────
    leds.startup_sequence()

    # ── Statistik-Variablen ───────────────────────────────────────────────────
    pkt_sent     = 0
    bytes_sent   = 0
    err_count    = 0
    sync_losses  = 0
    t_stat_start = time.monotonic()

    # ── Erste Synchronisation ─────────────────────────────────────────────────
    log.info("Suche Magic-Header (0xDEADBEEF) …")
    if not _sync_to_magic(ser):
        log.error("Kein Signal vom Teensy (Timeout 2 s). Kabel prüfen!")
    else:
        log.info("Synchronisiert — Empfang läuft.")

    # ══════════════════════════════════════════════════════════════════════════
    #  Haupt-Empfangsschleife
    # ══════════════════════════════════════════════════════════════════════════
    # ── Queue für Entkopplung ─────────────────────────────────────────────────
    import queue
    # Maxsize 2: Wir wollen immer die FRISCHESTEN Daten.
    # Wenn UDP (WLAN) zu langsam ist, verwerfen wir alte Pakete, statt sie
    # zu verzögern (verhindert Delay-Stau und UART-Pufferüberläufe!)
    packet_queue = queue.Queue(maxsize=2)

    def _uart_reader_thread():
        nonlocal err_count, sync_losses
        log.info("UART-Reader-Thread gestartet.")
        while True:
            # Schritt 1: Header lesen
            header = _read_exactly(ser, 4)
            if header is None:
                err_count += 1
                _sync_to_magic(ser)
                sync_losses += 1
                continue

            if header != MAGIC_BYTES:
                ser.reset_input_buffer()
                if not _sync_to_magic(ser):
                    err_count += 1
                    continue
                sync_losses += 1
                payload = _read_exactly(ser, PACKET_BYTES - 4)
                if payload is None:
                    continue
                raw = MAGIC_BYTES + payload
            else:
                payload = _read_exactly(ser, PACKET_BYTES - 4)
                if payload is None:
                    err_count += 1
                    _sync_to_magic(ser)
                    sync_losses += 1
                    continue
                raw = header + payload

            # Paket in die Queue schieben (ältestes verwerfen falls voll)
            try:
                packet_queue.put_nowait(raw)
            except queue.Full:
                try:
                    packet_queue.get_nowait() # Altes Paket wegwerfen
                    packet_queue.put_nowait(raw)
                except (queue.Empty, queue.Full):
                    pass

    # Reader-Thread starten
    threading.Thread(target=_uart_reader_thread, daemon=True, name="UART-Reader").start()

    # ══════════════════════════════════════════════════════════════════════════
    #  Haupt-Schleife (UDP Senden)
    # ══════════════════════════════════════════════════════════════════════════
    try:
        while True:
            # Warten bis ein frisches Paket da ist
            raw = packet_queue.get()

            try:
                sent = sock.sendto(raw, ("255.255.255.255", UDP_PORT))
                pkt_sent   += 1
                bytes_sent += sent
                leds.blink_data()
            except OSError as exc:
                log.warning(f"UDP-Sendefehler: {exc}")
                err_count += 1

            # ── Statistik alle 10 Sekunden ────────────────────────────────────
            elapsed = time.monotonic() - t_stat_start
            if elapsed >= 10.0:
                pps  = pkt_sent   / elapsed
                kbps = bytes_sent / elapsed / 1024
                log.info(
                    f"Throughput: {pps:.1f} Pkt/s | {kbps:.1f} KB/s | "
                    f"Sync-Verluste: {sync_losses} | Fehler: {err_count}"
                )
                pkt_sent = bytes_sent = err_count = sync_losses = 0
                t_stat_start = time.monotonic()

    except KeyboardInterrupt:
        log.info("Gestoppt (KeyboardInterrupt).")
    finally:
        stop_event.set()
        leds.stop()
        GPIO.cleanup()
        ser.close()
        sock.close()
        log.info("Alle Ressourcen freigegeben.")


if __name__ == "__main__":
    main()
