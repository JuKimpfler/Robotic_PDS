#!/usr/bin/env python3
"""
status_leds.py — GPIO Status-LED Modul (RPi Zero W Nodes)
===========================================================
Steuert 4 Hardware-LEDs für den kopflosen (headless) Betrieb
der RPi Zero W Nodes.

LED-Belegung (BCM-Nummerierung):
  GPIO 27  (Pin 13) — Heartbeat  : Grün  — Blinkt 1 Hz = System läuft
  GPIO 22  (Pin 15) — Netzwerk   : Blau  — AN = WLAN verbunden
  GPIO 24  (Pin 18) — Daten      : Gelb  — Blinkt = uart/UDP-Paket aktiv
  GPIO 25  (Pin 22) — Flash/Err  : Rot   — AN = Flashen, Schnell = Fehler

Schaltung pro LED (Reihenschaltung):
  GPIO-Pin ──[330 Ω]──[>|]── GND
                       LED

Strom:  3,3 V / 330 Ω ≈ 10 mA  (für Standard-5-mm-LEDs ausreichend)

Status-Tabelle:
  ╔══════════════╦══════════════════════════════════════════╗
  ║ LED          ║ Bedeutung                                ║
  ╠══════════════╬══════════════════════════════════════════╣
  ║ Heartbeat 🟢 ║ Blinkt 1 Hz       = Dienste laufen      ║
  ║              ║ Dauerhaft AN       = Boot läuft noch     ║
  ║              ║ Aus                = System abgestürzt   ║
  ╠══════════════╬══════════════════════════════════════════╣
  ║ Netzwerk  🔵 ║ Dauerhaft AN       = WiFi verbunden      ║
  ║              ║ 4× Blinken         = Verbindungsversuch  ║
  ║              ║ Aus                = Kein WLAN           ║
  ╠══════════════╬══════════════════════════════════════════╣
  ║ Daten     🟡 ║ Blinkt ~2 Hz       = Datenstrom aktiv   ║
  ║              ║ Aus                = Kein Teensy-Signal  ║
  ╠══════════════╬══════════════════════════════════════════╣
  ║ Flash/Err 🔴 ║ Dauerhaft AN       = Flash läuft         ║
  ║              ║ 3× langsam         = Flash OK            ║
  ║              ║ 10× schnell        = Flash Fehler        ║
  ║              ║ Aus                = Idle                ║
  ╚══════════════╩══════════════════════════════════════════╝
"""

import time
import logging
import threading

log = logging.getLogger(__name__)

# ── Pin-Definitionen (BCM) ────────────────────────────────────────────────────
PIN_HEARTBEAT = 27   # Grün:  Systemzustand / Alive
PIN_NETWORK   = 22   # Blau:  WLAN-Verbindungsstatus
PIN_DATA      = 24   # Gelb:  uart→UDP Datenaktivität
PIN_FLASH     = 25   # Rot:   Flash-Vorgang / Fehler

_ALL_PINS = (PIN_HEARTBEAT, PIN_NETWORK, PIN_DATA, PIN_FLASH)

# GPIO-Import  (auf Nicht-RPi-Systemen graceful degradieren)
try:
    import RPi.GPIO as GPIO
    _GPIO_OK = True
except (ImportError, RuntimeError):
    _GPIO_OK = False
    log.warning("[status_leds] RPi.GPIO nicht verfügbar — LED-Ausgabe deaktiviert.")


# ══════════════════════════════════════════════════════════════════════════════
#  StatusLEDs
# ══════════════════════════════════════════════════════════════════════════════

class StatusLEDs:
    """
    Thread-sicherer LED-Controller für RPi Zero W Nodes.

    Lebenszykus:
        leds = StatusLEDs()
        leds.start()                  # Heartbeat-Thread starten
        leds.startup_sequence()       # Boot-OK-Signal (alle LEDs 3×)
        ...
        leds.stop()                   # Alle LEDs aus, Thread stoppen
        # GPIO.cleanup() liegt beim aufrufenden Modul (z.B. spi_receiver.py)
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._running = False
        self._hb_thread: threading.Thread | None = None
        # Throttle für blink_data(): max. 1 Blink alle 500 ms
        self._last_data_blink = 0.0

        if _GPIO_OK:
            # Pins nur konfigurieren, wenn GPIO noch nicht im BCM-Modus ist
            try:
                GPIO.setmode(GPIO.BCM)
            except RuntimeError:
                pass   # Modus bereits gesetzt — ok
            GPIO.setwarnings(False)
            for pin in _ALL_PINS:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            log.info(
                f"[LEDs] Initialisiert — "
                f"HB=GPIO{PIN_HEARTBEAT}  NET=GPIO{PIN_NETWORK}  "
                f"DATA=GPIO{PIN_DATA}  FLASH=GPIO{PIN_FLASH}"
            )

    # ── Lebenszyklus ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Startet den Heartbeat-Hintergrundthread (1 Hz blinken)."""
        if self._running:
            return
        self._running = True
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="LED-Heartbeat",
        )
        self._hb_thread.start()
        log.debug("[LEDs] Heartbeat-Thread gestartet.")

    def stop(self) -> None:
        """Stoppt den Heartbeat-Thread und schaltet alle LEDs aus."""
        self._running = False
        if _GPIO_OK:
            for pin in _ALL_PINS:
                try:
                    GPIO.output(pin, GPIO.LOW)
                except RuntimeError:
                    pass
        log.debug("[LEDs] Alle LEDs ausgeschaltet.")

    # ── Interne Helfer ────────────────────────────────────────────────────────

    def _set(self, pin: int, state: bool) -> None:
        """Thread-sicheres GPIO-Schreiben."""
        if not _GPIO_OK:
            return
        with self._lock:
            try:
                GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
            except RuntimeError:
                pass   # GPIO bereits aufgeräumt

    def _blink_async(
        self,
        pin: int,
        on_ms:  int = 80,
        off_ms: int = 80,
        count:  int = 1,
    ) -> None:
        """Startet einen Blink-Sequence-Thread (non-blocking)."""
        def _run() -> None:
            for i in range(count):
                self._set(pin, True)
                time.sleep(on_ms  / 1000.0)
                self._set(pin, False)
                if i < count - 1:
                    time.sleep(off_ms / 1000.0)
        threading.Thread(target=_run, daemon=True, name="LED-Blink").start()

    # ── Heartbeat (intern) ────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """100 ms AN → 900 ms AUS = 1-Hz-Blinken der grünen LED."""
        while self._running:
            self._set(PIN_HEARTBEAT, True)
            time.sleep(0.10)
            self._set(PIN_HEARTBEAT, False)
            time.sleep(0.90)

    # ── Öffentliche API ───────────────────────────────────────────────────────

    def startup_sequence(self) -> None:
        """
        Boot-Sequenz: Alle LEDs 3× gemeinsam aufblitzen.
        Signal: System hochgefahren, Dienste bereit.
        """
        def _seq() -> None:
            time.sleep(0.2)   # kurze Pause nach start()
            for _ in range(3):
                for pin in _ALL_PINS:
                    self._set(pin, True)
                time.sleep(0.15)
                for pin in _ALL_PINS:
                    self._set(pin, False)
                time.sleep(0.15)
        threading.Thread(target=_seq, daemon=True, name="LED-Startup").start()

    def set_network(self, connected: bool) -> None:
        """
        Blaue Netzwerk-LED:
          connected=True  → dauerhaft AN  (WLAN verbunden, RPi 5 erreichbar)
          connected=False → dauerhaft AUS (kein WLAN)
        """
        self._set(PIN_NETWORK, connected)

    def network_connecting(self) -> None:
        """4× schnelles Blinken = WLAN-Verbindungsaufbau läuft."""
        self._blink_async(PIN_NETWORK, on_ms=200, off_ms=200, count=4)

    def blink_data(self) -> None:
        """
        Gelbe LED kurz aufblitzen = Datenpaket gesendet.
        Throttled: maximal 1 Blink alle 500 ms (verhindert Flackern bei 100 Hz).
        """
        now = time.monotonic()
        if now - self._last_data_blink >= 0.5:
            self._last_data_blink = now
            self._blink_async(PIN_DATA, on_ms=40, count=1)

    def set_flash_active(self, active: bool) -> None:
        """
        Rote Flash-LED:
          active=True  → dauerhaft AN  (Firmware wird übertragen / geflasht)
          active=False → AUS           (Idle)
        """
        self._set(PIN_FLASH, active)

    def flash_success(self) -> None:
        """3× langsames Blinken der roten LED = Flash erfolgreich."""
        self._blink_async(PIN_FLASH, on_ms=400, off_ms=200, count=3)

    def flash_error(self) -> None:
        """10× schnelles Blinken der roten LED = Flash-Fehler."""
        self._blink_async(PIN_FLASH, on_ms=80, off_ms=80, count=10)
