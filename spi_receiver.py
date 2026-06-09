#!/usr/bin/env python3
"""
spi_receiver.py — RPi Zero W Node  (v2 — mit Status-LEDs)
===========================================================
Liest Binärpakete vom Teensy 4.0 über SPI und leitet
sie sofort als UDP-Datagramm an den RPi 5 weiter.

Kein Parsing, keine Filterung — maximale Durchrate.

Umgebungsvariablen:
    NODE_ID  = 1 oder 2  (Standard: 1)
    RPI5_IP  = IP des RPi 5 (Standard: 192.168.42.1)

Paket-Format (vom Teensy):
    [Header: 4 Bytes][Timestamp: 4 Bytes][Data: 4000 Bytes]
    Gesamt: 4008 Bytes

LED-Status (GPIO BCM):
    GPIO 27 — Heartbeat  (grün,  blinkt 1 Hz = läuft)
    GPIO 22 — Netzwerk   (blau,  AN = WiFi OK)
    GPIO 24 — Daten      (gelb,  blinkt = Paket empfangen)
    GPIO 25 — Flash/Err  (rot,   aus bei normalem Betrieb)
"""

import os
import sys
import time
import socket
import logging
import threading
import subprocess

import spidev
import RPi.GPIO as GPIO

from status_leds import StatusLEDs

# ── Konfiguration ─────────────────────────────────────────────────────────────
NODE_ID        = int(os.environ.get("NODE_ID", "1"))
RPI5_IP        = os.environ.get("RPI5_IP", "192.168.42.1")
UDP_PORT       = 5000 + NODE_ID          # 5001 oder 5002
PACKET_BYTES   = 4008                    # Header(8) + 1000 × float32(4000)
SPI_BUS        = 0
SPI_DEVICE     = 0                       # /dev/spidev0.0
SPI_SPEED_HZ   = 10_000_000             # 10 MHz
SPI_MODE       = 0b00                   # CPOL=0, CPHA=0
DATA_READY_PIN = 17                     # BCM-Nummerierung (GPIO17 = Pin 11)

# Netzwerk-Prüfintervall in Sekunden
NET_CHECK_INTERVAL = 15.0

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format=f"[spi_rx Node{NODE_ID}] %(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger()

# ── Vorallokierter Sende-Buffer (vermeidet Allokierung im Hot-Path) ───────────
_DUMMY_TX = [0x00] * PACKET_BYTES       # Wird an Teensy gesendet (clocked out)


# ══════════════════════════════════════════════════════════════════════════════
#  Hilfsfunktionen
# ══════════════════════════════════════════════════════════════════════════════

def _check_wlan_connected(expected_ip: str = "") -> bool:
    """
    Prüft ob wlan0 die erwartete statische IP besitzt.
    Nutzt 'ip addr show wlan0' — kein Netzwerkzugriff nötig.
    """
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "wlan0"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = result.stdout
        # Entweder auf spezifische IP prüfen oder nur ob überhaupt eine IP da ist
        if expected_ip:
            return expected_ip in output
        return "inet " in output   # Irgendeine IP vorhanden
    except Exception:
        return False


def _network_monitor_thread(
    leds: StatusLEDs,
    rpi5_ip: str,
    stop_event: threading.Event,
) -> None:
    """
    Hintergrundthread: Prüft WLAN-Verbindung alle NET_CHECK_INTERVAL Sekunden
    und aktualisiert die blaue Netzwerk-LED.
    """
    # Statische Node-IP ableiten (z.B. 192.168.42.11 für Node 1)
    node_ip = f"192.168.42.1{NODE_ID}"

    while not stop_event.is_set():
        connected = _check_wlan_connected(node_ip)
        leds.set_network(connected)

        if not connected:
            log.warning(f"WLAN nicht verbunden (erwartet IP {node_ip})")
        else:
            log.debug(f"WLAN OK — IP {node_ip} bestätigt")

        # Warten mit regelmäßiger Überprüfung des Stop-Events
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
        f"SPI@{SPI_SPEED_HZ // 1_000_000}MHz | DATA_READY=GPIO{DATA_READY_PIN}"
    )

    # ── LED-Controller initialisieren ────────────────────────────────────────
    leds = StatusLEDs()
    leds.start()

    # ── GPIO Initialisierung ─────────────────────────────────────────────────
    # Hinweis: StatusLEDs.__init__() hat GPIO.setmode(BCM) bereits gesetzt
    GPIO.setwarnings(False)
    GPIO.setup(DATA_READY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    # ── SPI Initialisierung ──────────────────────────────────────────────────
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode         = SPI_MODE
    spi.no_cs        = False

    # ── UDP Socket ───────────────────────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)

    # ── Synchronisations-Event ───────────────────────────────────────────────
    data_ready_evt = threading.Event()
    stop_event     = threading.Event()

    def _on_rising_edge(channel: int) -> None:
        """GPIO-Interrupt-Callback (läuft im RPi.GPIO internen Thread)."""
        data_ready_evt.set()

    GPIO.add_event_detect(
        DATA_READY_PIN,
        GPIO.RISING,
        callback=_on_rising_edge,
        bouncetime=3         # 3 ms Entprellung
    )

    # ── Netzwerk-Monitor-Thread starten ──────────────────────────────────────
    net_thread = threading.Thread(
        target=_network_monitor_thread,
        args=(leds, RPI5_IP, stop_event),
        daemon=True,
        name="NetworkMonitor",
    )
    net_thread.start()

    # ── Startup-Sequenz (alle LEDs blinken = bereit) ──────────────────────────
    leds.startup_sequence()

    # ── Statistik-Variablen ──────────────────────────────────────────────────
    pkt_sent     = 0
    bytes_sent   = 0
    err_count    = 0
    t_stat_start = time.monotonic()

    log.info("Warte auf DATA_READY-Signal vom Teensy...")

    try:
        while True:
            # Warte auf steigende Flanke (DATA_READY HIGH vom Teensy)
            triggered = data_ready_evt.wait(timeout=2.0)

            if not triggered:
                # Timeout: kein Signal — Teensy ggf. nicht bereit
                log.debug("Warte weiter auf Teensy-Signal...")
                continue

            data_ready_evt.clear()

            # ── SPI-Transfer ─────────────────────────────────────────────────
            # RPi Zero (Master) clocked 4008 Dummy-Bytes hinaus;
            # Teensy (Slave) schiebt zeitgleich die Nutzdaten in MISO.
            try:
                rx  = spi.xfer2(_DUMMY_TX, SPI_SPEED_HZ)
                raw = bytes(rx)
            except Exception as exc:
                log.warning(f"SPI-Transfer-Fehler: {exc}")
                err_count += 1
                continue

            # ── UDP-Weiterleitung ─────────────────────────────────────────────
            # Keine Verarbeitung — rohe Bytes direkt an RPi 5 schicken
            try:
                sent = sock.sendto(raw, (RPI5_IP, UDP_PORT))
                pkt_sent   += 1
                bytes_sent += sent

                # Daten-LED blinken (throttled ~2 Hz, kein Flackern bei 100 Hz)
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
                    f"Throughput: {pps:.1f} Pkt/s | "
                    f"{kbps:.1f} KB/s | "
                    f"Fehler: {err_count}"
                )
                pkt_sent = bytes_sent = err_count = 0
                t_stat_start = time.monotonic()

    except KeyboardInterrupt:
        log.info("Gestoppt (KeyboardInterrupt).")
    finally:
        stop_event.set()
        leds.stop()          # LEDs aus (NICHT cleanup() — GPIO wird unten freigegeben)
        GPIO.cleanup()       # Gibt alle GPIO-Pins frei (inkl. LED-Pins)
        spi.close()
        sock.close()
        log.info("Alle Ressourcen freigegeben.")


if __name__ == "__main__":
    main()
