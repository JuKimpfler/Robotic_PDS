"""
bridge/param_bridge.py — Tab 4 (Parameter/Joystick-Downlink)
=================================================================
Wiederverwendung: param_io.py (Laden/Speichern) und die Slow/Fast-
UDP-Pack-Logik (ParamStore) sind reines Python ohne Qt-Widgets-Abhängigkeit
und werden 1:1 übernommen. Neu ist ausschließlich, WIE die Konfiguration
an die Oberfläche gereicht wird: statt in Python Widgets pro Eintrag zu
bauen (gui/tab_params.py, ~800 Zeilen Widget-Factories), wird die komplette
gruppierte Konfiguration einmalig als verschachtelte QVariant-Struktur an
QML übergeben — ParamsView.qml baut daraus deklarativ die UI per Repeater
+ Loader (siehe Abschnitt 4.6 im Migrationsplan).

Der aktuelle *Wert* jedes Reglers lebt bewusst NUR in QML (State im
Delegate) — das Teensy-Protokoll ist fire-and-forget ohne Rückkanal, es
gibt also nichts, das aus Python zurück in die Widgets gespiegelt werden
müsste (identisch zum Verhalten der alten Widgets-GUI).
"""
from __future__ import annotations

import logging
import socket
from typing import Callable

import numpy as np
from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtProperty, pyqtSlot

from config import (
    PARAM_SLOW_MAGIC, PARAM_FAST_MAGIC,
    UDP_PARAM_SLOW_PORT_NODE1, UDP_PARAM_SLOW_PORT_NODE2,
    UDP_PARAM_FAST_PORT_NODE1, UDP_PARAM_FAST_PORT_NODE2,
    PARAM_SLOW_SEND_INTERVAL_MS, PARAM_FAST_SEND_INTERVAL_MS,
    PARAM_SLOW_SEND_HZ, PARAM_FAST_SEND_HZ,
    PARAM_CONFIG_PATH, PARAM_DEFAULTS_H_PATH,
)
from param_io import (
    ParamConfig, ParamEntry, JoystickEntry,
    load_param_config, write_param_defaults_h, read_param_defaults_h,
)

log = logging.getLogger("bridge.param")


# ══════════════════════════════════════════════════════════════════════════
#  ParamStore — unverändert aus gui/tab_params.py übernommen
# ══════════════════════════════════════════════════════════════════════════

class ParamStore:
    """Hält den aktuellen Soll-Zustand aller Parameter und packt sie in
    die beiden Wire-Formate (Slow/Fast). Identisch zur bisherigen Klasse."""

    def __init__(self, config: ParamConfig) -> None:
        self.floats = np.array([e.default for e in config.floats], dtype=np.float32)
        self.bools = np.array([e.default for e in config.bools], dtype=bool)
        self.fast_floats = np.array([e.default for e in config.fast_floats], dtype=np.float32)
        self._slow_seq = 0
        self._fast_seq = 0

    def set_float(self, i: int, v: float) -> None:
        self.floats[i] = v

    def set_bool(self, i: int, v: bool) -> None:
        self.bools[i] = v

    def set_fast_float(self, i: int, v: float) -> None:
        self.fast_floats[i] = v

    def pack_slow(self) -> bytes:
        import struct
        self._slow_seq = (self._slow_seq + 1) & 0xFFFFFFFF
        header = struct.pack("<II", PARAM_SLOW_MAGIC, self._slow_seq)
        return (
            header
            + self.floats.astype("<f4").tobytes()
            + bytes(1 if b else 0 for b in self.bools)
        )

    def pack_fast(self) -> bytes:
        import struct
        self._fast_seq = (self._fast_seq + 1) & 0xFFFFFFFF
        header = struct.pack("<II", PARAM_FAST_MAGIC, self._fast_seq)
        return header + self.fast_floats.astype("<f4").tobytes()

    def apply_defaults_h(self, defaults: dict) -> bool:
        applied = False
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
#  Konfiguration → QML-taugliche verschachtelte Struktur
# ══════════════════════════════════════════════════════════════════════════

def _entry_to_dict(e: ParamEntry) -> dict:
    return {
        "index": e.index, "name": e.name, "widget": e.widget,
        "default": e.default, "min": e.min, "max": e.max,
        "step": e.step, "momentary": e.momentary,
    }


def _joystick_to_dict(js: JoystickEntry) -> dict:
    return {
        "name": js.name, "source": js.source,
        "xIndex": js.x_index, "yIndex": js.y_index,
        "xRange": list(js.x_range), "yRange": list(js.y_range),
        "returnToCenter": js.return_to_center,
    }


def _build_groups(config: ParamConfig) -> list[dict]:
    """Baut die Seiten-Struktur analog zu gui/tab_params.py::_build_group_pages:
    1) Fast Params, 2) Slow-Joysticks, 3) je 'group'-Feld eine Seite."""
    from collections import OrderedDict

    pages: list[dict] = []

    fast_joy_idx = {
        i for js in config.joysticks if js.source == "fast"
        for i in (js.x_index, js.y_index)
    }
    pages.append({
        "kind": "fast",
        "title": "Fast Params - 100 Hz",
        "floats": [_entry_to_dict(e) for e in config.fast_floats if e.index not in fast_joy_idx],
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
            "floats": [_entry_to_dict(e) for e in parts["floats"]],
            "bools": [_entry_to_dict(e) for e in parts["bools"]],
            "joysticks": [],
        })

    return pages


# ══════════════════════════════════════════════════════════════════════════
#  ParamBridge
# ══════════════════════════════════════════════════════════════════════════

class ParamBridge(QObject):
    groupsChanged  = pyqtSignal()
    statusChanged  = pyqtSignal()
    errorChanged   = pyqtSignal()
    enabledChanged = pyqtSignal()
    savedChanged   = pyqtSignal()

    def __init__(self, get_node_ip: Callable[[int], str], parent=None) -> None:
        super().__init__(parent)
        self._get_node_ip = get_node_ip
        self._active_node = 1
        self._enabled = True
        self._pkt_sent_slow = 0
        self._pkt_sent_fast = 0
        self._error: str | None = None
        self._defaults_loaded = False
        self._status = ""
        self._groups: list[dict] = []

        try:
            self._config = load_param_config(PARAM_CONFIG_PATH)
        except ValueError as exc:
            log.error("param_config.json ungültig: %s", exc)
            self._error = str(exc)
            self._config = ParamConfig(floats=[], bools=[], fast_floats=[], joysticks=[])

        self._store = ParamStore(self._config)

        if self._error is None:
            defaults = read_param_defaults_h(PARAM_DEFAULTS_H_PATH)
            if defaults:
                self._defaults_loaded = self._store.apply_defaults_h(defaults)
            self._groups = _build_groups(self._config)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._refresh_status()

        if self._error is None:
            self._slow_timer = QTimer(self)
            self._slow_timer.setInterval(PARAM_SLOW_SEND_INTERVAL_MS)
            self._slow_timer.timeout.connect(self._send_slow_tick)
            self._slow_timer.start()

            self._fast_timer = QTimer(self)
            self._fast_timer.setInterval(PARAM_FAST_SEND_INTERVAL_MS)
            self._fast_timer.timeout.connect(self._send_fast_tick)
            self._fast_timer.start()

            self._status_timer = QTimer(self)
            self._status_timer.setInterval(500)
            self._status_timer.timeout.connect(self._refresh_status)
            self._status_timer.start()

    # ── Properties ─────────────────────────────────────────────────────────
    @pyqtProperty(str, notify=errorChanged)
    def configError(self):
        return self._error or ""

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

    # ── Slots: Werte-Änderungen aus QML ───────────────────────────────────
    @pyqtSlot(int, float)
    def setSlowFloat(self, index: int, value: float) -> None:
        if 0 <= index < len(self._store.floats):
            self._store.set_float(index, value)

    @pyqtSlot(int, bool)
    def setSlowBool(self, index: int, value: bool) -> None:
        if 0 <= index < len(self._store.bools):
            self._store.set_bool(index, value)

    @pyqtSlot(int, float)
    def setFastFloat(self, index: int, value: float) -> None:
        if 0 <= index < len(self._store.fast_floats):
            self._store.set_fast_float(index, value)

    @pyqtSlot(bool)
    def setEnabled(self, value: bool) -> None:
        self._enabled = value
        self.enabledChanged.emit()
        self._refresh_status()

    @pyqtSlot()
    def saveDefaults(self) -> None:
        try:
            write_param_defaults_h(
                PARAM_DEFAULTS_H_PATH,
                self._store.floats, self._store.bools, self._store.fast_floats,
            )
            self._status = f"Gespeichert: {PARAM_DEFAULTS_H_PATH.name}"
            self.statusChanged.emit()
            log.info("Param-Defaults gespeichert nach %s", PARAM_DEFAULTS_H_PATH)
        except OSError as exc:
            log.error("Konnte param_defaults.h nicht schreiben: %s", exc)

    # ── Von AppBridge aufgerufen ───────────────────────────────────────────
    def set_active_node(self, node_id: int) -> None:
        self._active_node = node_id
        self._refresh_status()

    # ── Senden ────────────────────────────────────────────────────────────
    def _current_target(self, fast: bool) -> tuple[str, int]:
        ip = self._get_node_ip(self._active_node)
        if fast:
            port = UDP_PARAM_FAST_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_FAST_PORT_NODE2
        else:
            port = UDP_PARAM_SLOW_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_SLOW_PORT_NODE2
        return ip, port

    def _send_slow_tick(self) -> None:
        if not self._enabled:
            return
        ip, port = self._current_target(fast=False)
        try:
            self._sock.sendto(self._store.pack_slow(), (ip, port))
            self._pkt_sent_slow += 1
        except OSError as exc:
            log.warning("Slow-Param-Sendefehler: %s", exc)

    def _send_fast_tick(self) -> None:
        if not self._enabled:
            return
        ip, port = self._current_target(fast=True)
        try:
            self._sock.sendto(self._store.pack_fast(), (ip, port))
            self._pkt_sent_fast += 1
        except OSError as exc:
            log.warning("Fast-Param-Sendefehler: %s", exc)

    def _refresh_status(self) -> None:
        ip = self._get_node_ip(self._active_node)
        state = "aktiv" if self._enabled else "pausiert"
        self._status = (
            f"{state} -> Node {self._active_node} ({ip}) - "
            f"Slow: {PARAM_SLOW_SEND_HZ:.1f} Hz ({self._pkt_sent_slow} Pkt) - "
            f"Fast: {PARAM_FAST_SEND_HZ:.0f} Hz ({self._pkt_sent_fast} Pkt)"
        )
        self.statusChanged.emit()
