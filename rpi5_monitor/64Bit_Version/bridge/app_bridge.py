"""
bridge/app_bridge.py — zentrale Fassade
====================================================================
Verteilt die eingehenden Datenströme auf die Unter-Brücken (Tabelle,
Plotter, Systemansicht, Parameter, Diagnose) und hält den Zustand, der
zu keinem einzelnen Tab gehört: aktiver Node, Verbindungs-LEDs,
Pakete/Sekunde, Statuszeile.

Drei Datenströme kommen über je eigene Prozesse herein (siehe
network_worker.py):
    Telemetrie   100 Hz je Node   -> Tabelle, Plotter, Systemansicht
    Deskriptor   selten           -> Namen, Einheiten, Param-Konfiguration
    Aux          1..20 Hz         -> Ereignisse, Param-Ack, Node-Status
"""
from __future__ import annotations

import logging
import subprocess
import sys
from time import monotonic

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtProperty, pyqtSlot

import runtime_config
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
from bridge.diag_bridge import DiagBridge
from bridge.settings_bridge import SettingsBridge

log = logging.getLogger("bridge.app")


# Wie lange eine Statusmeldung in der Fußzeile stehen bleibt.
_STATUS_MESSAGE_MS = 6000

# Frühestens so oft dürfen die Kanalnamen automatisch neu angefordert werden.
# Bewusst träge: jede Anfrage kostet den Teensy mehrere Sekunden UART-Zeit,
# und auf einer schlechten Funkstrecke soll das nicht im Sekundentakt passieren.
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
    statusMessage     = pyqtSignal(str)
    statusTextChanged = pyqtSignal()
    firmwareChanged   = pyqtSignal()

    def __init__(self, network_manager: NetworkManager, parent=None) -> None:
        super().__init__(parent)
        self._nm = network_manager
        self._active_node = 1
        self._pkt_count = {1: 0, 2: 0}
        self._pps = 0
        self._node_connected = {1: False, 2: False}
        self._node_ips = {1: NODE1_IP, 2: NODE2_IP}
        self._shutdown_done = False

        # ── Robustheit gegen Neustarts ────────────────────────────────────
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
        self._settings  = SettingsBridge(self)
        self._telemetry = TelemetryBridge(self)
        self._plotter   = PlotBridge(self)
        self._visuals   = VisualsBridge(self)
        self._params    = ParamBridge(self.get_active_node_ip, self)
        self._diag      = DiagBridge(self._params.rtt_ms, self)

        # Ereignisse des Teensy als senkrechte Marke in den Plotter.
        self._diag.marker_sink = self._plotter.add_marker
        # Akku-Warnung: Konfiguration lebt in den Einstellungen (dauerhaft),
        # ausgewertet wird sie in der Diagnose-Brücke.
        self._diag.load_battery_config(self._settings.battery())
        self._diag.batteryConfigChanged.connect(self._store_battery_config)
        # Meldungen des Overlay-Editors (gespeichert, verworfen, ...)
        # laufen in dieselbe Fusszeile wie alles andere.
        self._visuals.notice.connect(self.statusMessage)
        self._params.setKeyboardEnabled(self._settings.keyboardControl)
        self._settings.settingsChanged.connect(self._apply_settings)

        # Zeitpunkt des letzten empfangenen Pakets je Node, für die
        # Verbindungs-LEDs (siehe _poll_data).
        self._node_last_seen = {1: 0.0, 2: 0.0}

        # ── Poll-Timer: GUI_TIMER_MS = 1000 / GUI_FPS = 50 ms -> 20 Hz ────
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

    @pyqtProperty(QObject, constant=True)
    def diag(self):
        return self._diag

    @pyqtProperty(QObject, constant=True)
    def settings(self):
        return self._settings

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

    @pyqtProperty(str, notify=firmwareChanged)
    def firmwareText(self):
        """Firmware-Stand des aktiven Roboters für die Fußzeile (E2)."""
        reg = self._registry.get(self._active_node)
        return reg.firmware_label() if reg is not None else ""

    @pyqtProperty(str, notify=statusTextChanged)
    def statusText(self):
        """Letzte Statusmeldung für die Fußzeile (StatusBar.qml)."""
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

    @safe_slot
    def _apply_settings(self) -> None:
        self._params.setKeyboardEnabled(self._settings.keyboardControl)

    def _store_battery_config(self) -> None:
        self._settings.store_battery(self._diag.battery_config_dict())

    # ── Slot: Node-Wechsel (aus NodeSelector.qml) ─────────────────────────
    @pyqtSlot(int)
    def setActiveNode(self, node_id: int) -> None:
        if node_id not in (1, 2) or node_id == self._active_node:
            return
        self._active_node = node_id
        self._telemetry.clear_stats()
        self._plotter.clearBuffer()
        self._params.set_active_node(node_id)
        self._diag.set_active_node(node_id)
        self._visuals.set_node(node_id)
        self.activeNodeChanged.emit()
        self.firmwareChanged.emit()

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

    # ══════════════════════════════════════════════════════════════════════
    #  Daten-Pipeline
    # ══════════════════════════════════════════════════════════════════════

    @safe_slot
    def _poll_data(self) -> None:
        now = monotonic()
        ip_changed = False
        batch: list[np.ndarray] = []

        # BEIDE Queues leeren, nicht nur die des aktiven Nodes.
        # Die Empfänger-Prozesse befüllen unabhängig vom GUI-Zustand beide
        # Queues; wurde die des inaktiven Nodes nie gelesen, lief sie bis
        # DATA_QUEUE_MAXSIZE (300) voll und blieb es — der zugehörige
        # Prozess hat danach dauerhaft jedes Paket verworfen, und beim
        # Umschalten auf diesen Node kamen erst einmal 300 uralte Pakete an.
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
                self._pkt_count[nid] += 1
                self._diag.note_packet(nid, ts)
                self._check_stream_continuity(nid, ts)
                self._node_last_seen[nid] = now

        # ── Verbindungs-LEDs: auch das AUSbleiben von Paketen auswerten ──
        led_changed = ip_changed
        for nid in (1, 2):
            alive = (now - self._node_last_seen[nid]) < NODE_TIMEOUT_SEC
            if alive != self._node_connected[nid]:
                self._node_connected[nid] = alive
                led_changed = True
        if led_changed:
            self.ledChanged.emit()

        # Deskriptor und Aux-Uplink haben eigene Queues und werden bewusst
        # VOR dem batch-Abbruch ausgewertet: sonst käme ein Ereignis nur
        # dann an, wenn im selben 50-ms-Fenster auch Telemetrie eintraf.
        self._poll_descriptor()
        self._poll_aux()

        if not batch:
            return

        latest = batch[-1]
        self._telemetry.update_data(latest)
        self._diag.note_values(latest)
        self._plotter.append_block(self._stack(batch))

    @staticmethod
    def _stack(batch: list[np.ndarray]) -> np.ndarray:
        """Die Pakete eines Poll-Durchlaufs in EIN 2D-Array legen.

        Die Einzelpakete können unterschiedlich lang sein (der Empfänger
        schneidet nachlaufende Dummy-Kanäle ab, siehe network_worker.py).
        Fehlende Spalten werden zu NaN — der Plotter unterbricht die Linie
        dort, statt eine Null vorzutäuschen.

        Ab hier ist alles numpy: der Plotter bekommt einen einzigen Block
        statt einer Python-Liste, und schreibt ihn in einem Rutsch in seinen
        Ringpuffer (siehe plot_bridge.append_block).
        """
        n = len(batch)
        width = max(v.shape[0] for v in batch)
        if n == 1:
            return batch[0].reshape(1, -1)
        block = np.full((n, width), np.nan, dtype=np.float32)
        for i, v in enumerate(batch):
            block[i, :v.shape[0]] = v
        return block

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
            if node_id == self._active_node:
                # Min/Max und Plotter-Verlauf beziehen sich auf den alten Lauf.
                self._telemetry.clear_stats()
                self._plotter.clearBuffer()
            self._request_channel_names(node_id, reason="Teensy neu gestartet")
            self.statusMessage.emit(f"Node {node_id}: Teensy neu gestartet.")
            self._diag.add_local(f"Node {node_id}: Teensy neu gestartet", 1)
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
                "Deskriptor empfangen (Node %d): %d Kanalnamen, %d Einheiten, "
                "%d Overlays%s.",
                nid, len(registry.channel_names), len(registry.channel_units),
                len(registry.overlays),
                f", {registry.firmware_label()}" if registry.firmware_label() else "",
            )
            self._persist_registry(nid, data, registry)
            self._diag.set_firmware(nid, registry.firmware_label())
            if nid == self._active_node:
                self._apply_registry(registry)
                self.firmwareChanged.emit()

    def _persist_registry(self, node_id: int, raw: dict, registry: ChannelRegistry) -> None:
        """Deskriptor und daraus abgeleitete Konfiguration dauerhaft ablegen.

        Damit steht nach einem Neustart der GUI sofort wieder alles bereit,
        auch ohne eingeschalteten Roboter — siehe runtime_config.py.
        """
        if not self._settings.autoApplyTeensyConfig:
            return
        try:
            runtime_config.save_descriptor(node_id, raw)
            _path, written = runtime_config.sync_param_config(node_id, registry.param_cfg)
        except Exception:                            # noqa: BLE001
            log.exception("Konfiguration von Node %d konnte nicht gespeichert werden.", node_id)
            return
        if written:
            self.statusMessage.emit(
                f"Parameter-Konfiguration von Node {node_id} übernommen und gespeichert.")
            self._diag.add_local(f"Node {node_id}: Parameter-Konfiguration übernommen", 0)
            if node_id == self._active_node:
                self._params.reload_for_node(node_id)

    def _apply_registry(self, registry: ChannelRegistry) -> None:
        """Empfangene Namen/Einheiten/Overlays in alle Tabs übernehmen."""
        VARIABLE_NAMES.update(registry.channel_names)
        self._telemetry.set_names(registry.channel_names)
        self._telemetry.set_units(registry.channel_units)
        self._plotter.set_names(registry.channel_names)
        self._plotter.set_units(registry.channel_units)
        self._params.apply_names(
            registry.param_slow_float_names,
            registry.param_slow_bool_names,
            registry.param_fast_float_names,
        )
        self._visuals.apply_overlay_defaults_from_registry(registry, self._active_node)

    @safe_slot
    def _poll_aux(self) -> None:
        """Ereignisse, Parameter-Rückmeldung und Node-Status verteilen."""
        for nid in (1, 2):
            q = self._nm.get_aux_queue(nid)
            while True:
                try:
                    _nid, kind, data = q.get_nowait()
                except Exception:
                    break   # Queue leer
                if kind == "event":
                    self._diag.apply_event(nid, data)
                elif kind == "ack":
                    self._params.apply_ack(nid, data)
                elif kind == "status":
                    self._diag.apply_node_status(nid, data)

    @pyqtSlot()
    def requestChannelNames(self) -> None:
        """Von QML aufrufbar (siehe Main.qml) — fordert eine Neuübertragung
        des Deskriptors an. Im Normalfall nicht nötig: der Teensy meldet die
        Namen beim Boot, wiederholt sie solange keine GUI antwortet, und die
        GUI fragt bei einer Datenlücke selbst nach."""
        # Beim Klick bewusst ohne Rate-Limit — der Nutzer erwartet eine Aktion.
        self._last_name_request[self._active_node] = 0.0
        self._request_channel_names(self._active_node, reason="manuell angefordert")
        ip = self.get_active_node_ip(self._active_node)
        self.statusMessage.emit(f"Kanalnamen von Node {self._active_node} ({ip}) angefordert.")

    @pyqtSlot()
    def resetStoredConfig(self) -> None:
        """Die vom Teensy übernommene, gespeicherte Konfiguration des aktiven
        Nodes verwerfen. Beim nächsten Deskriptor wird sie neu aufgebaut."""
        removed = runtime_config.clear(self._active_node)
        self._registry[self._active_node] = None
        self.statusMessage.emit(
            f"Gespeicherte Konfiguration von Node {self._active_node} verworfen "
            f"({removed} Dateien).")
        self._last_name_request[self._active_node] = 0.0
        self._request_channel_names(self._active_node, reason="nach Zurücksetzen")

    @safe_slot
    def _update_pps(self) -> None:
        self._pps = self._pkt_count[self._active_node]
        for nid in (1, 2):
            self._diag.note_pps(nid, self._pkt_count[nid])
            self._pkt_count[nid] = 0
        self.ppsChanged.emit()
        self._diag.linkChanged.emit()
        self._diag.nodeStatusChanged.emit()

        # Abgestürzte Empfänger-Prozesse neu starten (siehe
        # NetworkManager.supervise) — ohne das bliebe die Telemetrie eines
        # Nodes nach einem einzelnen Fehler bis zum GUI-Neustart tot.
        for name in self._nm.supervise():
            self.statusMessage.emit(f"Empfänger {name} neu gestartet.")
            self._diag.add_local(f"Empfänger {name} neu gestartet", 1)

    # ── Aufräumen ──────────────────────────────────────────────────────────
    @pyqtSlot()
    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._poll_timer.stop()
        self._stat_timer.stop()
        self._diag.shutdown()
        self._settings.flush()
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
