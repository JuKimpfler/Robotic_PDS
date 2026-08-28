#!/usr/bin/env python3
"""
status_leds.py — GPIO-Status-LEDs des RPi Zero 2 W Node
==========================================================
Drei LEDs zeigen den Zustand des Nodes an:

  🟢 Heartbeat (GPIO 27)  kurzes Blinken 1x/s -> Dienst laeuft
  🔵 Netzwerk  (GPIO 22)  dauerhaft an        -> WLAN-Verbindung zum RPi 5
  🟡 Daten     (GPIO 24)  Flackern            -> Teensy sendet ueber UART

Wird von `uart_receiver.py` importiert
und mitgesteuert — es gibt bewusst KEINEN eigenen Dienst dafuer: die
Informationen "Netzwerk da" und "Daten kommen an" liegen genau dort vor.

gpiozero ist eine OPTIONALE Abhaengigkeit. Fehlt sie (oder laeuft der Code
auf einem PC), sind alle Methoden funktionslose No-Ops — der Node
funktioniert dann vollstaendig, nur ohne LED-Anzeige.

Frueherer Stand: die komplette GPIO-Ansteuerung war auskommentiert und
`_GPIO_OK` fest auf False gesetzt, ausserdem hat das Modul beim Import
bedingungslos eine Warnung geloggt. Die im README beschriebenen LEDs haben
deshalb nie funktioniert.

Direktaufruf zum Testen der Verkabelung:
    python3 status_leds.py            # Lauflicht ueber alle drei LEDs
"""
from __future__ import annotations

import time
import logging
import threading

log = logging.getLogger(__name__)

PIN_HEARTBEAT = 27
PIN_NETWORK   = 22
PIN_DATA      = 24

_ALL_PINS = (PIN_HEARTBEAT, PIN_NETWORK, PIN_DATA)

# Kuerzester Abstand zwischen zwei Daten-Blinkern (sonst waere die LED bei
# 100 Pkt/s dauerhaft an und man saehe keinen Unterschied zu "kein Empfang").
_DATA_BLINK_MIN_INTERVAL = 0.25

try:
    from gpiozero import LED
    _GPIO_AVAILABLE = True
    _GPIO_IMPORT_ERROR = ""
except Exception as _exc:      # ImportError, aber auch fehlende Pin-Factory
    LED = None                 # type: ignore[assignment]
    _GPIO_AVAILABLE = False
    _GPIO_IMPORT_ERROR = str(_exc)


class StatusLEDs:
    """Steuert die drei Status-LEDs. Ohne gpiozero ein reiner No-Op."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._hb_thread: threading.Thread | None = None
        self._last_data_blink = 0.0
        self._data_pending = False
        self._network_on = False
        self._leds: dict[int, object] = {}
        self._enabled = False

        if not _GPIO_AVAILABLE:
            log.info("gpiozero nicht verfügbar (%s) — LED-Anzeige deaktiviert.",
                     _GPIO_IMPORT_ERROR)
            return

        try:
            for pin in _ALL_PINS:
                self._leds[pin] = LED(pin)
            self._enabled = True
            log.info("Status-LEDs initialisiert (GPIO %s).",
                     ", ".join(str(p) for p in _ALL_PINS))
        except Exception as exc:      # z. B. GPIO bereits belegt
            log.warning("GPIO-Initialisierung fehlgeschlagen (%s) — LEDs deaktiviert.", exc)
            self._close_all()
            self._enabled = False

    # ── intern ────────────────────────────────────────────────────────────
    def _close_all(self) -> None:
        for led in self._leds.values():
            try:
                led.close()        # type: ignore[attr-defined]
            except Exception:
                pass
        self._leds.clear()

    def _set(self, pin: int, state: bool) -> None:
        if not self._enabled:
            return
        led = self._leds.get(pin)
        if led is None:
            return
        with self._lock:
            try:
                if state:
                    led.on()       # type: ignore[attr-defined]
                else:
                    led.off()      # type: ignore[attr-defined]
            except Exception as exc:
                log.debug("LED %d konnte nicht geschaltet werden: %s", pin, exc)

    # ── Lebenszyklus ──────────────────────────────────────────────────────
    def start(self) -> None:
        """Startet den Heartbeat-Thread.

        Ein EINZIGER Thread bedient Heartbeat UND Daten-LED. Frueher wurde
        fuer jeden Blinker ein eigener Thread erzeugt — bei 100 Pkt/s waeren
        das auf einem Pi Zero mehrere Thread-Erzeugungen pro Sekunde
        gewesen, nur um eine LED kurz anzuschalten.
        """
        if self._running or not self._enabled:
            return
        self._running = True
        self._hb_thread = threading.Thread(
            target=self._blink_loop, daemon=True, name="LED-Blink"
        )
        self._hb_thread.start()

    def stop(self) -> None:
        self._running = False
        thread = self._hb_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        for pin in _ALL_PINS:
            self._set(pin, False)
        self._close_all()
        self._enabled = False

    # ── Blink-Schleife (ein Thread fuer alles) ────────────────────────────
    def _blink_loop(self) -> None:
        tick = 0
        while self._running:
            # Heartbeat: 100 ms an, 900 ms aus
            phase = tick % 10
            self._set(PIN_HEARTBEAT, phase == 0)

            # Daten: einmal kurz aufblitzen, wenn seit dem letzten Tick
            # Bytes angekommen sind.
            if self._data_pending:
                self._data_pending = False
                self._set(PIN_DATA, True)
            elif phase % 2 == 1:
                self._set(PIN_DATA, False)

            tick += 1
            time.sleep(0.1)

    # ── Oeffentliche Statusmeldungen ──────────────────────────────────────
    def startup_sequence(self) -> None:
        """Kurzes Lauflicht beim Start — zeigt, dass alle drei LEDs leben."""
        if not self._enabled:
            return

        def _seq() -> None:
            for _ in range(3):
                for pin in _ALL_PINS:
                    self._set(pin, True)
                time.sleep(0.12)
                for pin in _ALL_PINS:
                    self._set(pin, False)
                time.sleep(0.12)
            self._set(PIN_NETWORK, self._network_on)

        threading.Thread(target=_seq, daemon=True, name="LED-Startup").start()

    def set_network(self, connected: bool) -> None:
        if connected == self._network_on:
            return
        self._network_on = connected
        self._set(PIN_NETWORK, connected)

    def blink_data(self) -> None:
        """Aus der Empfangsschleife aufgerufen, sobald UART-Bytes ankommen.

        Bewusst extrem billig (ein Vergleich + eine Zuweisung): die Funktion
        laeuft im 100-Hz-Weiterleitungspfad des Nodes.
        """
        now = time.monotonic()
        if now - self._last_data_blink >= _DATA_BLINK_MIN_INTERVAL:
            self._last_data_blink = now
            self._data_pending = True


# ══════════════════════════════════════════════════════════════════════════
#  Direktaufruf: LED-Verkabelung testen
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="[status_leds] %(levelname)-8s %(message)s")
    leds = StatusLEDs()
    if not leds._enabled:      # noqa: SLF001 — bewusst, reines Testwerkzeug
        print("Keine GPIO-Unterstützung — nichts zu testen.")
        print("  Installation auf dem Pi:  sudo apt install python3-gpiozero python3-lgpio")
        return 1

    print(f"Testlauf — Heartbeat GPIO{PIN_HEARTBEAT}, Netzwerk GPIO{PIN_NETWORK}, "
          f"Daten GPIO{PIN_DATA}. Abbruch mit Strg+C.")
    leds.start()
    leds.startup_sequence()
    leds.set_network(True)
    try:
        while True:
            leds.blink_data()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        leds.stop()
        print("\nBeendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
