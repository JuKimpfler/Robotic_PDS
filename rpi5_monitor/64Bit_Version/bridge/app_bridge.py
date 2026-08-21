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
from bridge.utils import safe_slot
from bridge.telemetry_bridge import TelemetryBridge
from bridge.plot_bridge import PlotBridge
from bridge.param_bridge import ParamBridge
from bridge.visuals_bridge import VisualsBridge

log = logging.getLogger("bridge.app")


# Wie lange eine Statusmeldung in der Fußzeile stehen bleibt.
_STATUS_MESSAGE_MS = 6000

# Frühestens so oft dürfen die Kanalnamen automatisch neu angefordert werden.
# Bewusst träge: jede Anfrage kostet den Teensy ~12 kB UART-Zeit, und auf
# einer schlechten Funkstrecke soll das nicht im Sekundentakt passieren.
_NAME_REREQUEST_MIN_INTERVAL_S = 10.0

# Ein Sprung der Teensy-Zeitstempel um mehr als diese Spanne heißt: der Strom
# war unterbrochen (Funkloch) ODER der Teensy hat neu gestartet.
_TIMESTAMP_JUMP_US = 1_000_000

# ... und wenn der neue Zeitstempel zusätzlich klein ist, lief micros() gerade
# erst wieder von vorne los -> echter Neustart, keine bloße Funklücke.
_TIMESTAMP_FRESH_BOOT_US = 5_000_000


class AppBridge(QObject):
    activeNodeChanged = pyqtSignal()
    ppsChanged        = pyqtSignal()
    ledChanged        = pyqtSignal()
    statusMessage      = pyqtSignal(str)
    statusTextChanged  = pyqtSignal()

    def __init__(self, network_manager: NetworkManager, parent=None) -> None:
        super().__init__(parent)
        self._nm = network_manager
        self._active_node = 1
        self._pkt_count = 0
        self._pps = 0
        self._node_connected = {1: False, 2: False}
        self._node_ips = {1: NODE1_IP, 2: NODE2_IP}
        self._shutdown_done = False

        # ── Robustheit gegen Neustarts ────────────────────────────────────
        #  Je Node der zuletzt empfangene Teensy-Zeitstempel und der Zeitpunkt
        #  der letzten automatischen Namensanfrage (siehe _check_stream_continuity).
        self._last_ts: dict[int, int | None] = {1: None, 2: None}
        self._last_name_request: dict[int, float] = {1: 0.0, 2: 0.0}
        # Zuletzt empfangener Deskriptor JE NODE — beim Umschalten wird der
        # gespeicherte Stand erneut angewendet, statt bis zur nächsten
        # Übertragung mit den Namen des anderen Nodes weiterzulaufen.
        self._registry: dict[int, ChannelRegistry | None] = {1: None, 2: None}

        # Statuszeile (Fußzeile): letzte Meldung + Auto-Löschen
        self._status_text = ""
        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(self._clear_status_text)
        self.statusMessage.connect(self._on_status_message)

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

    @pyqtProperty(str, notify=statusTextChanged)
    def statusText(self):
        """Letzte Statusmeldung für die Fußzeile (StatusBar.qml). Vorher wurde
        `statusMessage` zwar emittiert, aber nirgends angezeigt."""
        return self._status_text

    # ── Statuszeile ───────────────────────────────────────────────────────
    def _on_status_message(self, text: str) -> None:
        self._status_text = text
        self.statusTextChanged.emit()
        self._status_clear_timer.start(_STATUS_MESSAGE_MS)

    @safe_slot
    def _clear_status_text(self) -> None:
        self._status_text = ""
        self.statusTextChanged.emit()

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

        # Namen des jetzt aktiven Nodes wiederherstellen. Liegt noch keiner
        # vor, einen anfordern — sonst stünden bis zur nächsten regulären
        # Übertragung die Namen des vorherigen Nodes in der Tabelle.
        registry = self._registry.get(node_id)
        if registry is not None:
            self._apply_registry(registry)
        else:
            self._request_channel_names(node_id, reason="Node gewechselt")

        self.statusMessage.emit(f"Node {node_id} aktiviert.")

    # ── Von main_qml.py / ParamBridge aufgerufen ──────────────────────────
    def get_active_node_ip(self, node_id: int) -> str:
        default_ip = NODE1_IP if node_id == 1 else NODE2_IP
        return self._node_ips.get(node_id, default_ip)

    # ── Daten-Pipeline (identisch zur bisherigen _poll_data-Logik) ───────
    @safe_slot
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
            while True:
                # Nur das Lesen selbst abfangen: waere die Verarbeitung mit
                # im try, wuerde ein Fehler dort wie "Queue leer" aussehen
                # und den Rest der Warteschlange stillschweigend liegen lassen.
                try:
                    _nid, ts, values, sender_ip = q.get_nowait()
                except Exception:
                    break   # Queue leer (oder beim Herunterfahren geschlossen)
                if nid == self._active_node:
                    batch.append(values)
                if self._node_ips.get(nid) != sender_ip:
                    self._node_ips[nid] = sender_ip
                    ip_changed = True
                self._check_stream_continuity(nid, ts)
                self._node_last_seen[nid] = now

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

    # ── Neustart-/Lückenerkennung ─────────────────────────────────────────
    def _check_stream_continuity(self, node_id: int, timestamp: int) -> None:
        """Erkennt am Teensy-Zeitstempel (micros() im Paket-Header), ob der
        Telemetriestrom unterbrochen war oder der Teensy neu gestartet hat —
        und fordert dann die Kanalnamen automatisch neu an.

        Die Differenz wird modulo 2^32 gerechnet, damit der reguläre Überlauf
        von micros() (alle ~71,6 Minuten) NICHT als Neustart durchgeht: dort
        ist die modulare Differenz weiterhin ~10 000 µs. Nach einem echten
        Reset beginnt micros() dagegen wieder bei ~0, die modulare Differenz
        wird dadurch riesig.
        """
        prev = self._last_ts.get(node_id)
        self._last_ts[node_id] = timestamp
        if prev is None:
            # Erstes Paket dieses Nodes seit GUI-Start -> Namen anfordern.
            self._request_channel_names(node_id, reason="Telemetrie gestartet")
            return

        delta = (timestamp - prev) & 0xFFFF_FFFF
        if delta <= _TIMESTAMP_JUMP_US:
            return

        if timestamp < _TIMESTAMP_FRESH_BOOT_US:
            # micros() läuft wieder bei ~0 los -> der Teensy wurde neu gestartet.
            # (Er meldet die Namen von sich aus erneut; die Anfrage hier ist die
            #  zweite Sicherung, falls das Paket auf dem Funkweg verloren geht.)
            if node_id == self._active_node:
                # Min/Max und Plotter-Verlauf beziehen sich auf den alten Lauf.
                self._telemetry.clear_stats()
                self._plotter.clearBuffer()
            self._request_channel_names(node_id, reason="Teensy neu gestartet")
            self.statusMessage.emit(f"Node {node_id}: Teensy neu gestartet.")
        elif self._registry.get(node_id) is None:
            # Nur eine Funklücke — Namen aber ohnehin noch nicht bekannt.
            self._request_channel_names(node_id, reason="Datenlücke, Namen fehlen noch")
        else:
            log.debug("Node %d: Telemetrielücke von %.1f s.", node_id, delta / 1e6)

    def _request_channel_names(self, node_id: int, reason: str = "") -> None:
        """Kanalnamen anfordern, aber höchstens alle paar Sekunden je Node."""
        now = monotonic()
        if now - self._last_name_request.get(node_id, 0.0) < _NAME_REREQUEST_MIN_INTERVAL_S:
            return
        self._last_name_request[node_id] = now
        ip = self.get_active_node_ip(node_id)
        port = (UDP_CHANNEL_DESC_REQUEST_PORT_NODE1 if node_id == 1
                else UDP_CHANNEL_DESC_REQUEST_PORT_NODE2)
        send_descriptor_request(ip, port)
        log.info("Kanalnamen von Node %d (%s) angefordert — %s.", node_id, ip, reason or "manuell")

    @safe_slot
    def _poll_descriptor(self) -> None:
        # Auch hier beide Queues leeren (siehe _poll_data): sonst sammeln
        # sich Deskriptoren des inaktiven Nodes unbegrenzt an und werden beim
        # Umschalten alle auf einmal verarbeitet.
        received: dict[int, dict] = {}
        for nid in (1, 2):
            q = self._nm.get_desc_queue(nid)
            while True:
                try:
                    received[nid] = q.get_nowait()   # nur das neueste zählt
                except Exception:
                    break   # Queue leer

        for nid, data in received.items():
            registry = ChannelRegistry.from_json_dict(data)
            if registry.is_empty():
                # Kann bei einem Teensy ohne einen einzigen Namen vorkommen —
                # dann aber bitte nicht die bereits bekannten Namen löschen.
                log.debug("Leerer Deskriptor von Node %d ignoriert.", nid)
                continue
            self._registry[nid] = registry
            log.info(
                "Namens-/Overlay-Deskriptor empfangen (Node %d): "
                "%d Kanalnamen, %d Overlay-Einträge.",
                nid, len(registry.channel_names), len(registry.overlays),
            )
            if nid == self._active_node:
                self._apply_registry(registry)

    def _apply_registry(self, registry: ChannelRegistry) -> None:
        """Empfangene Namen/Overlays in alle Tabs übernehmen."""
        VARIABLE_NAMES.update(registry.channel_names)
        self._telemetry.set_names(registry.channel_names)
        self._plotter.set_names(registry.channel_names)
        self._params.apply_names(
            registry.param_slow_float_names,
            registry.param_slow_bool_names,
            registry.param_fast_float_names,
        )
        self._visuals.apply_overlay_defaults_from_registry(registry)

    @pyqtSlot()
    def requestChannelNames(self) -> None:
        """Von QML aufrufbar (siehe Main.qml) — fordert eine Neuübertragung
        des Namens-/Overlay-Deskriptors an. Im Normalfall nicht nötig: der
        Teensy meldet die Namen beim Boot, wiederholt sie solange keine GUI
        antwortet, und die GUI fragt bei einer Datenlücke selbst nach."""
        # Beim Klick bewusst ohne Rate-Limit — der Nutzer erwartet eine Aktion.
        self._last_name_request[self._active_node] = 0.0
        self._request_channel_names(self._active_node, reason="manuell angefordert")
        ip = self.get_active_node_ip(self._active_node)
        self.statusMessage.emit(f"Kanalnamen von Node {self._active_node} ({ip}) angefordert.")

    @safe_slot
    def _update_pps(self) -> None:
        self._pps = self._pkt_count
        self._pkt_count = 0
        self.ppsChanged.emit()

        # Abgestürzte Empfänger-Prozesse neu starten (siehe
        # NetworkManager.supervise) — ohne das bliebe die Telemetrie eines
        # Nodes nach einem einzelnen Fehler bis zum GUI-Neustart tot.
        for name in self._nm.supervise():
            self.statusMessage.emit(f"Empfänger {name} neu gestartet.")

    # ── Aufräumen ──────────────────────────────────────────────────────────
    @pyqtSlot()
    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._poll_timer.stop()
        self._stat_timer.stop()
        self._params.shutdown()
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
