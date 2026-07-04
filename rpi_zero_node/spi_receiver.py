#!/usr/bin/env python3
"""
spi_receiver.py — RPi Zero W Node  (v5 — Einthreadige Event-Loop)
==========================================================
Liest Binärpakete vom Teensy 4.0 über UART und leitet sie sofort als
UDP-Datagramm an den RPi 5 weiter. Empfängt außerdem zwei Param-Downlink-
Streams (Slow + Fast) vom RPi 5 und reicht sie unverändert über UART_DBG-TX
an den Teensy weiter.

────────────────────────────────────────────────────────────────────────────
WARUM v5 EIN KOMPLETTER UMBAU IST (Bugfix für Throughput-Einbruch):
────────────────────────────────────────────────────────────────────────────
In v4 liefen UART-Reader, NetworkMonitor, ParamDownlinkSlow und
ParamDownlinkFast als VIER separate Python-Threads. Sobald der Fast-Kanal
(100 Hz) aktiv gesendet hat, ist die Telemetrie-Rate von 100 auf ca. 70
Pakete/s eingebrochen — das war kein Bandbreiten- oder Kabelproblem
(2.8 kB/s Fast-Traffic sind nichts gegen die ~100 kB/s Baud-Budget),
sondern ein GIL-Scheduling-Problem: CPython fuehrt nur EINEN Thread
gleichzeitig aus. Der Fast-Downlink-Thread wachte 100x/s auf und hat dem
UART-Reader-Thread Ausfuehrungszeit auf dem schwachen Cortex-A53-Kern des
RPi Zero 2 W weggenommen. Geriet der Reader dadurch kurz in Verzug, war die
(alte) Resync-Logik selbst wieder teuer (Byte-fuer-Byte-Lesen), was den
Effekt verstaerkt hat.

v5 loest das strukturell: ALLES (UART lesen/schreiben, beide UDP-Ports)
laeuft in EINEM einzigen Thread ueber eine `selectors`-Event-Loop (wie
select/epoll). Es gibt keine konkurrierenden Python-Threads mehr, also auch
keine GIL-Umschaltung zwischen ihnen. Zusaetzlich ersetzt ein einfacher
Puffer-Zustandsautomat (TelemetryFrameAssembler) die alte byte-fuer-byte
Resync-Schleife durch ein effizientes bytearray.find()-basiertes Verfahren.

Umgebungsvariablen:
    NODE_ID  = 1 oder 2  (Standard: 1)
    RPI5_IP  = IP des RPi 5 (Standard: 192.168.42.1) — aktuell nur fuer
               Logging verwendet, der eigentliche Versand ist Broadcast.

Paket-Format (vom Teensy, Telemetrie):
    [Header: 4 Bytes = 0xDEADBEEF][Timestamp: 4 Bytes][Data: 200 × float32]
    Gesamt: 808 Bytes   (bei MAX_FLOATS=200 — siehe PDS.cpp)

Param-Downlink (vom RPi 5, Gegenrichtung):
    Slow-Kanal (Port 700X): 50 Floats + 50 Bools, 2 Hz    (Magic 0xCAFEFEED, 258 B)
    Fast-Kanal (Port 701X): 5 Floats, 100 Hz               (Magic 0xFA57DA7A, 28 B)

Verdrahtung:
    RPi GPIO15 (Pin 10, UART RX) ←── Teensy Pin 1 (TX1)
    RPi GPIO14 (Pin  8, UART TX) ──→ Teensy Pin 0 (RX1)  [Pflicht fuer Param-Downlink]
    GND (Pin 6)                  ───  GND

UART-Einrichtung (RPi Zero W, einmalig):
    /boot/firmware/config.txt:
        dtoverlay=disable-bt    ← PL011 UART auf GPIO14/15 (BT deaktiviert)
        enable_uart=1
    /boot/firmware/cmdline.txt:
        console=serial0,115200  ← DIESE ZEILE ENTFERNEN (kein Login-Prompt)
    Danach: sudo reboot
"""

import os
import time
import socket
import struct
import logging
import selectors
import subprocess

import serial

# ── Konfiguration: Telemetrie ────────────────────────────────────────────────
NODE_ID      = int(os.environ.get("NODE_ID", "1"))
RPI5_IP      = os.environ.get("RPI5_IP", "192.168.42.1")
UDP_PORT     = 5000 + NODE_ID          # 5001 oder 5002

UART_PORT    = "/dev/ttyAMA0"          # PL011 Full-UART (nach dtoverlay=disable-bt)
UART_BAUD    = 1_000_000               # 1 Mbps — muss mit params.h (UART_DBG_BAUD) übereinstimmen!

MAX_FLOATS   = 200                     # Muss mit Teensy PDS.cpp (MAX_FLOATS) übereinstimmen!
HEADER_SIZE  = 8                       # uint32 magic + uint32 timestamp
PACKET_BYTES = HEADER_SIZE + MAX_FLOATS * 4   # 808 Bytes (bei MAX_FLOATS=200)

MAGIC        = 0xDEADBEEF
MAGIC_BYTES  = struct.pack("<I", MAGIC)

NET_CHECK_INTERVAL = 15.0   # Sekunden
STAT_LOG_INTERVAL  = 4.0    # Sekunden

# ── Konfiguration: Param-Downlink ────────────────────────────────────────────
# Muss exakt mit params.h (Teensy) und config.py (RPi 5) übereinstimmen!

PARAM_SLOW_MAGIC        = 0xCAFEFEED
PARAM_SLOW_MAGIC_BYTES  = struct.pack("<I", PARAM_SLOW_MAGIC)
PARAM_SLOW_FLOAT_COUNT  = 50
PARAM_SLOW_BOOL_COUNT   = 50
PARAM_SLOW_PACKET_BYTES = HEADER_SIZE + PARAM_SLOW_FLOAT_COUNT * 4 + PARAM_SLOW_BOOL_COUNT   # 258
UDP_PARAM_SLOW_PORT     = 7000 + NODE_ID   # 7001 / 7002

PARAM_FAST_MAGIC        = 0xFA57DA7A
PARAM_FAST_MAGIC_BYTES  = struct.pack("<I", PARAM_FAST_MAGIC)
PARAM_FAST_FLOAT_COUNT  = 5
PARAM_FAST_PACKET_BYTES = HEADER_SIZE + PARAM_FAST_FLOAT_COUNT * 4                            # 28
UDP_PARAM_FAST_PORT     = 7010 + NODE_ID   # 7011 / 7012

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format=f"[uart_rx Node{NODE_ID}] %(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger()


# ══════════════════════════════════════════════════════════════════════════════
#  TelemetryFrameAssembler — ersetzt die alte byte-für-byte Resync-Schleife
# ══════════════════════════════════════════════════════════════════════════════

class TelemetryFrameAssembler:
    """
    Nimmt beliebig große, beliebig geschnittene Byte-Chunks entgegen (wie sie
    von einem nicht-blockierenden UART-Read zurückkommen) und liefert
    vollständige Telemetrie-Pakete zurück, sobald sie komplett sind.

    Nutzt bytearray.find() für die Magic-Suche statt einer Python-Schleife
    mit Einzelbyte-Reads — das ist der Teil, der in v4 bei Sync-Verlust
    unverhältnismäßig teuer war und zum GIL-Kontentions-Teufelskreis
    beigetragen hat (siehe Modul-Docstring).
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.sync_losses = 0
        self.packets_out = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        self._buf.extend(chunk)
        packets: list[bytes] = []

        while True:
            idx = self._buf.find(MAGIC_BYTES)
            if idx == -1:
                # Kein vollständiger Magic im Puffer -- die letzten 3 Bytes
                # könnten der Anfang eines noch nicht komplett angekommenen
                # Magic sein, den Rest können wir gefahrlos verwerfen.
                if len(self._buf) > 3:
                    del self._buf[:-3]
                break

            if idx > 0:
                # Byte-Müll vor dem Magic -- Sync-Verlust zählen und verwerfen
                self.sync_losses += 1
                del self._buf[:idx]

            if len(self._buf) < PACKET_BYTES:
                break   # Paket ist noch nicht vollständig angekommen

            packets.append(bytes(self._buf[:PACKET_BYTES]))
            del self._buf[:PACKET_BYTES]
            self.packets_out += 1

        return packets


# ══════════════════════════════════════════════════════════════════════════════
#  Netzwerk-Check (jetzt eine einfache Funktion statt eigenem Thread)
# ══════════════════════════════════════════════════════════════════════════════

def _check_wlan_connected() -> bool:
    """Prüft ob wlan0 überhaupt eine IP-Adresse besitzt (DHCP erfolgreich)."""
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=3,
        )
        return "inet " in result.stdout
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Hauptfunktion — einthreadige Event-Loop
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info(
        f"Starte | NODE_ID={NODE_ID} | UDP→{RPI5_IP}:{UDP_PORT} (Broadcast) | "
        f"UART {UART_PORT} @ {UART_BAUD // 1_000_000} Mbps | "
        f"{PACKET_BYTES} Bytes/Paket | {MAX_FLOATS} Floats"
    )
    log.info(
        f"Param-Downlink | Slow: UDP :{UDP_PARAM_SLOW_PORT} -> {PARAM_SLOW_PACKET_BYTES} B | "
        f"Fast: UDP :{UDP_PARAM_FAST_PORT} -> {PARAM_FAST_PACKET_BYTES} B"
    )
    log.info("v5: einthreadige selectors-Event-Loop (kein GIL-Konkurrenzproblem mehr)")

    # ── UART öffnen (nicht-blockierend: timeout=0 -> read() kehrt sofort zurück) ──
    try:
        ser = serial.Serial(
            port         = UART_PORT,
            baudrate     = UART_BAUD,
            bytesize     = serial.EIGHTBITS,
            parity       = serial.PARITY_NONE,
            stopbits     = serial.STOPBITS_ONE,
            timeout      = 0,      # nicht-blockierend: read() liefert sofort, was da ist
            write_timeout = 0,     # write() blockiert ebenfalls nicht
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
    log.info(f"UART {UART_PORT} geöffnet — warte auf ersten Teensy-Frame...")

    # ── UDP Socket (Telemetrie, Broadcast an RPi 5) ─────────────────────────────
    udp_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_out.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)
    udp_out.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # ── UDP Sockets (Param-Downlink, empfangend, nicht-blockierend) ────────────
    slow_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    slow_sock.setblocking(False)
    slow_sock.bind(("0.0.0.0", UDP_PARAM_SLOW_PORT))

    fast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fast_sock.setblocking(False)
    fast_sock.bind(("0.0.0.0", UDP_PARAM_FAST_PORT))

    # ── Event-Loop: alle vier Quellen (UART, 2× UDP) über EINEN Selector ───────
    sel = selectors.DefaultSelector()
    sel.register(ser.fileno(), selectors.EVENT_READ, data="uart")
    sel.register(slow_sock, selectors.EVENT_READ, data="param_slow")
    sel.register(fast_sock, selectors.EVENT_READ, data="param_fast")

    assembler = TelemetryFrameAssembler()

    # ── Statistik ────────────────────────────────────────────────────────────
    pkt_sent      = 0
    bytes_sent    = 0
    send_errors   = 0
    fwd_slow_ok   = 0
    fwd_fast_ok   = 0
    fwd_bad       = 0
    last_sync_losses = 0

    t_stat_start   = time.monotonic()
    t_last_netcheck = time.monotonic()

    log.info("Event-Loop gestartet — warte auf Daten (UART + 2× UDP)...")

    try:
        while True:
            # timeout=1.0: mind. 1x/s aufwachen, auch wenn nichts anliegt,
            # damit periodische Aufgaben (Stats, Netzwerk-Check) nicht liegen bleiben
            events = sel.select(timeout=1.0)

            for key, _mask in events:
                if key.data == "uart":
                    # Nicht-blockierend: liefert sofort 0..N verfügbare Bytes
                    chunk = ser.read(4096)
                    for raw in assembler.feed(chunk):
                        try:
                            sent = udp_out.sendto(raw, ("255.255.255.255", UDP_PORT))
                            pkt_sent += 1
                            bytes_sent += sent
                        except OSError as exc:
                            log.warning(f"UDP-Sendefehler: {exc}")
                            send_errors += 1

                elif key.data == "param_slow":
                    try:
                        data, _addr = slow_sock.recvfrom(PARAM_SLOW_PACKET_BYTES + 64)
                    except (BlockingIOError, OSError):
                        continue
                    if len(data) == PARAM_SLOW_PACKET_BYTES and data[:4] == PARAM_SLOW_MAGIC_BYTES:
                        try:
                            ser.write(data)
                            fwd_slow_ok += 1
                        except serial.SerialException as exc:
                            log.warning(f"[Slow] UART-Schreibfehler: {exc}")
                    else:
                        fwd_bad += 1

                elif key.data == "param_fast":
                    try:
                        data, _addr = fast_sock.recvfrom(PARAM_FAST_PACKET_BYTES + 64)
                    except (BlockingIOError, OSError):
                        continue
                    if len(data) == PARAM_FAST_PACKET_BYTES and data[:4] == PARAM_FAST_MAGIC_BYTES:
                        try:
                            ser.write(data)
                            fwd_fast_ok += 1
                        except serial.SerialException as exc:
                            log.warning(f"[Fast] UART-Schreibfehler: {exc}")
                    else:
                        fwd_bad += 1

            # ── Periodische Aufgaben (statt eigener Threads) ────────────────────
            now = time.monotonic()

            if now - t_stat_start >= STAT_LOG_INTERVAL:
                elapsed = now - t_stat_start
                pps = pkt_sent / elapsed
                kbps = bytes_sent / elapsed / 1024
                new_losses = assembler.sync_losses - last_sync_losses
                log.info(
                    f"Telemetrie: {pps:.1f} Pkt/s | {kbps:.1f} KB/s | "
                    f"Sync-Verluste: {new_losses} | Sendefehler: {send_errors} || "
                    f"Param-Downlink: Slow={fwd_slow_ok} Fast={fwd_fast_ok} "
                    f"({fwd_fast_ok / elapsed:.1f} Pkt/s) ungültig={fwd_bad}"
                )
                pkt_sent = bytes_sent = send_errors = 0
                fwd_slow_ok = fwd_fast_ok = fwd_bad = 0
                last_sync_losses = assembler.sync_losses
                t_stat_start = now

            if now - t_last_netcheck >= NET_CHECK_INTERVAL:
                if not _check_wlan_connected():
                    log.warning("WLAN nicht verbunden (keine IP-Adresse auf wlan0)")
                t_last_netcheck = now

    except KeyboardInterrupt:
        log.info("Gestoppt (KeyboardInterrupt).")
    finally:
        sel.close()
        ser.close()
        udp_out.close()
        slow_sock.close()
        fast_sock.close()
        log.info("Alle Ressourcen freigegeben.")


if __name__ == "__main__":
    main()