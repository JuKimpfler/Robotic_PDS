"""
bridge/app_bridge.py — zentrale Fassade, ersetzt main_window.py
====================================================================
Entspricht funktional exakt der bisherigen `MainWindow`-Logik
(_poll_data, _on_node_toggled, get_active_node_ip, LED-Status,
Pakete/Sekunde) — nur dass hier keine Widgets mehr aktualisiert werden,
sondern Qt-Properties/-Signale, an die QML sich bindet.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtProperty, pyqtSlot

from config import (
    GUI_TIMER_MS, NODE1_IP, NODE2_IP, VARIABLE_NAMES, NODE_TIMEOUT_SEC,
    UDP_CHANNEL_DESC_REQUEST_PORT_NODE1, UDP_CHANNEL_DESC_REQUEST_PORT_NODE2,
)
from network_worker import NetworkManager
from channel_registry import ChannelRegistry, send_descriptor_request
from bridge.telemetry_bridge import TelemetryBridge
from bridge.plot_bridge import PlotBridge
from bridge.param_bridge import ParamBridge
from bridge.visuals_bridge import VisualsBridge

log = logging.getLogger("bridge.app")


class AppBridge(QObject):
    activeNodeChanged = pyqtSignal()
    ppsChanged        = pyqtSignal()
    ledChanged        = pyqtSignal()
    statusMessage      = pyqtSignal(str)

    def __init__(self, network_manager: NetworkManager, parent=None) -> None:
        super().__init__(parent)
        self._nm = network_manager
        self._active_node = 1
        self._pkt_count = 0
        self._pps = 0
        self._node_connected = {1: False, 2: False}
        self._node_ips = {1: NODE1_IP, 2: NODE2_IP}

        # ── Sub-Bridges (eine je Tab) ─────────────────────────────────────
        # Bewusst als PRIVATE Attribute (_telemetry etc.) gehalten und über
        # pyqtProperty (weiter unten) öffentlich gemacht: reine Python-
        # Instanzattribute sind für das QML-Meta-Objekt-System unsichtbar —
        # `appBridge.plotter` käme in QML sonst als `undefined` an.
        self._telemetry = TelemetryBridge(self)
        self._plotter   = PlotBridge(self)
        self._visuals   = VisualsBridge(self)
        self._params    = ParamBridge(self.get_active_node_ip, self)

        # Zeitpunkt des letzten empfangenen Pakets je Node, für die
        # Verbindungs-LEDs (siehe _poll_data).
        self._node_last_seen = {1: 0.0, 2: 0.0}

        # ── Poll-Timer: identisch zu main_window.py::_poll_data ──
        #    GUI_TIMER_MS = 1000 / GUI_FPS = 50 ms -> 20 Hz
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(GUI_TIMER_MS)
        self._poll_timer.timeout.connect(self._poll_data)
        self._poll_timer.start()

        # ── Statistik-Timer (1 Hz) ─────────────────────────────────────────
        self._stat_timer = QTimer(self)
        self._stat_timer.setInterval(1000)
        self._stat_timer.timeout.connect(self._update_pps)
        self._stat_timer.start()

    # ── Sub-Bridge-Properties (constant: Objekt-Identität ändert sich nie) ─
    @pyqtProperty(QObject, constant=True)
    def telemetry(self):
        return self._telemetry

    @pyqtProperty(QObject, constant=True)
    def plotter(self):
        return self._plotter

    @pyqtProperty(QObject, constant=True)
    def visuals(self):
        return self._visuals

    @pyqtProperty(QObject, constant=True)
    def params(self):
        return self._params

    # ── Weitere Properties für QML ────────────────────────────────────────
    @pyqtProperty(int, notify=activeNodeChanged)
    def activeNode(self):
        return self._active_node

    @pyqtProperty(int, notify=ppsChanged)
    def packetsPerSecond(self):
        return self._pps

    @pyqtProperty(bool, notify=ledChanged)
    def node1Connected(self):
        return self._node_connected[1]

    @pyqtProperty(bool, notify=ledChanged)
    def node2Connected(self):
        return self._node_connected[2]

    @pyqtProperty(str, notify=ledChanged)
    def node1Ip(self):
        return self._node_ips[1]

    @pyqtProperty(str, notify=ledChanged)
    def node2Ip(self):
        return self._node_ips[2]

    # ── Slot: Node-Wechsel (aus NodeSelector.qml) ─────────────────────────
    @pyqtSlot(int)
    def setActiveNode(self, node_id: int) -> None:
        if node_id not in (1, 2) or node_id == self._active_node:
            return
        self._active_node = node_id
        self._telemetry.clear_stats()
        self._plotter.clearBuffer()
        self._params.set_active_node(node_id)
        self.activeNodeChanged.emit()
        self.statusMessage.emit(f"Node {node_id} aktiviert.")

    # ── Von main_qml.py / ParamBridge aufgerufen ──────────────────────────
    def get_active_node_ip(self, node_id: int) -> str:
        default_ip = NODE1_IP if node_id == 1 else NODE2_IP
        return self._node_ips.get(node_id, default_ip)

    # ── Daten-Pipeline (identisch zur bisherigen _poll_data-Logik) ───────
    def _poll_data(self) -> None:
        now = monotonic()
        ip_changed = False
        batch: list = []

        # BEIDE Queues leeren, nicht nur die des aktiven Nodes.
        # Die Empfänger-Prozesse befüllen unabhängig vom GUI-Zustand beide
        # Queues; wurde die des inaktiven Nodes nie gelesen, lief sie bis
        # DATA_QUEUE_MAXSIZE (300) voll und blieb es — der zugehörige
        # Prozess hat danach dauerhaft jedes Paket verworfen, und beim
        # Umschalten auf diesen Node kamen erst einmal 300 uralte Pakete an.
        # Nebeneffekt: die Verbindungs-LED des inaktiven Nodes stimmt jetzt.
        for nid in (1, 2):
            q = self._nm.get_queue(nid)
            try:
                while True:
                    _nid, _ts, values, sender_ip = q.get_nowait()
                    if nid == self._active_node:
                        batch.append(values)
                    if self._node_ips.get(nid) != sender_ip:
                        self._node_ips[nid] = sender_ip
                        ip_changed = True
                    self._node_last_seen[nid] = now
            except Exception:
                pass   # Queue leer

        # ── Verbindungs-LEDs: auch das AUSbleiben von Paketen auswerten ──
        #    Bisher wurde `_node_connected` nur auf True gesetzt und nie
        #    wieder zurück — eine einmal grüne LED blieb grün, selbst wenn
        #    der Node längst abgeschaltet war.
        led_changed = ip_changed
        for nid in (1, 2):
            alive = (now - self._node_last_seen[nid]) < NODE_TIMEOUT_SEC
            if alive != self._node_connected[nid]:
                self._node_connected[nid] = alive
                led_changed = True
        if led_changed:
            self.ledChanged.emit()

        # Namens-/Overlay-Deskriptor vom Teensy (einmalig beim Boot + auf
        # Anfrage). Bewusst VOR dem batch-Abbruch: der Deskriptor kommt über
        # eine eigene Queue und wurde bisher nur dann ausgewertet, wenn im
        # selben 50-ms-Fenster auch Telemetrie eintraf.
        self._poll_descriptor()

        if not batch:
            return

        self._pkt_count += len(batch)
        latest = batch[-1]

        self._telemetry.update_data(latest)
        self._plotter.append_batch(batch)

    def _poll_descriptor(self) -> None:
        # Auch hier beide Queues leeren (siehe _poll_data): sonst sammeln
        # sich Deskriptoren des inaktiven Nodes unbegrenzt an und werden beim
        # Umschalten alle auf einmal verarbeitet.
        data = None
        for nid in (1, 2):
            q = self._nm.get_desc_queue(nid)
            try:
                while True:
                    latest = q.get_nowait()   # nur das neueste Paket interessiert
                    if nid == self._active_node:
                        data = latest
            except Exception:
                pass   # Queue leer

        if data is None:
            return

        registry = ChannelRegistry.from_json_dict(data)

        VARIABLE_NAMES.update(registry.channel_names)
        self._telemetry.set_names(registry.channel_names)
        self._params.apply_names(
            registry.param_slow_float_names,
            registry.param_slow_bool_names,
            registry.param_fast_float_names,
        )
        self._visuals.apply_overlay_defaults_from_registry(registry)

        log.info(
            "Namens-/Overlay-Deskriptor empfangen (Node %d): %d Kanalnamen, %d Overlay-Einträge.",
            self._active_node, len(registry.channel_names), len(registry.overlays),
        )

    @pyqtSlot()
    def requestChannelNames(self) -> None:
        """Von QML aufrufbar (siehe StatusBar.qml/Main.qml) — fordert eine
        Neuübertragung des Namens-/Overlay-Deskriptors an, da der Teensy ihn
        sonst nur einmalig beim Boot sendet."""
        ip = self.get_active_node_ip(self._active_node)
        port = (UDP_CHANNEL_DESC_REQUEST_PORT_NODE1 if self._active_node == 1
                else UDP_CHANNEL_DESC_REQUEST_PORT_NODE2)
        send_descriptor_request(ip, port)
        self.statusMessage.emit(f"Kanalnamen von Node {self._active_node} ({ip}) angefordert.")

    def _update_pps(self) -> None:
        self._pps = self._pkt_count
        self._pkt_count = 0
        self.ppsChanged.emit()

    # ── Aufräumen ──────────────────────────────────────────────────────────
    @pyqtSlot()
    def shutdown(self) -> None:
        self._params.controller.shutdown()
        self._nm.stop()

    # ── Strg+S in der GUI (siehe Shortcut in qml/Main.qml) ────────────────
    @pyqtSlot()
    def systemShutdown(self) -> None:
        """Fährt den Raspberry Pi kontrolliert herunter. Unter Windows
        (Entwicklungs-/Testbetrieb) wird der Aufruf nur geloggt, damit ein
        Test auf dem PC nicht versehentlich das Entwickler-System
        herunterfährt."""
        log.warning("Shutdown angefordert (Strg+S).")
        if not sys.platform.startswith("linux"):
            log.warning(
                "systemShutdown() übersprungen (kein Linux-System, aktuell: %s).",
                sys.platform,
            )
            return
        try:
            subprocess.Popen(["systemctl", "poweroff"])
        except FileNotFoundError:
            try:
                subprocess.Popen(["sudo", "shutdown", "-h", "now"])
            except Exception as exc:
                log.error("Shutdown fehlgeschlagen: %s", exc)
        except Exception as exc:
            log.error("Shutdown fehlgeschlagen: %s", exc)
