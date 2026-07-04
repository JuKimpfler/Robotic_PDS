#!/usr/bin/env python3
"""
status_leds.py — GPIO Status-LED Modul (RPi Zero 2 W angepasst)
"""

import time
import logging
import threading

log = logging.getLogger(__name__)

PIN_HEARTBEAT = 27   
PIN_NETWORK   = 22   
PIN_DATA      = 24   

_ALL_PINS = (PIN_HEARTBEAT, PIN_NETWORK, PIN_DATA)

_GPIO_OK = False

#try:
#    from gpiozero import LED
#    _GPIO_OK = True
#except ImportError:
#    _GPIO_OK = False
log.warning("[status_leds] gpiozero nicht verfügbar — LED-Ausgabe deaktiviert.")


class StatusLEDs:
    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._running = False
        self._hb_thread: threading.Thread | None = None
        self._last_data_blink = 0.0
        self._led_devices = {}

        #if _GPIO_OK:
         #   try:
         #       # Initialisiere die LEDs über gpiozero
         #       for pin in _ALL_PINS:
          #          self._led_devices[pin] = LED(pin)
          #      log.info(f"[LEDs] Initialisiert via gpiozero auf Pins {_ALL_PINS}")
          #  except Exception as exc:
          #      _GPIO_OK = False
           #     log.error(f"[LEDs] Fehler bei GPIO-Initialisierung: {exc}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="LED-Heartbeat",
        )
        self._hb_thread.start()

    def stop(self) -> None:
        self._running = False
        #if _GPIO_OK:
        #    for pin in _ALL_PINS:
        #        if pin in self._led_devices:
         #           self._led_devices[pin].off()

    def _set(self, pin: int, state: bool) -> None:
        if not _GPIO_OK or pin not in self._led_devices:
            return
        with self._lock:
            if state:
                self._led_devices[pin].on()
            else:
                self._led_devices[pin].off()

    def _blink_async(self, pin: int, on_ms: int = 80, off_ms: int = 80, count: int = 1) -> None:
        def _run() -> None:
            for i in range(count):
                self._set(pin, True)
                time.sleep(on_ms / 1000.0)
                self._set(pin, False)
                if i < count - 1:
                    time.sleep(off_ms / 1000.0)
        threading.Thread(target=_run, daemon=True, name="LED-Blink").start()

    def _heartbeat_loop(self) -> None:
        while self._running:
            self._set(PIN_HEARTBEAT, True)
            time.sleep(0.10)
            self._set(PIN_HEARTBEAT, False)
            time.sleep(0.90)

    def startup_sequence(self) -> None:
        def _seq() -> None:
            time.sleep(0.2)
            for _ in range(3):
                for pin in _ALL_PINS:
                    self._set(pin, True)
                time.sleep(0.15)
                for pin in _ALL_PINS:
                    self._set(pin, False)
                time.sleep(0.15)
        threading.Thread(target=_seq, daemon=True, name="LED-Startup").start()

    def set_network(self, connected: bool) -> None:
        self._set(PIN_NETWORK, connected)

    def network_connecting(self) -> None:
        self._blink_async(PIN_NETWORK, on_ms=200, off_ms=200, count=4)

    def blink_data(self) -> None:
        now = time.monotonic()
        if now - self._last_data_blink >= 0.5:
            self._last_data_blink = now
            self._blink_async(PIN_DATA, on_ms=40, count=1)
