"""
bridge/controller_bridge.py — PS4-Controller (USB) -> Fast-Param-Kanal
=========================================================================
Liest einen per USB angeschlossenen PS4-Controller (DualShock 4) über
pygame/SDL und schreibt die Werte, sobald ein Controller erkannt wird, MIT
PRIORITÄT direkt in den ParamStore von ParamBridge (siehe param_bridge.py)
— genau wie zuvor setFastFloat()/Joystick.moved() das von der Touch-UI
aus taten. Hier wird nur festgelegt, WER den Store zwischen Touch und
Controller füllen darf.

Anforderung "Controller hat Vorrang vor Touch": wird NICHT dadurch gelöst,
dass hier ein Flag den Touch-Callback in QML blockiert (das bliebe eine
Wettlaufsituation) — stattdessen exponiert diese Klasse eine `connected`-
Property, an die ParamsView.qml die Touch-Widgets bindet (enabled: false
solange ein Controller verbunden ist). Die Werte selbst kommen dann
ausschließlich noch von hier.

────────────────────────────────────────────────────────────────────────────
LATENZ — WARUM DIESE KLASSE KEINEN EIGENEN TIMER MEHR HAT
────────────────────────────────────────────────────────────────────────────
Früher lief hier ein eigener QTimer mit 10 ms, unabhängig vom 10-ms-Timer,
der in ParamBridge das Fast-Paket verschickt. Zwei gleich schnelle, aber
nicht gekoppelte Timer haben eine zufällige, über die Laufzeit driftende
Phasenlage: im ungünstigen Fall schreibt der Controller-Timer den neuen
Stand unmittelbar NACHDEM der Sende-Timer das Paket gepackt hat — der Wert
wartet dann volle 10 ms auf den nächsten Sendeslot. Im Mittel kostete das
5 ms, im Maximum 10 ms, und zwar schwankend (Jitter fühlt sich subjektiv
schlimmer an als eine konstante Verzögerung).

Jetzt ruft ParamBridge._worker_tick() direkt vor dem Packen poll() auf
(siehe param_bridge.py). Damit ist der gesendete Stand garantiert der
zuletzt gelesene.

Und zwar aus einem EIGENEN THREAD, nicht mehr aus dem GUI-Thread: ein
QTimer feuert erst, wenn die Ereignisschleife wieder drankommt, also erst
nachdem der Plotter neu gezeichnet, die Tabelle neu berechnet und das Bild
gerendert wurde. Der Abtastzeitpunkt des Controllers ist dadurch
unregelmäßig gewandert — genau das fühlt sich als "die Joystick-Abfrage
stockt" an. Deshalb wird pygame/SDL hier auch erst beim ersten poll()
initialisiert: das Joystick-Subsystem muss aus demselben Thread gepumpt
werden, aus dem es aufgesetzt wurde.

Kalibrierung: Achsen-/Button-Indizes können je nach OS/SDL-Version
abweichen. Zwei Möglichkeiten ohne Code-Änderung:
  * `controller_config.json` neben config.py anlegen (siehe _load_mapping)
  * Logger "bridge.controller" auf DEBUG stellen — dann werden alle rohen
    Achsen/Buttons 1x pro Sekunde ausgegeben.
"""
from __future__ import annotations

import json
import logging
import os
import time

# Müssen VOR "import pygame" gesetzt werden: verhindert, dass SDL versucht,
# ein eigenes Video-/Audio-System zu initialisieren, das mit der laufenden
# Qt-Quick-Anzeige kollidieren oder (bei ALSA auf schlanken Pi-Images) in
# lange Timeouts laufen könnte. Wir nutzen von pygame ausschließlich die
# Joystick-Subsystem-Funktionen.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# pygame ist eine OPTIONALE Abhaengigkeit. Fehlt sie, laeuft die komplette
# GUI unveraendert weiter — nur die Controller-Unterstuetzung ist dann aus
# und die Fast-Params werden wie bisher per Touch bedient.
#
# Das ist kein theoretischer Fall: fuer Python 3.14 gibt es (Stand 08/2026)
# kein pygame-Wheel, und der Quell-Build scheitert. Ohne diese Fallunter-
# scheidung hat ein fehlendes pygame den Import von controller_bridge ->
# param_bridge -> app_bridge mitgerissen und damit den Start der GESAMTEN
# Oberflaeche verhindert. Siehe Doku/PS4_Controller_Implementierung.md.
try:
    import pygame
    _PYGAME_IMPORT_ERROR: str | None = None
except Exception as _exc:            # ImportError, aber auch SDL-Ladefehler
    pygame = None
    _PYGAME_IMPORT_ERROR = str(_exc)

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal

from config import CONTROLLER_CONFIG_PATH, CONTROLLER_UI_NOTIFY_MS
from bridge.utils import safe_slot

log = logging.getLogger("bridge.controller")

# ══════════════════════════════════════════════════════════════════════════
#  MAPPING — Standardwerte, per controller_config.json überschreibbar
# ══════════════════════════════════════════════════════════════════════════
DEFAULT_MAPPING = {
    "axis_left_x":  0,    # linker Stick, links/rechts  -> fast_floats[0] (Joystick_X)
    "axis_left_y":  1,    # linker Stick, hoch/runter   -> fast_floats[1] (Joystick_Y)
    "axis_right_x": 2,    # rechter Stick, links/rechts -> fast_floats[2] (Rotation)
    "axis_r2":      5,    # R2-Trigger (ruhend -1, voll +1) -> fast_floats[3] (Speed)
    "button_r1":   10,    # -> fast_floats[4] (Dribbler) = Maximalwert solange gehalten
    "button_l1":    9,    # -> fast_floats[4] (Dribbler) = Minimalwert solange gehalten
    "deadzone":  0.08,
}


def _load_mapping() -> dict:
    """Optionale controller_config.json neben config.py einlesen.

    Fehlt die Datei (Normalfall), gelten DEFAULT_MAPPING-Werte. Damit lässt
    sich eine abweichende SDL-Belegung anpassen, ohne Code zu ändern und
    ohne dass ein `git pull` die Anpassung wieder überschreibt.
    """
    mapping = dict(DEFAULT_MAPPING)
    try:
        with open(CONTROLLER_CONFIG_PATH, "r", encoding="utf-8") as fh:
            user = json.load(fh)
    except FileNotFoundError:
        return mapping
    except (OSError, ValueError) as exc:
        log.warning("%s konnte nicht gelesen werden (%s) — Standard-Mapping aktiv.",
                    CONTROLLER_CONFIG_PATH.name, exc)
        return mapping

    for key in mapping:
        if key in user:
            mapping[key] = user[key]
    log.info("Controller-Mapping aus %s übernommen.", CONTROLLER_CONFIG_PATH.name)
    return mapping


def _apply_deadzone(value: float, deadzone: float) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    scaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(scaled, 1.0)


class ControllerBridge(QObject):
    """Erkennt PS4-Controller (Hot-Plug-fähig durch Polling) und schreibt
    dessen Werte in den ParamStore der übergebenen ParamBridge.

    poll() wird von ParamBridge._worker_tick() mit 100 Hz aufgerufen, und zwar
    aus dem Sende-Thread — siehe Modul-Docstring, Abschnitt LATENZ."""

    connectedChanged = pyqtSignal()
    valuesChanged = pyqtSignal()

    # Der erste Poll direkt nach dem Verbinden wird verworfen: SDL liefert
    # für noch nie bewegte Achsen 0 statt des Ruhewerts. Beim R2-Trigger
    # (Ruhewert -1) wäre 0 die Mitte des Wertebereichs -> der Roboter würde
    # im Moment des Einsteckens mit halbem Speed losfahren.
    _WARMUP_POLLS = 2

    def __init__(self, param_bridge, parent=None) -> None:
        super().__init__(parent)
        self._param_bridge = param_bridge
        self._connected = False
        self._name = ""
        self._joystick = None
        self._values: list[float] = [0.0] * 5
        self._stick_x = 0.0
        self._stick_y = 0.0
        self._warmup = 0
        self._available = False

        self._map = _load_mapping()
        self._deadzone = float(self._map["deadzone"])

        # UI-Benachrichtigung entkoppeln: der Store wird mit 100 Hz gefüttert,
        # aber QML muss nicht 100x/s alle daran hängenden Bindings neu
        # auswerten (die Anzeige läuft ohnehin mit max. 60 fps). Jedes
        # valuesChanged-Signal kostet im GUI-Thread Zeit, die dann dem
        # 10-ms-Sendetimer fehlt — genau der Effekt, der die Steuerung
        # zusätzlich träge gemacht hat.
        self._last_ui_notify = 0.0
        self._ui_notify_interval = CONTROLLER_UI_NOTIFY_MS / 1000.0

        self._last_debug_dump = 0.0

        # Hot-Plug-Erkennung braucht keine 100 Hz. get_count() geht in SDL
        # ueber die Geraeteliste; einmal je halbe Sekunde reicht voellig und
        # spart 98 % der Aufrufe im Regeltakt.
        self._init_done = False
        self._last_count_check = 0.0
        self._count_cache = 0

        if pygame is None:
            log.warning(
                "pygame nicht verfuegbar (%s) — Controller-Unterstuetzung ist "
                "deaktiviert, die Fast-Params bleiben per Touch bedienbar. "
                "Installation: pip install pygame  (fuer Python 3.14 gibt es "
                "noch kein pygame-Wheel, dort stattdessen: pip install pygame-ce)",
                _PYGAME_IMPORT_ERROR,
            )

    def _ensure_init(self) -> bool:
        """pygame beim ERSTEN poll() aufsetzen — also im Sende-Thread.

        SDL verlangt, dass das Joystick-Subsystem aus demselben Thread
        gepumpt wird, in dem es initialisiert wurde. Wuerde das noch im
        Konstruktor (GUI-Thread) passieren, waere jedes spaetere
        get_axis() aus dem Sende-Thread ein Thread-Wechsel mitten in SDL.
        """
        if self._init_done:
            return self._available
        self._init_done = True
        if pygame is None:
            return False
        try:
            pygame.init()
            pygame.joystick.init()
            self._available = True
        except pygame.error as exc:
            log.error("pygame/SDL konnte nicht initialisiert werden: %s", exc)
        return self._available

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
    @safe_slot
    def poll(self) -> None:
        """Einen Abtastzyklus ausführen. Wird von ParamBridge unmittelbar vor
        dem Packen des Fast-Pakets aufgerufen (100 Hz, Sende-Thread)."""
        if not self._ensure_init():
            return

        # SDL legt bei jeder Achsenbewegung Events in eine Warteschlange. Wir
        # lesen den Zustand direkt über get_axis()/get_button() und brauchen
        # die Events nicht — ohne dieses clear() läuft die Queue mit rund
        # 1000 Events/s voll, die niemand abholt.
        # clear() pumpt intern selbst; ein zusätzliches event.pump() davor
        # wäre ein zweiter kompletter Durchlauf der Warteschlange pro Zyklus.
        try:
            pygame.event.clear()
        except pygame.error as exc:
            log.warning("pygame-Event-Verarbeitung fehlgeschlagen: %s", exc)
            return

        # Hot-Plug nur alle 500 ms prüfen (siehe __init__). Solange ein
        # Controller verbunden ist, meldet ein Lesefehler das Abziehen
        # ohnehin sofort.
        now = time.monotonic()
        if self._joystick is None or (now - self._last_count_check) >= 0.5:
            self._last_count_check = now
            try:
                self._count_cache = pygame.joystick.get_count()
            except pygame.error as exc:
                log.warning("Controller-Abfrage fehlgeschlagen: %s", exc)
                return
        count = self._count_cache

        if count == 0:
            if self._connected:
                self._set_disconnected()
            return

        if self._joystick is None:
            try:
                self._joystick = pygame.joystick.Joystick(0)
                self._joystick.init()
                self._name = self._joystick.get_name()
                self._connected = True
                self._warmup = self._WARMUP_POLLS
                log.info("Controller verbunden: '%s' — Touch-Eingabe gesperrt.", self._name)
                self.connectedChanged.emit()
            except pygame.error as exc:
                log.warning("Controller-Initialisierung fehlgeschlagen: %s", exc)
                return

        try:
            self._read_and_apply()
        except pygame.error as exc:
            log.warning("Controller-Lesefehler (vermutlich getrennt): %s", exc)
            self._set_disconnected()

    def _set_disconnected(self) -> None:
        self._connected = False
        self._joystick = None
        self._count_cache = 0
        self._last_count_check = 0.0   # beim naechsten poll() sofort neu pruefen
        self._name = ""
        self._warmup = 0
        # Beim Trennen bewusst auf 0 zurückfallen statt den letzten Stand
        # stehen zu lassen — ein weggerissenes USB-Kabel darf den Roboter
        # nicht mit dem letzten Gasstand weiterfahren lassen.
        self._values = [0.0] * 5
        self._stick_x = 0.0
        self._stick_y = 0.0
        self._param_bridge.apply_controller_values(self._values)
        log.info("Controller getrennt — Touch-Eingabe wieder aktiv, Fast-Werte auf 0.")
        self.connectedChanged.emit()
        self.valuesChanged.emit()

    def _read_and_apply(self) -> None:
        js = self._joystick
        num_axes = js.get_numaxes()
        num_buttons = js.get_numbuttons()
        m = self._map

        def axis(idx: int, default: float = 0.0) -> float:
            return js.get_axis(idx) if 0 <= idx < num_axes else default

        def button(idx: int) -> int:
            return js.get_button(idx) if 0 <= idx < num_buttons else 0

        if log.isEnabledFor(logging.DEBUG):
            now = time.monotonic()
            if now - self._last_debug_dump >= 1.0:
                self._last_debug_dump = now
                log.debug(
                    "Rohwerte '%s': Achsen=%s Buttons=%s",
                    self._name,
                    [round(js.get_axis(i), 3) for i in range(num_axes)],
                    [js.get_button(i) for i in range(num_buttons)],
                )

        if self._warmup > 0:
            # Ruhewerte noch nicht gültig (siehe _WARMUP_POLLS)
            self._warmup -= 1
            return

        raw_x = _apply_deadzone(axis(m["axis_left_x"]), self._deadzone)
        raw_y = _apply_deadzone(axis(m["axis_left_y"]), self._deadzone)
        raw_rot = _apply_deadzone(axis(m["axis_right_x"]), self._deadzone)
        # Auf -1..1 begrenzen: scale_unipolar bildet diesen Bereich direkt auf
        # min..max ab, ein Ausreisser wuerde also einen Sollwert ausserhalb der
        # in param_config.json konfigurierten Grenzen an den Roboter schicken.
        raw_r2 = max(-1.0, min(1.0, axis(m["axis_r2"], -1.0)))
        r1_held = button(m["button_r1"])
        l1_held = button(m["button_l1"])

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

        values = [joystick_x, joystick_y, rotation, speed, dribbler]
        changed = values != self._values

        self._values = values
        self._stick_x = raw_x
        self._stick_y = raw_y

        # Der Store wird IMMER mit voller Rate gefüttert — nur die
        # QML-Benachrichtigung wird gedrosselt (siehe __init__).
        self._param_bridge.apply_controller_values(values)

        if changed:
            now = time.monotonic()
            if now - self._last_ui_notify >= self._ui_notify_interval:
                self._last_ui_notify = now
                self.valuesChanged.emit()

    def shutdown(self) -> None:
        if not self._available:
            return
        try:
            pygame.joystick.quit()
            pygame.quit()
        except pygame.error:
            pass
        self._available = False
