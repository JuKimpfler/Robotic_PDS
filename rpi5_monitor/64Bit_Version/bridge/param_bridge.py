"""
bridge/param_bridge.py — Tab 4 (Parameter/Joystick-Downlink)
=================================================================
Haelt den Soll-Zustand aller Parameter, packt ihn in die beiden Wire-Formate
(Slow 2 Hz / Fast 100 Hz) und schickt ihn an den aktiven Node.

────────────────────────────────────────────────────────────────────────────
WARUM DER 100-HZ-TAKT IN EINEM EIGENEN THREAD LAEUFT
────────────────────────────────────────────────────────────────────────────
Bis hierher lief alles im Qt-GUI-Thread: der 10-ms-Sendetimer, das Auslesen
des PS4-Controllers, das Verarbeiten der eingehenden Telemetrie (20 Hz, bis
zu 200 Kanaele), das Neuzeichnen des Plotters UND das Rendern der Oberflaeche.

Ein QTimer feuert aber erst, wenn die Ereignisschleife wieder drankommt.
Jedes Neuzeichnen des Plotters, jeder Tabwechsel, jede Neuberechnung der
Parametertabelle hat den 10-ms-Takt deshalb verschoben — und zwar
unregelmaessig. Genau das ist der Effekt "die Joystick-Abfrage stockt": nicht
der Controller ist langsam, sondern sein Abtastzeitpunkt wandert, weil er
sich einen Thread mit dem Renderer teilt.

Jetzt laeuft die komplette Regelstrecke — Controller lesen, Tastatur
auswerten, Paket packen, senden — in einem eigenen Thread mit fester
Periode. Der GUI-Thread fasst sie nicht mehr an; er liest nur noch Zaehler
fuer die Anzeige. Der Zugriff auf den gemeinsamen Wertespeicher ist mit
einem Lock geschuetzt, das ausserhalb des sendto() gehalten wird — ein
blockierender Socket duerfte den GUI-Thread nie warten lassen.

pygame/SDL wird bewusst IM Worker-Thread initialisiert: das Joystick-
Subsystem muss aus demselben Thread gepumpt werden, aus dem es aufgesetzt
wurde.

────────────────────────────────────────────────────────────────────────────
WOHER DIE KONFIGURATION KOMMT
────────────────────────────────────────────────────────────────────────────
Vorrang hat die vom Teensy gemeldete und lokal gespeicherte Fassung
(runtime_config/nodeN/param_config.json). Erst wenn es die nicht gibt, gilt
param_config.json aus dem Repository als Vorlage. Siehe runtime_config.py.
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from time import monotonic as _monotonic
from typing import Callable

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtProperty, pyqtSlot

import runtime_config
from config import (
    PARAM_SLOW_MAGIC, PARAM_FAST_MAGIC,
    UDP_PARAM_SLOW_PORT_NODE1, UDP_PARAM_SLOW_PORT_NODE2,
    UDP_PARAM_FAST_PORT_NODE1, UDP_PARAM_FAST_PORT_NODE2,
    PARAM_SLOW_SEND_INTERVAL_MS, PARAM_FAST_SEND_INTERVAL_MS,
    PARAM_SLOW_SEND_HZ, PARAM_FAST_SEND_HZ,
    PARAM_CONFIG_PATH, PARAM_DEFAULTS_H_PATH,
    DISCOVERY_MAGIC, DISCOVERY_STRUCT, DISCOVERY_SEND_INTERVAL_MS,
    DISCOVERY_ECHO_MAGIC, DISCOVERY_ECHO_PACKET_BYTES, DISCOVERY_ECHO_STRUCT,
    UDP_DISCOVERY_PORT_NODE1, UDP_DISCOVERY_PORT_NODE2,
)
from param_io import (
    ParamConfig, ParamEntry, JoystickEntry,
    load_param_config, write_param_defaults_h, read_param_defaults_h,
)
from bridge.controller_bridge import ControllerBridge
from bridge.utils import safe_slot

log = logging.getLogger("bridge.param")

_ECHO_MAGIC_BYTES = struct.pack("<I", DISCOVERY_ECHO_MAGIC)

# Zwei Aenderungen desselben Reglers innerhalb dieser Zeit gelten als EIN
# Schritt fuer "Rueckgaengig". Ohne das erzeugt ein einziges Ziehen an einem
# Schieberegler dutzende Undo-Schritte.
_UNDO_COALESCE_S = 1.5
_UNDO_DEPTH = 50

# Ab dieser Abweichung gilt ein Float als "weicht ab" (Anzeige B5/B6).
_DIFF_EPS = 1e-4


# ══════════════════════════════════════════════════════════════════════════
#  ParamStore — Soll-Zustand + Wire-Format
# ══════════════════════════════════════════════════════════════════════════

class ParamStore:
    """Haelt den aktuellen Soll-Zustand aller Parameter und packt sie in die
    beiden Wire-Formate (Slow/Fast).

    Thread-sicher: geschrieben wird sowohl aus dem GUI-Thread (Touch) als
    auch aus dem Sende-Thread (Controller/Tastatur), gelesen beim Packen.
    Das Lock ist unstrittig billig (unkontendiert ~50 ns) und wird nie
    ueber einen sendto()-Aufruf gehalten.
    """

    def __init__(self, config: ParamConfig) -> None:
        self.lock = threading.Lock()
        self.floats = np.array([e.default for e in config.floats], dtype=np.float32)
        self.bools = np.array([e.default for e in config.bools], dtype=bool)
        self.fast_floats = np.array([e.default for e in config.fast_floats], dtype=np.float32)
        self._slow_seq = 0
        self._fast_seq = 0

    def set_float(self, i: int, v: float) -> None:
        with self.lock:
            self.floats[i] = v

    def set_bool(self, i: int, v: bool) -> None:
        with self.lock:
            self.bools[i] = v

    def set_fast_float(self, i: int, v: float) -> None:
        with self.lock:
            self.fast_floats[i] = v

    def set_fast_block(self, values) -> None:
        """Mehrere Fast-Werte in EINEM Lock-Durchgang (Controller/Tastatur)."""
        with self.lock:
            n = min(len(values), len(self.fast_floats))
            if n:
                self.fast_floats[:n] = values[:n]

    def pack_slow(self) -> bytes:
        with self.lock:
            self._slow_seq = (self._slow_seq + 1) & 0xFFFFFFFF
            header = struct.pack("<II", PARAM_SLOW_MAGIC, self._slow_seq)
            return (
                header
                + self.floats.astype("<f4").tobytes()
                # astype(uint8) liefert garantiert 0/1 je Element und ersetzt
                # den frueheren Python-Generator ueber alle 50 Bools pro Paket.
                + self.bools.astype(np.uint8).tobytes()
            )

    def pack_fast(self) -> bytes:
        with self.lock:
            self._fast_seq = (self._fast_seq + 1) & 0xFFFFFFFF
            header = struct.pack("<II", PARAM_FAST_MAGIC, self._fast_seq)
            return header + self.fast_floats.astype("<f4").tobytes()

    def snapshot(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        with self.lock:
            return self.floats.copy(), self.bools.copy(), self.fast_floats.copy()

    def apply_defaults_h(self, defaults: dict) -> bool:
        applied = False
        with self.lock:
            if defaults.get("floats") and len(defaults["floats"]) == len(self.floats):
                self.floats[:] = defaults["floats"]
                applied = True
            if defaults.get("bools") and len(defaults["bools"]) == len(self.bools):
                self.bools[:] = defaults["bools"]
                applied = True
            ff = defaults.get("fast_floats")
            if ff and len(ff) == len(self.fast_floats):
                self.fast_floats[:] = ff
                applied = True
        return applied


# ══════════════════════════════════════════════════════════════════════════
#  Tastatursteuerung (B4)
# ══════════════════════════════════════════════════════════════════════════

class KeyboardControl:
    """Normierte Achswerte aus WASD/QE, gesetzt von Main.qml.

    Bewusst nur ein Wertespeicher ohne eigene Zeitsteuerung: das Abtasten
    macht der Sende-Thread, damit Tastatur, Controller und Touch alle
    denselben 100-Hz-Takt bedienen.
    """

    __slots__ = ("x", "y", "rot", "speed", "dribbler", "active", "release_pending")

    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.rot = 0.0
        self.speed = 0.0
        self.dribbler = 0.0
        self.active = False
        # Beim Loslassen muss noch genau EIN Nullpaket gesendet werden —
        # sonst bliebe der letzte Stand stehen und der Roboter fuehre weiter.
        self.release_pending = False

    def set(self, x: float, y: float, rot: float, speed: float, dribbler: float) -> None:
        self.x, self.y, self.rot = x, y, rot
        self.speed, self.dribbler = speed, dribbler
        was_active = self.active
        self.active = any(abs(v) > 1e-6 for v in (x, y, rot, speed, dribbler))
        if was_active and not self.active:
            self.release_pending = True


# ══════════════════════════════════════════════════════════════════════════
#  Konfiguration -> QML-taugliche verschachtelte Struktur
# ══════════════════════════════════════════════════════════════════════════

def _entry_to_dict(e: ParamEntry, kind: str, current=None) -> dict:
    """current: falls gesetzt, wird der LIVE-Wert aus dem ParamStore statt des
    statischen JSON-Defaults als 'default' an QML gereicht -- sonst wuerde ein
    Neuaufbau der Gruppen (Repeater-Model-Austausch) jeden bereits vom Nutzer
    veraenderten Regler optisch auf seinen Ursprungswert zuruecksetzen.

    kind ("fast"/"slow"/"bool") haengt an JEDEM Eintrag, nicht nur an der
    Gruppe: damit kann QML eine gruppenuebergreifende Suchergebnisliste bauen
    und trotzdem wissen, wohin der Wert gehoert (siehe Suchfeld in
    ParamsView.qml)."""
    return {
        "index": e.index, "name": e.name, "widget": e.widget, "kind": kind,
        "default": current if current is not None else e.default,
        "min": e.min, "max": e.max,
        "step": e.step, "momentary": e.momentary,
        "group": e.group,
    }


def _joystick_to_dict(js: JoystickEntry) -> dict:
    return {
        "name": js.name, "source": js.source,
        "xIndex": js.x_index, "yIndex": js.y_index,
        "xRange": list(js.x_range), "yRange": list(js.y_range),
        "returnToCenter": js.return_to_center,
    }


def _build_groups(config: ParamConfig, store: "ParamStore | None" = None) -> list[dict]:
    """Baut die Seiten-Struktur: 1) Fast Params, 2) Slow-Joysticks,
    3) je 'group'-Feld eine Seite.

    store: nur bei einem Namens-/Konfigurations-Refresh gesetzt, damit die neu
    aufgebauten Gruppen die aktuellen Live-Werte statt der JSON-Defaults als
    Anzeige-Startwert bekommen (siehe _entry_to_dict)."""
    from collections import OrderedDict

    pages: list[dict] = []
    floats_v, bools_v, fast_v = store.snapshot() if store is not None else (None, None, None)

    def _cur(arr, idx):
        if arr is None or idx >= len(arr):
            return None
        return float(arr[idx]) if arr.dtype != bool else bool(arr[idx])

    fast_joy_idx = {
        i for js in config.joysticks if js.source == "fast"
        for i in (js.x_index, js.y_index)
    }
    pages.append({
        "kind": "fast",
        "title": "Fast Params - 100 Hz",
        "floats": [
            _entry_to_dict(e, "fast", _cur(fast_v, e.index))
            for e in config.fast_floats if e.index not in fast_joy_idx
        ],
        "joysticks": [_joystick_to_dict(js) for js in config.joysticks if js.source == "fast"],
        "bools": [],
    })

    slow_joysticks = [js for js in config.joysticks if js.source == "slow"]
    slow_joy_idx = {i for js in slow_joysticks for i in (js.x_index, js.y_index)}
    if slow_joysticks:
        pages.append({
            "kind": "joysticks",
            "title": "Joysticks - 2 Hz",
            "floats": [], "bools": [],
            "joysticks": [_joystick_to_dict(js) for js in slow_joysticks],
        })

    combined: "OrderedDict[str, dict]" = OrderedDict()
    for e in config.floats:
        if e.index in slow_joy_idx:
            continue
        grp = e.group or "Allgemein"
        combined.setdefault(grp, {"floats": [], "bools": []})["floats"].append(e)
    for e in config.bools:
        grp = e.group or "Schalter"
        combined.setdefault(grp, {"floats": [], "bools": []})["bools"].append(e)

    for grp_name, parts in combined.items():
        pages.append({
            "kind": "group",
            "title": grp_name,
            "floats": [_entry_to_dict(e, "slow", _cur(floats_v, e.index))
                       for e in parts["floats"]],
            "bools": [_entry_to_dict(e, "bool", _cur(bools_v, e.index))
                      for e in parts["bools"]],
            "joysticks": [],
        })

    return pages


# ══════════════════════════════════════════════════════════════════════════
#  Sende-Thread
# ══════════════════════════════════════════════════════════════════════════

class FastControlWorker(threading.Thread):
    """Die komplette Regelstrecke in einem Thread: Controller lesen, Tastatur
    anwenden, Fast-Paket (100 Hz), Slow-Paket (2 Hz) und Discovery (1 Hz)
    senden.

    Siehe Modul-Docstring — die Trennung vom GUI-Thread ist der eigentliche
    Zweck dieser Klasse.
    """

    def __init__(self, bridge: "ParamBridge") -> None:
        super().__init__(name="PDS-FastControl", daemon=True)
        self._b = bridge
        self._stop = threading.Event()
        self.loop_count = 0
        self.late_count = 0        # Zyklen, die mehr als eine halbe Periode spaet waren
        self.max_late_ms = 0.0

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        b = self._b
        period = PARAM_FAST_SEND_INTERVAL_MS / 1000.0
        slow_period = PARAM_SLOW_SEND_INTERVAL_MS / 1000.0
        disc_period = DISCOVERY_SEND_INTERVAL_MS / 1000.0

        next_tick = time.perf_counter()
        next_slow = next_tick
        next_disc = next_tick

        try:
            self._loop(b, period, slow_period, disc_period,
                        next_tick, next_slow, next_disc)
        finally:
            # pygame/SDL in DEMSELBEN Thread schliessen, in dem es aufgesetzt
            # wurde (siehe ControllerBridge._ensure_init) — auch dann, wenn
            # die Schleife durch eine Ausnahme verlassen wird.
            try:
                b._controller.shutdown()
            except Exception:                       # noqa: BLE001
                log.debug("Controller-Abbau im Sende-Thread fehlgeschlagen.",
                           exc_info=True)

    def _loop(self, b, period, slow_period, disc_period,
               next_tick, next_slow, next_disc) -> None:
        while not self._stop.is_set():
            now = time.perf_counter()
            late = now - next_tick
            if late > period:
                # Deutlich hinterher (Systemlast, Standby): neu ausrichten,
                # statt die verpassten Zyklen nachzuholen — bei einer
                # Fernsteuerung zaehlt nur der AKTUELLE Stand.
                next_tick = now
                if late > period * 5:
                    self.late_count += 1
                    self.max_late_ms = max(self.max_late_ms, late * 1000.0)
            next_tick += period

            send_slow = now >= next_slow
            if send_slow:
                next_slow = now + slow_period
            send_disc = now >= next_disc
            if send_disc:
                next_disc = now + disc_period

            try:
                b._worker_tick(send_slow, send_disc)
            except Exception:                       # noqa: BLE001
                # Ein Fehler hier darf die Fernsteuerung nicht dauerhaft
                # stilllegen — melden und im naechsten Zyklus weitermachen.
                log.exception("Fehler im Sende-Thread — Zyklus uebersprungen.")

            self.loop_count += 1

            sleep_for = next_tick - time.perf_counter()
            if sleep_for > 0:
                # Seit Python 3.11 nutzt time.sleep() auch unter Windows einen
                # hochaufloesenden Timer; darunter waere die Granularitaet
                # ~15 ms und dieser Takt nicht zu halten.
                time.sleep(sleep_for)


# ══════════════════════════════════════════════════════════════════════════
#  ParamBridge
# ══════════════════════════════════════════════════════════════════════════

class ParamBridge(QObject):
    groupsChanged  = pyqtSignal()
    statusChanged  = pyqtSignal()
    errorChanged   = pyqtSignal()
    enabledChanged = pyqtSignal()
    savedChanged   = pyqtSignal()
    diffChanged    = pyqtSignal()
    undoChanged    = pyqtSignal()
    ackChanged     = pyqtSignal()
    keyboardChanged = pyqtSignal()

    def __init__(self, get_node_ip: Callable[[int], str], parent=None) -> None:
        super().__init__(parent)
        self._get_node_ip = get_node_ip
        self._active_node = 1
        self._enabled = True
        self._pkt_sent_slow = 0
        self._pkt_sent_fast = 0
        self._send_drops = 0
        self._last_send_error_log = 0.0
        self._error: str | None = None
        self._defaults_loaded = False
        self._status = ""
        self._groups: list[dict] = []
        self._config_path = PARAM_CONFIG_PATH
        # Fuer die 2-Hz-Anzeigeaktualisierung: nur melden, wenn sich etwas
        # geaendert hat. Jedes Signal laesst QML die komplette Liste neu
        # auswerten, und der Controller schreibt 100x/s in dieselben Werte.
        self._last_diff_count = -1
        self._ack_was_available = False

        # ── Rueckgaengig (F6) ────────────────────────────────────────────
        self._undo: list[tuple[str, int, object, object, str, float]] = []

        # ── Parameter-Rueckmeldung des Teensy (B6) ───────────────────────
        self._ack: dict | None = None
        self._ack_time = 0.0
        self._ack_node = 0

        # ── Tastatursteuerung (B4) ───────────────────────────────────────
        self._kb = KeyboardControl()
        self._kb_enabled = True

        # ── Discovery/Ping (C1) ──────────────────────────────────────────
        self._disc_seq = 0
        self._rtt_ms: dict[int, float] = {}
        self._rtt_time: dict[int, float] = {}

        self._load_config(self._config_path)
        self._store = ParamStore(self._config)

        # PS4-Controller. Wird NICHT von einem eigenen Timer getrieben,
        # sondern aus dem Sende-Thread heraus gepollt (siehe Modul-Docstring).
        self._controller = ControllerBridge(self, self)

        if self._error is None:
            defaults = read_param_defaults_h(PARAM_DEFAULTS_H_PATH)
            if defaults:
                self._defaults_loaded = self._store.apply_defaults_h(defaults)
            self._saved_defaults = defaults or {}
            self._groups = _build_groups(self._config)
        else:
            self._saved_defaults = {}

        # ── Socket ────────────────────────────────────────────────────────
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Nicht-blockierend: ein UDP-sendto() kann auf einem WLAN-Interface
        # blockieren, sobald die Sendewarteschlange des Treibers voll ist
        # (ENOBUFS). Lieber ein einzelnes Paket verwerfen (der naechste Stand
        # kommt in 10 ms) als den Sendetakt anzuhalten.
        self._sock.setblocking(False)

        # ── Sende-Thread ──────────────────────────────────────────────────
        #  VOR dem ersten _refresh_status(): die Statuszeile meldet auch die
        #  Zahl der zu spaet gekommenen Zyklen und liest dafuer self._worker.
        self._worker = FastControlWorker(self)
        self._worker.start()
        self._refresh_status()

        # Der GUI-Thread aktualisiert nur noch die Anzeige.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()

    # ── Konfiguration laden ───────────────────────────────────────────────
    def _load_config(self, path) -> None:
        self._fast_ranges: dict[int, tuple[float, float]] | None = None
        try:
            self._config = load_param_config(path)
            self._error = None
            self._config_path = path
        except ValueError as exc:
            log.error("%s ungueltig: %s", getattr(path, "name", path), exc)
            self._error = str(exc)
            self._config = ParamConfig(floats=[], bools=[], fast_floats=[], joysticks=[])

    def reload_for_node(self, node_id: int) -> bool:
        """Auf die (ggf. vom Teensy gelieferte) Konfiguration dieses Nodes
        umschalten. Gibt True zurueck, wenn tatsaechlich neu geladen wurde."""
        path = runtime_config.param_config_path_for(node_id, PARAM_CONFIG_PATH)
        if path == self._config_path:
            return False
        old_values = self._store.snapshot() if self._error is None else None
        self._load_config(path)
        self._store = ParamStore(self._config)
        if old_values is not None:
            # Werte, soweit die Laengen passen, uebernehmen — ein Node-Wechsel
            # soll nicht alle Regler auf die JSON-Defaults zuruecksetzen.
            floats, bools, fast = old_values
            with self._store.lock:
                n = min(len(floats), len(self._store.floats))
                self._store.floats[:n] = floats[:n]
                n = min(len(bools), len(self._store.bools))
                self._store.bools[:n] = bools[:n]
                n = min(len(fast), len(self._store.fast_floats))
                self._store.fast_floats[:n] = fast[:n]
        self._groups = _build_groups(self._config, self._store)
        self.groupsChanged.emit()
        self.errorChanged.emit()
        log.info("Parameter-Konfiguration von %s geladen (Node %d).", path, node_id)
        return True

    # ══════════════════════════════════════════════════════════════════════
    #  Sende-Thread: der eigentliche Takt
    # ══════════════════════════════════════════════════════════════════════

    def _worker_tick(self, send_slow: bool, send_disc: bool) -> None:
        """Wird 100x/s aus FastControlWorker aufgerufen. Laeuft NICHT im
        GUI-Thread."""
        # Controller zuerst: der gepackte Stand soll der zuletzt gelesene sein.
        self._controller.poll()

        if not self._controller.connected and self._kb_enabled:
            self._apply_keyboard()

        if self._error is None and self._enabled:
            ip, port = self._current_target(fast=True)
            self._sendto(self._store.pack_fast(), ip, port, fast=True)

            if send_slow:
                ip, port = self._current_target(fast=False)
                self._sendto(self._store.pack_slow(), ip, port, fast=False)

        if send_disc:
            self._send_discovery()

        # Antworten auf das Discovery-Paket abholen (Round-Trip-Messung).
        self._drain_echo()

    def _apply_keyboard(self) -> None:
        kb = self._kb
        if not kb.active and not kb.release_pending:
            return
        ranges = self.fast_float_ranges()

        def bipolar(idx: int, norm: float) -> float:
            lo, hi = ranges.get(idx, (-100.0, 100.0))
            return norm * (hi if norm >= 0 else -lo)

        def unipolar(idx: int, norm: float) -> float:
            lo, hi = ranges.get(idx, (0.0, 100.0))
            return lo + max(0.0, min(1.0, norm)) * (hi - lo)

        if kb.release_pending:
            kb.release_pending = False
            self._store.set_fast_block([0.0] * 5)
            return

        self._store.set_fast_block([
            bipolar(0, kb.x),
            bipolar(1, kb.y),
            bipolar(2, kb.rot),
            unipolar(3, kb.speed),
            bipolar(4, kb.dribbler),
        ])

    # ══════════════════════════════════════════════════════════════════════
    #  Properties
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(str, notify=errorChanged)
    def configError(self):
        return self._error or ""

    @pyqtProperty(str, notify=groupsChanged)
    def configSource(self):
        """Woher die aktuelle Parameter-Konfiguration stammt (Anzeige im
        Einstellungs-Tab)."""
        try:
            if self._config_path == PARAM_CONFIG_PATH:
                return f"Vorlage: {PARAM_CONFIG_PATH.name}"
            return f"vom Teensy: {self._config_path}"
        except Exception:                            # noqa: BLE001
            return str(self._config_path)

    @pyqtProperty("QVariantList", notify=groupsChanged)
    def groups(self):
        return self._groups

    @pyqtProperty(str, notify=statusChanged)
    def statusText(self):
        return self._status

    @pyqtProperty(bool, notify=enabledChanged)
    def enabled(self):
        return self._enabled

    @pyqtProperty(bool, notify=savedChanged)
    def defaultsLoadedFromFile(self):
        return self._defaults_loaded

    @pyqtProperty(QObject, constant=True)
    def controller(self):
        """ControllerBridge-Instanz für QML (params.controller.connected, ...)."""
        return self._controller

    @pyqtProperty(bool, notify=keyboardChanged)
    def keyboardEnabled(self):
        return self._kb_enabled

    @pyqtProperty(bool, notify=keyboardChanged)
    def keyboardActive(self):
        return self._kb.active

    # ── Abweichungen (B5) ─────────────────────────────────────────────────
    @pyqtProperty("QVariantList", notify=diffChanged)
    def diffEntries(self):
        """Was weicht vom gespeicherten Default (param_defaults.h) ab?"""
        if self._error is not None or not self._saved_defaults:
            return []
        floats, bools, fast = self._store.snapshot()
        out: list[dict] = []

        def add(entries, values, saved, kind):
            if not saved:
                return
            for e in entries:
                if e.index >= len(values) or e.index >= len(saved):
                    continue
                cur = values[e.index]
                ref = saved[e.index]
                if kind == "bool":
                    if bool(cur) == bool(ref):
                        continue
                    cur_s, ref_s = ("an" if cur else "aus"), ("an" if ref else "aus")
                elif abs(float(cur) - float(ref)) <= _DIFF_EPS:
                    continue
                else:
                    cur_s, ref_s = f"{float(cur):.4g}", f"{float(ref):.4g}"
                out.append({"kind": kind, "index": e.index, "name": e.name,
                            "current": cur_s, "reference": ref_s})

        add(self._config.floats, floats, self._saved_defaults.get("floats"), "slow")
        add(self._config.bools, bools, self._saved_defaults.get("bools"), "bool")
        add(self._config.fast_floats, fast, self._saved_defaults.get("fast_floats"), "fast")
        return out

    @pyqtProperty(int, notify=diffChanged)
    def diffCount(self):
        return len(self.diffEntries)

    # ── Rueckmeldung des Teensy (B6) ──────────────────────────────────────
    @pyqtProperty(bool, notify=ackChanged)
    def ackAvailable(self):
        return self._ack is not None and (_monotonic() - self._ack_time) < 5.0

    @pyqtProperty(str, notify=ackChanged)
    def ackText(self):
        if not self.ackAvailable:
            return "Teensy meldet keine Parameter zurück"
        n = len(self.ackMismatches)
        if n == 0:
            return "Teensy bestätigt alle Parameter"
        return f"{n} Parameter weichen im Teensy ab"

    @pyqtProperty("QVariantList", notify=ackChanged)
    def ackMismatches(self):
        """Soll (GUI) gegen Ist (Teensy). Genau dafuer gibt es den Rueckkanal:
        vorher war der Downlink fire-and-forget und niemand hat gemerkt, wenn
        ein Wert gar nicht angekommen ist."""
        if not self.ackAvailable or self._error is not None:
            return []
        ack = self._ack
        floats, bools, fast = self._store.snapshot()
        out: list[dict] = []

        def cmp_num(entries, values, remote, kind):
            for e in entries:
                if e.index >= len(values) or e.index >= len(remote):
                    continue
                a, b = float(values[e.index]), float(remote[e.index])
                if abs(a - b) <= _DIFF_EPS:
                    continue
                out.append({"kind": kind, "index": e.index, "name": e.name,
                            "current": f"{a:.4g}", "reference": f"{b:.4g}"})

        cmp_num(self._config.floats, floats, ack["floats"], "slow")
        cmp_num(self._config.fast_floats, fast, ack["fast_floats"], "fast")
        for e in self._config.bools:
            if e.index >= len(bools) or e.index >= len(ack["bools"]):
                continue
            if bool(bools[e.index]) == bool(ack["bools"][e.index]):
                continue
            out.append({"kind": "bool", "index": e.index, "name": e.name,
                        "current": "an" if bools[e.index] else "aus",
                        "reference": "an" if ack["bools"][e.index] else "aus"})
        return out

    def apply_ack(self, node_id: int, data: dict) -> None:
        """Vom AppBridge aufgerufen, sobald ein Ack-Paket eintrifft."""
        if node_id != self._active_node:
            return
        self._ack = data
        self._ack_node = node_id
        self._ack_time = _monotonic()
        self.ackChanged.emit()

    # ── Rueckgaengig (F6) ─────────────────────────────────────────────────
    @pyqtProperty(bool, notify=undoChanged)
    def canUndo(self):
        return bool(self._undo)

    @pyqtProperty(str, notify=undoChanged)
    def undoLabel(self):
        if not self._undo:
            return ""
        return f"Rückgängig: {self._undo[-1][4]}"

    def _push_undo(self, kind: str, index: int, old, new, name: str) -> None:
        now = _monotonic()
        if self._undo:
            k, i, o, _n, lbl, t = self._undo[-1]
            if k == kind and i == index and (now - t) < _UNDO_COALESCE_S:
                # Selber Regler, kurz hintereinander -> zu einem Schritt
                # zusammenfassen; der ALTE Ausgangswert bleibt erhalten.
                self._undo[-1] = (k, i, o, new, lbl, now)
                return
        self._undo.append((kind, index, old, new, name, now))
        if len(self._undo) > _UNDO_DEPTH:
            del self._undo[0]
        self.undoChanged.emit()

    @pyqtSlot()
    def undo(self) -> None:
        if not self._undo:
            return
        kind, index, old, _new, _label, _t = self._undo.pop()
        if kind == "slow":
            self._store.set_float(index, float(old))
        elif kind == "bool":
            self._store.set_bool(index, bool(old))
        elif kind == "fast":
            self._store.set_fast_float(index, float(old))
        # Die Anzeige lebt in den QML-Delegates; nur ein Neuaufbau der
        # Gruppen bringt den zurueckgesetzten Wert dort wieder an.
        self._groups = _build_groups(self._config, self._store)
        self.groupsChanged.emit()
        self.undoChanged.emit()
        self.diffChanged.emit()

    @pyqtSlot()
    def resetToDefaults(self) -> None:
        """Alle Werte auf den gespeicherten Default zuruecksetzen."""
        if self._error is not None or not self._saved_defaults:
            return
        self._store.apply_defaults_h(self._saved_defaults)
        self._undo.clear()
        self._groups = _build_groups(self._config, self._store)
        self.groupsChanged.emit()
        self.undoChanged.emit()
        self.diffChanged.emit()

    # ── Fuer ControllerBridge ─────────────────────────────────────────────
    def fast_float_ranges(self) -> dict[int, tuple[float, float]]:
        """index -> (min, max) aus der Konfiguration, damit Controller und
        Tastatur dieselben Grenzen respektieren wie die Touch-Slider.

        Gecacht: die Methode wird 100x/s aus dem Sende-Thread gerufen, und
        ein jedes Mal neu gebautes dict waere reine Arbeit fuer den
        Garbage Collector."""
        if self._fast_ranges is None:
            self._fast_ranges = {e.index: (e.min, e.max) for e in self._config.fast_floats}
        return self._fast_ranges

    def apply_controller_values(self, values: list[float]) -> None:
        """Aus ControllerBridge.poll() heraus aufgerufen (im Sende-Thread),
        unmittelbar bevor das Fast-Paket gepackt wird."""
        if self._error is not None:
            return
        self._store.set_fast_block(values)

    # ══════════════════════════════════════════════════════════════════════
    #  Slots: Werte-Aenderungen aus QML (GUI-Thread)
    # ══════════════════════════════════════════════════════════════════════

    @pyqtSlot(int, float)
    def setSlowFloat(self, index: int, value: float) -> None:
        if 0 <= index < len(self._store.floats):
            old = float(self._store.floats[index])
            if abs(old - value) > _DIFF_EPS:
                self._push_undo("slow", index, old, value, self._name_of("slow", index))
            self._store.set_float(index, value)

    @pyqtSlot(int, bool)
    def setSlowBool(self, index: int, value: bool) -> None:
        if 0 <= index < len(self._store.bools):
            old = bool(self._store.bools[index])
            if old != value:
                self._push_undo("bool", index, old, value, self._name_of("bool", index))
            self._store.set_bool(index, value)

    @pyqtSlot(int, float)
    def setFastFloat(self, index: int, value: float) -> None:
        # Fast-Werte kommen vom Joystick mit bis zu 100 Aenderungen/s —
        # bewusst KEIN Undo-Eintrag, das waere nur Rauschen im Verlauf.
        if 0 <= index < len(self._store.fast_floats):
            self._store.set_fast_float(index, value)

    def _name_of(self, kind: str, index: int) -> str:
        table = {"slow": self._config.floats, "bool": self._config.bools,
                 "fast": self._config.fast_floats}.get(kind, [])
        for e in table:
            if e.index == index:
                return e.name
        return f"{kind} {index}"

    @pyqtSlot(bool)
    def setEnabled(self, value: bool) -> None:
        self._enabled = value
        self.enabledChanged.emit()
        self._refresh_status()

    @pyqtSlot(bool)
    def setKeyboardEnabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._kb_enabled:
            return
        self._kb_enabled = value
        if not value:
            self._kb.set(0.0, 0.0, 0.0, 0.0, 0.0)
            self._kb.release_pending = True
        self.keyboardChanged.emit()

    @pyqtSlot(float, float, float, float, float)
    def setKeyboardAxes(self, x: float, y: float, rot: float,
                         speed: float, dribbler: float) -> None:
        """Von Main.qml bei jeder Tastenaenderung aufgerufen (WASD/QE/Shift).
        Die Umrechnung auf die konfigurierten Wertebereiche und das Senden
        macht der Sende-Thread — hier wird nur der Zustand hinterlegt."""
        was = self._kb.active
        self._kb.set(x, y, rot, speed, dribbler)
        if was != self._kb.active:
            self.keyboardChanged.emit()

    @pyqtSlot()
    def stopAll(self) -> None:
        """Not-Aus: alle Fast-Werte sofort auf 0."""
        self._kb.set(0.0, 0.0, 0.0, 0.0, 0.0)
        self._store.set_fast_block([0.0] * len(self._store.fast_floats))
        self.keyboardChanged.emit()

    @pyqtSlot()
    def saveDefaults(self) -> None:
        try:
            floats, bools, fast = self._store.snapshot()
            write_param_defaults_h(PARAM_DEFAULTS_H_PATH, floats, bools, fast)
            self._saved_defaults = {
                "floats": [float(v) for v in floats],
                "bools": [bool(v) for v in bools],
                "fast_floats": [float(v) for v in fast],
            }
            self._status = f"Gespeichert: {PARAM_DEFAULTS_H_PATH.name}"
            self.statusChanged.emit()
            self.diffChanged.emit()
            log.info("Param-Defaults gespeichert nach %s", PARAM_DEFAULTS_H_PATH)
        except OSError as exc:
            log.error("Konnte param_defaults.h nicht schreiben: %s", exc)

    # ── Von AppBridge aufgerufen ──────────────────────────────────────────
    def set_active_node(self, node_id: int) -> None:
        self._active_node = node_id
        self._ack = None
        self.reload_for_node(node_id)
        self.ackChanged.emit()
        self._refresh_status()

    def rtt_ms(self, node_id: int) -> float | None:
        """Zuletzt gemessene Round-Trip-Zeit zum Node (None = unbekannt)."""
        t = self._rtt_time.get(node_id, 0.0)
        if t == 0.0 or (_monotonic() - t) > 5.0:
            return None
        return self._rtt_ms.get(node_id)

    def apply_names(
        self,
        slow_float_names: dict[int, str],
        slow_bool_names: dict[int, str],
        fast_float_names: dict[int, str],
    ) -> None:
        """Vom Teensy empfangene Anzeigenamen uebernehmen. Baut 'groups' neu
        auf, gibt dabei aber die aktuellen Live-Werte mit (siehe
        _build_groups) — sonst wuerde der Repeater-Neuaufbau in QML jeden
        bereits verstellten Regler auf seinen Ursprungswert zuruecksetzen."""
        if self._error is not None:
            return
        changed = False
        for e in self._config.floats:
            if e.index in slow_float_names and e.name != slow_float_names[e.index]:
                e.name = slow_float_names[e.index]
                changed = True
        for e in self._config.bools:
            if e.index in slow_bool_names and e.name != slow_bool_names[e.index]:
                e.name = slow_bool_names[e.index]
                changed = True
        for e in self._config.fast_floats:
            if e.index in fast_float_names and e.name != fast_float_names[e.index]:
                e.name = fast_float_names[e.index]
                changed = True
        if not changed:
            return
        self._groups = _build_groups(self._config, self._store)
        self.groupsChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Senden (im Sende-Thread)
    # ══════════════════════════════════════════════════════════════════════

    def _current_target(self, fast: bool) -> tuple[str, int]:
        ip = self._get_node_ip(self._active_node)
        if fast:
            port = UDP_PARAM_FAST_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_FAST_PORT_NODE2
        else:
            port = UDP_PARAM_SLOW_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_SLOW_PORT_NODE2
        return ip, port

    def _send_discovery(self) -> None:
        """1x/s an BEIDE Nodes, damit auch der gerade nicht ausgewaehlte Node
        die Adresse der GUI kennt und seine Telemetrie per Unicast statt per
        Broadcast schickt.

        Enthaelt bewusst KEINE Parameter — es kann also nie Werte in den
        falschen Roboter schreiben, und der Node leitet es nicht an den
        Teensy weiter. Die mitgeschickte Nummer und der Sendezeitpunkt
        kommen als Echo zurueck und ergeben die Round-Trip-Zeit.
        """
        self._disc_seq = (self._disc_seq + 1) & 0xFFFFFFFF
        t_ms = int(time.perf_counter() * 1000.0) & 0xFFFFFFFF
        payload = struct.pack(DISCOVERY_STRUCT, DISCOVERY_MAGIC, self._disc_seq, t_ms)
        for node_id, port in ((1, UDP_DISCOVERY_PORT_NODE1),
                               (2, UDP_DISCOVERY_PORT_NODE2)):
            ip = self._get_node_ip(node_id)
            try:
                self._sock.sendto(payload, (ip, port))
            except OSError:
                pass   # Node (noch) nicht erreichbar — naechster Versuch in 1 s

    def _drain_echo(self) -> None:
        """Antworten der Nodes auf das Discovery-Paket auswerten."""
        while True:
            try:
                data, _addr = self._sock.recvfrom(DISCOVERY_ECHO_PACKET_BYTES + 64)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                # Unter Windows meldet ein unerreichbarer Ziel-Port den Fehler
                # nachtraeglich auf recvfrom (WSAECONNRESET). Das ist kein
                # Grund, die Schleife zu beenden — aber auch nichts, worauf
                # man reagieren muesste.
                return
            if (len(data) != DISCOVERY_ECHO_PACKET_BYTES
                    or data[:4] != _ECHO_MAGIC_BYTES):
                continue
            _m, node_id, _seq, t_send = struct.unpack(DISCOVERY_ECHO_STRUCT, data)
            now_ms = int(time.perf_counter() * 1000.0) & 0xFFFFFFFF
            rtt = (now_ms - t_send) & 0xFFFFFFFF
            if rtt > 60000:
                continue          # unplausibel (Ueberlauf/uraltes Paket)
            if node_id in (1, 2):
                self._rtt_ms[node_id] = float(rtt)
                self._rtt_time[node_id] = _monotonic()

    def _sendto(self, payload: bytes, ip: str, port: int, fast: bool) -> None:
        try:
            self._sock.sendto(payload, (ip, port))
            if fast:
                self._pkt_sent_fast += 1
            else:
                self._pkt_sent_slow += 1
        except BlockingIOError:
            # Sendepuffer voll. Beim Fast-Kanal folgenlos: in 10 ms kommt der
            # naechste, aktuellere Stand. Nur zaehlen, nicht pro Paket loggen —
            # sonst flutet ein schlechter Funkkanal das Log mit 100 Zeilen/s.
            self._send_drops += 1
        except OSError as exc:
            self._send_drops += 1
            now = _monotonic()
            if now - self._last_send_error_log >= 2.0:
                self._last_send_error_log = now
                log.warning("Param-Sendefehler (%s-Kanal) an %s:%d: %s",
                            "Fast" if fast else "Slow", ip, port, exc)

    # ══════════════════════════════════════════════════════════════════════
    #  Anzeige (GUI-Thread)
    # ══════════════════════════════════════════════════════════════════════

    @safe_slot
    def _refresh_status(self) -> None:
        ip = self._get_node_ip(self._active_node)
        state = "aktiv" if self._enabled else "pausiert"
        if self._controller.connected:
            src = " - 🎮 Controller"
        elif self._kb_enabled and self._kb.active:
            src = " - ⌨ Tastatur"
        else:
            src = ""
        drops = f" - Verworfen: {self._send_drops}" if self._send_drops else ""
        late = f" - Takt spät: {self._worker.late_count}x" if self._worker.late_count else ""
        status = (
            f"{state} -> Node {self._active_node} ({ip}) - "
            f"Slow: {PARAM_SLOW_SEND_HZ:.1f} Hz ({self._pkt_sent_slow} Pkt) - "
            f"Fast: {PARAM_FAST_SEND_HZ:.0f} Hz ({self._pkt_sent_fast} Pkt)"
            f"{drops}{late}{src}"
        )
        # Nur bei echter Aenderung melden: sonst wertet QML das daran haengende
        # Text-Binding 2x/s neu aus, obwohl sich nichts geaendert hat.
        if status != self._status:
            self._status = status
            self.statusChanged.emit()

        n = len(self.diffEntries)
        if n != self._last_diff_count:
            self._last_diff_count = n
            self.diffChanged.emit()

        available = self.ackAvailable
        if available != self._ack_was_available:
            self._ack_was_available = available
            self.ackChanged.emit()

    # ── Aufraeumen (von AppBridge.shutdown aufgerufen) ────────────────────
    def shutdown(self) -> None:
        """Sende-Thread stoppen, Controller freigeben, Socket schliessen.

        Reihenfolge ist wichtig: erst den Thread beenden (er benutzt Socket
        und Controller), dann die Ressourcen abbauen. Ohne das lief der
        100-Hz-Takt beim Beenden weiter und schrieb auf einen bereits
        geschlossenen Socket.
        """
        timer = getattr(self, "_status_timer", None)
        if timer is not None:
            timer.stop()
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.stop()
            worker.join(timeout=1.0)
            if worker.is_alive():
                log.warning("Sende-Thread reagiert nicht — wird als Daemon beendet.")
        self._controller.shutdown()
        try:
            self._sock.close()
        except OSError:
            pass
