"""
bridge/controller_bridge.py — PS4-Controller (USB) -> Fast-Param-Kanal
=========================================================================
Pollt einen per USB angeschlossenen PS4-Controller (DualShock 4) über
pygame und schreibt die Werte, sobald ein Controller erkannt wird, MIT
PRIORITÄT direkt in den ParamStore von ParamBridge (siehe param_bridge.py)
— genau wie zuvor setFastFloat()/Joystick.moved() das von der Touch-UI
aus taten. Der bestehende _fast_timer in ParamBridge sendet weiterhin
unverändert alle 10 ms, was gerade im Store steht; hier wird nur
festgelegt, WER den Store zwischen Touch und Controller füllen darf.

Anforderung "Controller hat Vorrang vor Touch": wird NICHT dadurch gelöst,
dass hier ein Flag den Touch-Callback in QML blockiert (das bliebe eine
Wettlaufsituation) — stattdessen exponiert diese Klasse eine `connected`-
Property, an die ParamsView.qml die Touch-Widgets bindet (enabled: false
solange ein Controller verbunden ist). Die Werte selbst kommen dann
ausschließlich noch von hier.

Kalibrierung: Achsen-/Button-Indizes können je nach OS/SDL-Version leicht
abweichen. Am schnellsten prüfbar mit dem eigenständigen Skript
`ps4_fast_controller.py --list-axes` (falls vorhanden) oder testweise
Werte hier ausgeben lassen.
"""
from __future__ import annotations

import logging
import os

# Muss VOR "import pygame" gesetzt werden: verhindert, dass SDL versucht,
# ein eigenes Video-/Fenstersystem zu initialisieren, das mit der
# laufenden Qt-Quick-Anzeige kollidieren könnte. Wir nutzen von pygame
# ausschließlich die Joystick-Subsystem-Funktionen.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

from config import PARAM_FAST_SEND_INTERVAL_MS

log = logging.getLogger("bridge.controller")

# ══════════════════════════════════════════════════════════════════════════
#  MAPPING — bei Bedarf anpassen (siehe Docstring oben zur Kalibrierung)
# ══════════════════════════════════════════════════════════════════════════
AXIS_LEFT_X = 0    # linker Stick, links/rechts  -> fast_floats[0] (Joystick_X)
AXIS_LEFT_Y = 1    # linker Stick, hoch/runter   -> fast_floats[1] (Joystick_Y)
AXIS_RIGHT_X = 2   # rechter Stick, links/rechts -> fast_floats[2] (Rotation)
AXIS_R2 = 5        # R2-Trigger (ruhend -1, voll +1) -> fast_floats[3] (Speed)

BUTTON_R1 = 10     # -> fast_floats[4] (Dribbler) = Maximalwert solange gehalten
BUTTON_L1 = 9      # -> fast_floats[4] (Dribbler) = Minimalwert solange gehalten

DEADZONE = 0.08


def _apply_deadzone(value: float, deadzone: float = DEADZONE) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(scaled, 1.0)


class ControllerBridge(QObject):
    """Erkennt PS4-Controller (Hot-Plug-fähig durch Polling) und schreibt
    dessen Werte mit derselben Frequenz wie der Fast-Kanal (100 Hz) in
    den ParamStore der übergebenen ParamBridge."""

    connectedChanged = pyqtSignal()
    valuesChanged = pyqtSignal()

    def __init__(self, param_bridge, parent=None) -> None:
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._connected = False
        self._name = ""
        self._joystick: pygame.joystick.JoystickType | None = None
        self._values: list[float] = [0.0] * 5
        self._stick_x = 0.0
        self._stick_y = 0.0

        try:
            pygame.init()
            pygame.joystick.init()
        except pygame.error as exc:
            log.error("pygame/SDL konnte nicht initialisiert werden: %s", exc)

        self._timer = QTimer(self)
        self._timer.setInterval(PARAM_FAST_SEND_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ── Properties (für QML) ─────────────────────────────────────────────
    @pyqtProperty(bool, notify=connectedChanged)
    def connected(self) -> bool:
        return self._connected

    @pyqtProperty(str, notify=connectedChanged)
    def name(self) -> str:
        return self._name

    @pyqtProperty("QVariantList", notify=valuesChanged)
    def values(self) -> list[float]:
        """Aktuelle 5 Fast-Floats (index-gleich zu fast_floats/ParamStore),
        für die Live-Anzeige der Touch-Widgets während der Controller aktiv ist."""
        return self._values

    @pyqtProperty(float, notify=valuesChanged)
    def stickNormX(self) -> float:
        """Normierte Position -1..1 des linken Sticks (X), zur Anzeige im
        Joystick-Widget (siehe Joystick.qml externalNormX)."""
        return self._stick_x

    @pyqtProperty(float, notify=valuesChanged)
    def stickNormY(self) -> float:
        return self._stick_y

    # ── Polling ───────────────────────────────────────────────────────────
    def _poll(self) -> None:
        try:
            pygame.event.pump()
            count = pygame.joystick.get_count()
        except pygame.error as exc:
            log.warning("pygame-Event-Pump fehlgeschlagen: %s", exc)
            return

        if count == 0:
            if self._connected:
                self._connected = False
                self._joystick = None
                self._name = ""
                log.info("Controller getrennt — Touch-Eingabe wieder aktiv.")
                self.connectedChanged.emit()
            return

        if self._joystick is None:
            try:
                self._joystick = pygame.joystick.Joystick(0)
                self._joystick.init()
                self._name = self._joystick.get_name()
                self._connected = True
                log.info("Controller verbunden: '%s' — Touch-Eingabe gesperrt.", self._name)
                self.connectedChanged.emit()
            except pygame.error as exc:
                log.warning("Controller-Initialisierung fehlgeschlagen: %s", exc)
                return

        try:
            self._read_and_apply()
        except pygame.error as exc:
            log.warning("Controller-Lesefehler (vermutlich getrennt): %s", exc)
            self._connected = False
            self._joystick = None
            self.connectedChanged.emit()

    def _read_and_apply(self) -> None:
        js = self._joystick
        num_axes = js.get_numaxes()
        num_buttons = js.get_numbuttons()

        raw_x = _apply_deadzone(js.get_axis(AXIS_LEFT_X)) if num_axes > AXIS_LEFT_X else 0.0
        raw_y = _apply_deadzone(js.get_axis(AXIS_LEFT_Y)) if num_axes > AXIS_LEFT_Y else 0.0
        raw_rot = _apply_deadzone(js.get_axis(AXIS_RIGHT_X)) if num_axes > AXIS_RIGHT_X else 0.0
        raw_r2 = js.get_axis(AXIS_R2) if num_axes > AXIS_R2 else -1.0
        r1_held = js.get_button(BUTTON_R1) if num_buttons > BUTTON_R1 else 0
        l1_held = js.get_button(BUTTON_L1) if num_buttons > BUTTON_L1 else 0

        # Wertebereiche aus param_config.json (live, respektiert also auch
        # nachträgliche Anpassungen dort) statt fest verdrahteter Zahlen.
        ranges = self._param_bridge.fast_float_ranges()

        def scale_bipolar(idx: int, norm: float) -> float:
            lo, hi = ranges.get(idx, (-100.0, 100.0))
            return norm * (hi if norm >= 0 else -lo)

        def scale_unipolar(idx: int, norm_minus1_to_1: float) -> float:
            lo, hi = ranges.get(idx, (0.0, 100.0))
            return lo + (norm_minus1_to_1 + 1.0) / 2.0 * (hi - lo)

        joystick_x = scale_bipolar(0, raw_x)
        joystick_y = scale_bipolar(1, -raw_y)          # Bildschirm-Y invertiert
        rotation = scale_bipolar(2, raw_rot)
        speed = scale_unipolar(3, raw_r2)

        dribbler_lo, dribbler_hi = ranges.get(4, (-100.0, 100.0))
        if r1_held and not l1_held:
            dribbler = dribbler_hi
        elif l1_held and not r1_held:
            dribbler = dribbler_lo
        else:
            dribbler = 0.0

        self._values = [joystick_x, joystick_y, rotation, speed, dribbler]
        self._stick_x = raw_x
        self._stick_y = raw_y

        self._param_bridge.apply_controller_values(self._values)
        self.valuesChanged.emit()

    def shutdown(self) -> None:
        self._timer.stop()
        try:
            pygame.joystick.quit()
            pygame.quit()
        except pygame.error:
            pass
