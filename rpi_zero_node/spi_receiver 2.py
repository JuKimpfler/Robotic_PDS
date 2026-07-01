#!/usr/bin/env python3
"""
spi_receiver.py — RPi Zero 2W Node  (v4 — bidirektional)
==========================================================
Reine Weiterleitung zwischen Teensy 4.0 (UART) und RPi 5 / PC (UDP) —
jetzt in BEIDEN Richtungen:

    Teensy → UART → RPi Zero → UDP → RPi 5     (Telemetrie, wie bisher)
    RPi 5 → UDP → RPi Zero → UART → Teensy     (Kommandos, NEU)

Das Skript parst die Kommando-Richtung NICHT — was auch immer per UDP
auf UDP_COMMAND_PORT ankommt, wird 1:1 auf den UART geschrieben. Das
ist bewusst so gehalten, damit später ein XCP-Master (oder jedes
andere Protokoll) auf der PC-Seite sprechen kann, ohne dass dieses
Skript geändert werden muss — der RPi Zero bleibt "dumme" Bridge.

Zwei unabhängige Threads:
    1. uart_to_udp   — wie in v3: liest UART, synct auf Magic-Header,
                        schickt Pakete per UDP an RPi5_IP:UDP_TELEMETRY_PORT
    2. udp_to_uart    — NEU: lauscht auf UDP_COMMAND_PORT, schreibt
                        jedes empfangene Datagramm sofort auf den UART

Beide Threads teilen sich dasselbe serial.Serial-Objekt. Das ist bei
pyserial auf Linux unproblematisch, solange ein Thread nur liest und
der andere nur schreibt (siehe pyserial-FAQ zu Multithreading).

Umgebungsvariablen:
    NODE_ID           = 1 oder 2  (Standard: 1)
    RPI5_IP           = IP des RPi 5 (Standard: 192.168.42.1)
    UART_RAW_MODE     = "1" → kein Magic-Sync, UART wird 1:1 roh
                        weitergereicht (für später, sobald die Firmware
                        auf ein eigenes Framing wie XCP umgestellt ist).
                        Standard: "0" (aktuelles DEADBEEF-Format).

Ports (abgeleitet von NODE_ID, wie im restlichen Projekt üblich):
    UDP_TELEMETRY_PORT = 5000 + NODE_ID   (Pi Zero → RPi 5, wie bisher)
    UDP_COMMAND_PORT   = 5100 + NODE_ID   (RPi 5 → Pi Zero, NEU)

    WICHTIG: Auf der RPi5-Seite (network_worker.py / config.py) muss ein
    passender Sende-Pfad zu UDP_COMMAND_PORT ergänzt werden — das ist in
    diesem Skript nicht enthalten, da es nur die Pi-Zero-Seite betrifft.

Paket-Format Telemetrie (unverändert, nur relevant wenn UART_RAW_MODE=0):
    [Header: 4 Bytes = 0xDEADBEEF][Timestamp: 4 Bytes][Data: 400 × float32]

Verdrahtung (jetzt BEIDE Leitungen zwingend erforderlich, nicht mehr optional!):
    RPi GPIO15 (Pin 10, UART RX) ←── Teensy Pin 1 (TX1)
    RPi GPIO14 (Pin  8, UART TX) ──→ Teensy Pin 0 (RX1)   ← jetzt Pflicht
    GND (Pin 6)                  ───  GND

UART-Einrichtung (RPi Zero 2W, einmalig):
    /boot/firmware/config.txt:
        dtoverlay=disable-bt    ← PL011 UART auf GPIO14/15 (BT deaktiviert)
        enable_uart=1
    /boot/firmware/cmdline.txt:
        console=serial0,115200  ← DIESE ZEILE ENTFERNEN (kein Login-Prompt)
    Danach: sudo reboot

LED-Status (GPIO BCM):
    GPIO 27 — Heartbeat  (grün,  blinkt 1 Hz = läuft)
    GPIO 22 — Netzwerk   (blau,  AN = WiFi OK)
    GPIO 24 — Daten      (gelb,  blinkt = Paket empfangen ODER gesendet)
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

from status_leds import StatusLEDs

# ── Konfiguration ─────────────────────────────────────────────────────────────
NODE_ID      = int(os.environ.get("NODE_ID", "1"))
RPI5_IP      = os.environ.get("RPI5_IP", "192.168.42.1")
UART_RAW_MODE = os.environ.get("UART_RAW_MODE", "0") == "1"

UDP_TELEMETRY_PORT = 5000 + NODE_ID    # Pi Zero → RPi 5   (5001 / 5002, wie bisher)
UDP_COMMAND_PORT   = 5100 + NODE_ID    # RPi 5   → Pi Zero (5101 / 5102, NEU)

UART_PORT    = "/dev/ttyAMA0"          # PL011 Full-UART (nach dtoverlay=disable-bt)
UART_BAUD    = 4_000_000               # 4 Mbps — muss mit Teensy übereinstimmen

MAX_FLOATS   = 400                     # Muss mit Teensy main.cpp übereinstimmen!
HEADER_SIZE  = 8                       # uint32 magic + uint32 timestamp
PACKET_BYTES = HEADER_SIZE + MAX_FLOATS * 4   # 1608 Bytes

MAGIC        = 0xDEAD_BEEF
MAGIC_BYTES  = struct.pack("<I", MAGIC)       # b'\xef\xbe\xad\xde' (little-endian)

# Größe für rohe Kommando-Pakete (großzügig, XCP-Frames sind i.d.R. klein)
UDP_CMD_RECV_BUFSIZE = 4096

# Netzwerk-Prüfintervall in Sekunden
NET_CHECK_INTERVAL = 15.0

# Socket-Timeout für den Kommando-Empfänger — bestimmt, wie schnell der
# Thread auf stop_event reagiert (kein Einfluss auf Latenz der Weiterleitung,
# recvfrom() kehrt sofort zurück sobald Daten da sind).
UDP_CMD_SOCK_TIMEOUT = 1.0

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format=f"[bridge Node{NODE_ID}] %(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger()


# ══════════════════════════════════════════════════════════════════════════════
#  Gemeinsame Statistik (thread-übergreifend, ohne Lock — reine Zähler,
#  gelegentliche Ungenauigkeit bei Log-Ausgabe ist unkritisch)
# ══════════════════════════════════════════════════════════════════════════════

class _Stats:
    def __init__(self) -> None:
        self.tel_pkt_sent    = 0   # UART → UDP  (Telemetrie)
        self.tel_bytes_sent  = 0
        self.tel_err_count   = 0
        self.tel_sync_losses = 0
        self.cmd_pkt_fwd     = 0   # UDP → UART  (Kommandos)
        self.cmd_bytes_fwd   = 0
        self.cmd_err_count   = 0


# ══════════════════════════════════════════════════════════════════════════════
#  Richtung 1: UART → UDP  (Telemetrie, RPi Zero → RPi 5)
# ══════════════════════════════════════════════════════════════════════════════

def _read_exactly(ser: serial.Serial, n: int) -> bytes | None:
    """
    Liest exakt n Bytes aus dem UART.
    Gibt None zurück bei Timeout oder unvollständigem Empfang.
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

        window[0:3] = window[1:4]
        window[3]   = b[0]
        bytes_searched += 1

        if bytes(window) == MAGIC_BYTES:
            if bytes_searched > 4:
                log.warning(f"Re-Sync nach {bytes_searched} Bytes")
            return True


def _uart_to_udp_loop(
    ser: serial.Serial,
    tel_sock: socket.socket,
    leds: StatusLEDs,
    stop_event: threading.Event,
    stats: _Stats,
) -> None:
    """
    Thread-Funktion: liest kontinuierlich vom UART und leitet die Pakete
    per UDP an den RPi 5 weiter. Entspricht der Hauptschleife aus v3,
    nur jetzt als eigenständiger Thread statt der main()-Funktion.

    UART_RAW_MODE=1: kein Magic-Sync, jeder gelesene Chunk wird sofort
    1:1 weitergereicht (für zukünftiges XCP-Framing, das sein eigenes
    Längenfeld/CRC mitbringt und keine feste Paketgröße mehr hat).
    """
    log.info("uart_to_udp gestartet.")

    if UART_RAW_MODE:
        # ── Roh-Modus: kein Parsing, keine Paketgrenzen ───────────────────────
        # Read-Timeout des Serial-Objekts sorgt dafür, dass ser.read() auch
        # ohne Daten regelmäßig zurückkehrt, damit stop_event geprüft wird.
        while not stop_event.is_set():
            chunk = ser.read(4096)
            if not chunk:
                continue   # Timeout, keine Daten — einfach weiter warten
            try:
                sent = tel_sock.sendto(chunk, (RPI5_IP, UDP_TELEMETRY_PORT))
                stats.tel_pkt_sent   += 1
                stats.tel_bytes_sent += sent
                leds.blink_data()
            except OSError as exc:
                log.warning(f"UDP-Sendefehler: {exc}")
                stats.tel_err_count += 1
        log.info("uart_to_udp beendet (Roh-Modus).")
        return

    # ── Standard-Modus: Magic-Header-Framing (wie v3) ─────────────────────────
    t_stat_start = time.monotonic()

    log.info("Suche Magic-Header (0xDEADBEEF) …")
    if not _sync_to_magic(ser):
        log.warning("Kein Signal vom Teensy (Timeout). Kabel/Firmware prüfen.")
    else:
        log.info("Synchronisiert — Telemetrie-Empfang läuft.")

    while not stop_event.is_set():
        header = _read_exactly(ser, 4)

        if header is None:
            # Timeout — kein Fehler, einfach kein Signal gerade. Erneut syncen
            # kostet nichts, da _sync_to_magic() selbst wieder auf Timeout
            # zurückkehrt, falls weiterhin nichts kommt.
            _sync_to_magic(ser)
            continue

        if header != MAGIC_BYTES:
            log.debug(f"Magic erwartet, bekam {header.hex()} — re-sync...")
            ser.reset_input_buffer()
            if not _sync_to_magic(ser):
                stats.tel_err_count += 1
                continue
            stats.tel_sync_losses += 1
            payload = _read_exactly(ser, PACKET_BYTES - 4)
            if payload is None:
                stats.tel_err_count += 1
                continue
            raw = MAGIC_BYTES + payload
        else:
            payload = _read_exactly(ser, PACKET_BYTES - 4)
            if payload is None:
                log.warning("Paket unvollständig (Timeout nach Magic).")
                stats.tel_err_count += 1
                _sync_to_magic(ser)
                stats.tel_sync_losses += 1
                continue
            raw = header + payload

        try:
            sent = tel_sock.sendto(raw, (RPI5_IP, UDP_TELEMETRY_PORT))
            stats.tel_pkt_sent   += 1
            stats.tel_bytes_sent += sent
            leds.blink_data()
        except OSError as exc:
            log.warning(f"UDP-Sendefehler: {exc}")
            stats.tel_err_count += 1

        elapsed = time.monotonic() - t_stat_start
        if elapsed >= 10.0:
            pps  = stats.tel_pkt_sent   / elapsed
            kbps = stats.tel_bytes_sent / elapsed / 1024
            log.info(
                f"Telemetrie: {pps:.1f} Pkt/s | {kbps:.1f} KB/s | "
                f"Sync-Verluste: {stats.tel_sync_losses} | Fehler: {stats.tel_err_count} || "
                f"Kommandos weitergeleitet: {stats.cmd_pkt_fwd} ({stats.cmd_bytes_fwd} B) | "
                f"Kommando-Fehler: {stats.cmd_err_count}"
            )
            stats.tel_pkt_sent = stats.tel_bytes_sent = 0
            stats.tel_err_count = stats.tel_sync_losses = 0
            t_stat_start = time.monotonic()

    log.info("uart_to_udp beendet.")


# ══════════════════════════════════════════════════════════════════════════════
#  Richtung 2: UDP → UART  (Kommandos, RPi 5 → RPi Zero, NEU)
# ══════════════════════════════════════════════════════════════════════════════

def _udp_to_uart_loop(
    ser: serial.Serial,
    cmd_sock: socket.socket,
    leds: StatusLEDs,
    stop_event: threading.Event,
    stats: _Stats,
) -> None:
    """
    Thread-Funktion: lauscht auf UDP_COMMAND_PORT und schreibt jedes
    empfangene Datagramm unverändert auf den UART. Keine Interpretation
    der Nutzdaten — der RPi Zero bleibt reine Weiterleitung, egal ob
    darin z.B. XCP-CONNECT/DOWNLOAD-Frames stecken oder etwas anderes.

    Läuft komplett unabhängig vom uart_to_udp-Thread — ein Kommando kann
    also jederzeit dazwischenfunken, ohne den Telemetrie-Empfang zu
    blockieren (und umgekehrt).
    """
    log.info(f"udp_to_uart gestartet — lauscht auf 0.0.0.0:{UDP_COMMAND_PORT}")

    while not stop_event.is_set():
        try:
            data, addr = cmd_sock.recvfrom(UDP_CMD_RECV_BUFSIZE)
        except socket.timeout:
            continue
        except OSError as exc:
            if stop_event.is_set():
                break
            log.warning(f"UDP-Empfangsfehler (Kommando-Socket): {exc}")
            continue

        if not data:
            continue

        try:
            ser.write(data)
            # Kein ser.flush() nötig für den Normalfall — pyserial puffert
            # intern und schreibt zeitnah; falls die Master-Seite spürbar
            # niedrige Latenz braucht, kann hier ser.flush() ergänzt werden.
            stats.cmd_pkt_fwd   += 1
            stats.cmd_bytes_fwd += len(data)
            leds.blink_data()
            log.debug(f"{len(data)} B von {addr[0]}:{addr[1]} → UART weitergeleitet")
        except serial.SerialException as exc:
            log.warning(f"UART-Schreibfehler: {exc}")
            stats.cmd_err_count += 1

    log.info("udp_to_uart beendet.")


# ══════════════════════════════════════════════════════════════════════════════
#  Netzwerk-Monitor (Hintergrundthread, unverändert zu v3)
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
    node_ip = f"192.168.42.1{NODE_ID}"

    while not stop_event.is_set():
        connected = _check_wlan_connected(node_ip)
        leds.set_network(connected)

        if not connected:
            log.warning(f"WLAN nicht verbunden (erwartet IP {node_ip})")

        for _ in range(int(NET_CHECK_INTERVAL)):
            if stop_event.is_set():
                break
            time.sleep(1.0)


# ══════════════════════════════════════════════════════════════════════════════
#  Hauptfunktion
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info(
        f"Starte Bridge | NODE_ID={NODE_ID} | "
        f"Telemetrie UDP→{RPI5_IP}:{UDP_TELEMETRY_PORT} | "
        f"Kommandos UDP←:{UDP_COMMAND_PORT} | "
        f"UART {UART_PORT} @ {UART_BAUD // 1_000_000} Mbps | "
        f"Roh-Modus={'AN' if UART_RAW_MODE else 'AUS (Magic-Framing)'}"
    )

    # ── LED-Controller ────────────────────────────────────────────────────────
    leds = StatusLEDs()
    leds.start()

    # ── UART öffnen (wird jetzt von BEIDEN Threads genutzt: 1× Lese-, ─────────
    #    1× Schreibrichtung) ────────────────────────────────────────────────
    try:
        ser = serial.Serial(
            port         = UART_PORT,
            baudrate     = UART_BAUD,
            bytesize     = serial.EIGHTBITS,
            parity       = serial.PARITY_NONE,
            stopbits     = serial.STOPBITS_ONE,
            timeout      = 2.0,    # Lese-Timeout [s] — betrifft nur ser.read()
            write_timeout = 2.0,   # Schreib-Timeout [s] — verhindert ewiges Blockieren
            xonxoff      = False,
            rtscts       = False,
            dsrdtr       = False,
        )
    except serial.SerialException as exc:
        log.error(f"UART {UART_PORT} konnte nicht geöffnet werden: {exc}")
        log.error("→ Prüfe: dtoverlay=disable-bt in /boot/firmware/config.txt?")
        log.error("→ Prüfe: console=serial0,... in cmdline.txt entfernt?")
        raise SystemExit(1)

    ser.reset_input_buffer()
    log.info(f"UART {UART_PORT} geöffnet.")

    # ── UDP Socket für Telemetrie-Ausgang (Senden, wie bisher) ────────────────
    tel_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tel_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)

    # ── UDP Socket für Kommando-Eingang (NEU — muss gebunden werden!) ─────────
    cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    cmd_sock.bind(("0.0.0.0", UDP_COMMAND_PORT))
    cmd_sock.settimeout(UDP_CMD_SOCK_TIMEOUT)

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

    # ── Gemeinsame Statistik ──────────────────────────────────────────────────
    stats = _Stats()

    # ── Beide Bridge-Richtungen als eigene Threads starten ────────────────────
    uart_to_udp_thread = threading.Thread(
        target=_uart_to_udp_loop,
        args=(ser, tel_sock, leds, stop_event, stats),
        daemon=True,
        name="UART-to-UDP",
    )
    udp_to_uart_thread = threading.Thread(
        target=_udp_to_uart_loop,
        args=(ser, cmd_sock, leds, stop_event, stats),
        daemon=True,
        name="UDP-to-UART",
    )

    uart_to_udp_thread.start()
    udp_to_uart_thread.start()

    log.info("Bridge läuft — beide Richtungen aktiv. Strg+C zum Beenden.")

    try:
        # Hauptthread wartet nur noch, die eigentliche Arbeit läuft in den
        # beiden Bridge-Threads. join() mit Timeout in einer Schleife, damit
        # KeyboardInterrupt zuverlässig ankommt (statt in einem blockierenden
        # join() ohne Timeout hängen zu bleiben).
        while uart_to_udp_thread.is_alive() and udp_to_uart_thread.is_alive():
            uart_to_udp_thread.join(timeout=0.5)
            udp_to_uart_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        log.info("Gestoppt (KeyboardInterrupt).")
    finally:
        stop_event.set()
        uart_to_udp_thread.join(timeout=3)
        udp_to_uart_thread.join(timeout=3)
        leds.stop()
        GPIO.cleanup()
        ser.close()
        tel_sock.close()
        cmd_sock.close()
        log.info("Alle Ressourcen freigegeben.")


if __name__ == "__main__":
    main()
