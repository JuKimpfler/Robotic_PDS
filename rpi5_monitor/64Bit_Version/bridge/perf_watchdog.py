"""
bridge/perf_watchdog.py — Überlast-Erkennung für den Live-Plotter
=================================================================

Warum ein eigener Wächter? Der Plotter läuft im GUI-Thread, der gleichzeitig
die QML-Oberfläche zeichnet und den 100-Hz-Takt der Fernsteuerung hält. Wenn
das Zeichnen zu teuer wird, merkt das NUR der Event-Loop selbst: die Timer
(20 Hz Poll, 100 Hz Sendetakt) feuern dann später als eingestellt, die
Oberfläche ruckelt, und auf einem Raspberry Pi 4 (2 GB) kann die GUI ganz
einfrieren.

Der Wächter misst genau das: er hat einen eigenen Timer und vergleicht die
tatsächlich vergangene Zeit mit der erwarteten. Bleibt der Event-Loop
wiederholt hinterher, gibt es eine Warnung — und bei anhaltender Überlastung
wird der Plotter abgeschaltet, damit der Rest der Anwendung (Tabelle,
Fernsteuerung) weiterläuft.

Der Wächter wertet die Last NUR aus, wenn der Plotter tatsächlich aktiv ist
(enabled, sichtbar, nicht schon überlastet). So wird eine Überlast, die von
einem anderen Teil der App käme, nicht dem Plotter angelastet — und ein
Plotter, der schon aus ist, wird nicht noch einmal „bestraft“.

Schwellen kommen aus settings.json -> "plotter" (siehe app_settings.py).
"""
from __future__ import annotations

import logging
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

log = logging.getLogger("bridge.plot.perf")


class PerfWatchdog(QObject):
    # Grund der Abschaltung (Plotter soll sich abschalten).
    overload = pyqtSignal(str)
    # Nicht-fatal: die Last ist hoch, aber der Plotter läuft noch.
    warning = pyqtSignal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        measure_ms: int = 250,
        warn_stall_ms: float = 35.0,
        disable_stall_ms: float = 80.0,
        streak: int = 5,
    ) -> None:
        super().__init__(parent)
        self._measure_ms = max(50, int(measure_ms))
        self._warn_stall_ms = float(warn_stall_ms)
        self._disable_stall_ms = float(disable_stall_ms)
        self._streak_n = max(1, int(streak))

        self._active = False
        self._warned = False
        self._streak = 0
        self._last = monotonic()

        self._timer = QTimer(self)
        self._timer.setInterval(self._measure_ms)
        self._timer.timeout.connect(self._tick)

    # ── Steuerung ─────────────────────────────────────────────────────────
    def start(self) -> None:
        self._last = monotonic()
        self._streak = 0
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_active(self, active: bool) -> None:
        """Plotter liefert gerade Arbeit ab (und darf deshalb Last machen)."""
        self._active = bool(active)
        if not self._active:
            # Wenn der Plotter inaktiv ist, zählt ein Stall nicht — er käme
            # sonst von woanders her, und wir würden fälschlich warnen.
            self._streak = 0

    def reset(self) -> None:
        """Nach manuellem Re-Aktivieren wieder von vorne zählen."""
        self._streak = 0
        self._warned = False
        self._last = monotonic()

    # ── Messung ───────────────────────────────────────────────────────────
    def _tick(self) -> None:
        now = monotonic()
        dt_ms = (now - self._last) * 1000.0
        self._last = now

        if not self._active:
            return

        # „Stall“ = wie viel mehr Zeit verging, als der Takt vorgibt. Ein
        # gesunder Event-Loop kommt mit dt ≈ measure_ms heraus; ist er
        # blockiert, wird dt deutlich größer.
        stall = max(0.0, dt_ms - self._measure_ms)

        if stall >= self._disable_stall_ms:
            self._streak += 1
        else:
            self._streak = 0

        if self._streak >= self._streak_n:
            self._streak = 0
            self.overload.emit(
                "Der Event-Loop des GUI-Threads kommt nicht mehr hinterher "
                f"(Staulast {stall:.0f} ms über dem {self._measure_ms} ms-Takt, "
                f"{self._streak_n}× hintereinander)."
            )
            return

        if not self._warned and stall >= self._warn_stall_ms:
            self._warned = True
            self.warning.emit(
                "Plotter verbraucht viel Rechenzeit "
                f"(Staulast {stall:.0f} ms). Bei weiterer Überlastung wird "
                "der Plotter automatisch abgeschaltet."
            )
