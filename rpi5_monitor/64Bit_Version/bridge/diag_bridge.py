"""
bridge/diag_bridge.py — Tab "Diagnose"
=========================================
Bündelt alles, was nicht Messwert, sondern ZUSTAND ist:

  C1  Verbindungsqualität  — Pakete/s, geschätzter Paketverlust, echte
                             Round-Trip-Zeit zum Node
  C2  Node-Systemstatus    — CPU-Temperatur, Last, Speicher, WLAN-Pegel,
                             Uptime des Pi Zero
  C3  Akku-Warnung         — optischer Alarm, sobald ein frei wählbarer Kanal
                             unter eine einstellbare Schwelle fällt
  A4/D2  Logbuch           — Ereignisse (PDS.event) und Logzeilen (PDS.log)
                             vom Teensy

Bewusst EINE Brücke statt vier: die vier Themen teilen sich denselben
Datenstrom (Aux-Uplink + Telemetrie), dieselbe Aktualisierungsrate und
dieselbe Seite in der Oberfläche. Vier QObject-Fassaden dafür wären mehr
Verdrahtung als Inhalt.

────────────────────────────────────────────────────────────────────────────
WIE DER PAKETVERLUST GESCHÄTZT WIRD
────────────────────────────────────────────────────────────────────────────
Das Telemetriepaket trägt keine Sequenznummer, wohl aber den micros()-Stand
des Teensy beim Absenden. Der Teensy sendet exakt alle 10 ms; die Differenz
zweier aufeinanderfolgender Zeitstempel ist also ein Vielfaches von 10 ms,
und aus dem Vielfachen ergibt sich, wie viele Pakete dazwischen fehlen.

Das kostet kein einziges Byte Wire-Format und ist trotzdem genau: nur wenn
der Teensy selbst ins Stocken kommt (txDrops), zählt es fälschlich als
Funkverlust — und genau das steht dann auch in seinen Diagnosekanälen.
"""
from __future__ import annotations

import logging
from collections import deque
from time import monotonic, strftime, localtime

from PyQt6.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot

from config import (
    EVENT_LOG_MAXLEN, PDS_EVENT_KIND_EVENT, PDS_EVENT_LEVEL_NAMES,
    BATTERY_ALARM_DEFAULTS,
)

log = logging.getLogger("bridge.diag")

# Ein Sprung von mehr als einer Sekunde ist keine Funklücke mehr, sondern ein
# Neustart oder ein längerer Ausfall — der wird separat gemeldet und darf die
# Verlustquote nicht verfälschen.
_MAX_GAP_US = 1_000_000
_NOMINAL_PERIOD_US = 10_000

# Über so viele Pakete wird die Verlustquote gemittelt (10 s bei 100 Hz).
_LOSS_WINDOW = 1000

# Nach dieser Zeit ohne Statuspaket gilt der Node-Status als veraltet.
_STATUS_STALE_S = 4.0


class NodeLink:
    """Verbindungs- und Systemzustand EINES Nodes."""

    __slots__ = ("expected", "received", "last_ts", "gaps", "status", "status_time")

    def __init__(self) -> None:
        # Ringpuffer aus (erwartet, empfangen) je Auswertefenster
        self.expected = deque(maxlen=_LOSS_WINDOW)
        self.received = 0
        self.last_ts: int | None = None
        self.gaps = 0
        self.status: dict | None = None
        self.status_time = 0.0

    def note_packet(self, timestamp: int) -> None:
        prev = self.last_ts
        self.last_ts = timestamp
        if prev is None:
            self.expected.append(1)
            return
        # Modulo 2^32: der reguläre micros()-Überlauf alle ~71,6 Minuten ist
        # kein Sprung (siehe app_bridge._check_stream_continuity).
        delta = (timestamp - prev) & 0xFFFF_FFFF
        if delta > _MAX_GAP_US:
            self.gaps += 1
            self.expected.append(1)
            return
        # Wie viele Sendeperioden liegen dazwischen? 1 = lückenlos.
        steps = max(1, int(round(delta / _NOMINAL_PERIOD_US)))
        self.expected.append(min(steps, 50))

    def loss_percent(self) -> float:
        total = sum(self.expected)
        if total <= 0:
            return 0.0
        got = len(self.expected)
        return max(0.0, (1.0 - got / total) * 100.0)

    def status_fresh(self) -> bool:
        return self.status is not None and (monotonic() - self.status_time) < _STATUS_STALE_S


class DiagBridge(QObject):
    linkChanged     = pyqtSignal()
    nodeStatusChanged = pyqtSignal()
    eventsChanged   = pyqtSignal()
    alarmChanged    = pyqtSignal()
    batteryConfigChanged = pyqtSignal()

    def __init__(self, get_rtt, parent=None) -> None:
        super().__init__(parent)
        self._get_rtt = get_rtt          # Callable[[int], float | None]
        self._links = {1: NodeLink(), 2: NodeLink()}
        self._active_node = 1
        self._pps = {1: 0, 2: 0}
        self._fw = {1: "", 2: ""}

        # ── Logbuch ───────────────────────────────────────────────────────
        self._events: deque[dict] = deque(maxlen=EVENT_LOG_MAXLEN)
        self._event_filter = 0           # 0 = alles, 1 = ab Warnung, 2 = nur Fehler
        self._unseen_errors = 0

        # ── Akku-Warnung (C3) ─────────────────────────────────────────────
        self._batt = dict(BATTERY_ALARM_DEFAULTS)
        self._batt_value = float("nan")
        self._batt_below_since = 0.0
        self._alarm_level = 0            # 0 = ok, 1 = Warnung, 2 = kritisch

        # Marken an den Plotter durchreichen (wird von AppBridge gesetzt).
        self.marker_sink = None

    # ══════════════════════════════════════════════════════════════════════
    #  Eingehende Daten
    # ══════════════════════════════════════════════════════════════════════

    def note_packet(self, node_id: int, timestamp: int) -> None:
        link = self._links.get(node_id)
        if link is not None:
            link.note_packet(timestamp)

    def note_pps(self, node_id: int, pps: int) -> None:
        self._pps[node_id] = pps

    def set_active_node(self, node_id: int) -> None:
        self._active_node = node_id
        self.linkChanged.emit()
        self.nodeStatusChanged.emit()

    def set_firmware(self, node_id: int, label: str) -> None:
        if self._fw.get(node_id) != label:
            self._fw[node_id] = label
            self.nodeStatusChanged.emit()

    def apply_node_status(self, node_id: int, data: dict) -> None:
        link = self._links.get(node_id)
        if link is None:
            return
        link.status = data
        link.status_time = monotonic()
        if node_id == self._active_node:
            self.nodeStatusChanged.emit()

    def apply_event(self, node_id: int, data: dict) -> None:
        """Ereignis/Logzeile vom Teensy ins Logbuch aufnehmen."""
        kind = data.get("kind", 1)
        level = int(data.get("level", 0))
        text = str(data.get("text", ""))
        entry = {
            "node": node_id,
            "time": strftime("%H:%M:%S", localtime()),
            "kind": "event" if kind == PDS_EVENT_KIND_EVENT else "log",
            "level": level,
            "levelName": PDS_EVENT_LEVEL_NAMES.get(level, "?"),
            "text": text,
            "value": float(data.get("value", 0.0)),
        }
        self._events.append(entry)
        if level >= 2:
            self._unseen_errors += 1

        # Ereignisse (keine Logzeilen) werden zusätzlich als senkrechte Marke
        # in den Plotter gelegt — aber nur für den gerade angezeigten Node.
        if (kind == PDS_EVENT_KIND_EVENT and node_id == self._active_node
                and self.marker_sink is not None):
            self.marker_sink(text, level)

        self.eventsChanged.emit()

    def note_values(self, values) -> None:
        """Letzter Telemetriestand — nur für die Akku-Überwachung."""
        chn = int(self._batt.get("channel", -1))
        if not self._batt.get("enabled") or chn < 0 or chn >= len(values):
            if self._alarm_level != 0:
                self._alarm_level = 0
                self.alarmChanged.emit()
            return

        value = float(values[chn])
        self._batt_value = value
        crit = float(self._batt.get("critical_below", 0.0))
        warn = float(self._batt.get("warn_below", 0.0))
        hold = float(self._batt.get("hold_seconds", 2.0))

        level = 2 if value < crit else (1 if value < warn else 0)
        now = monotonic()
        if level == 0:
            self._batt_below_since = 0.0
        elif self._batt_below_since == 0.0:
            self._batt_below_since = now
            level = 0       # Haltezeit läuft noch
        elif (now - self._batt_below_since) < hold:
            # Anlaufströme der Motoren ziehen die Spannung kurz herunter; ohne
            # diese Haltezeit blinkt der Alarm bei jedem Beschleunigen.
            level = 0

        if level != self._alarm_level:
            self._alarm_level = level
            if level > 0:
                log.warning("Akku-Alarm Stufe %d: Kanal %d = %.2f", level, chn, value)
            self.alarmChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Properties: Verbindungsqualität (C1)
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty("QVariantList", notify=linkChanged)
    def linkStats(self):
        """Je Node ein Datensatz für die Diagnoseseite."""
        out = []
        for nid in (1, 2):
            link = self._links[nid]
            rtt = self._get_rtt(nid) if self._get_rtt else None
            out.append({
                "node": nid,
                "pps": self._pps.get(nid, 0),
                "lossPercent": round(link.loss_percent(), 2),
                "gaps": link.gaps,
                "rttMs": -1.0 if rtt is None else round(rtt, 1),
                "firmware": self._fw.get(nid, ""),
                "active": nid == self._active_node,
            })
        return out

    @pyqtSlot()
    def resetLinkStats(self) -> None:
        for link in self._links.values():
            link.expected.clear()
            link.gaps = 0
        self.linkChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Properties: Node-Systemstatus (C2)
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty("QVariantList", notify=nodeStatusChanged)
    def nodeStatus(self):
        out = []
        for nid in (1, 2):
            link = self._links[nid]
            fresh = link.status_fresh()
            st = link.status or {}
            out.append({
                "node": nid,
                "fresh": fresh,
                "cpuTemp": _num(st.get("cpu_temp_c")),
                "load1": _num(st.get("load1")),
                "memUsedPct": _num(st.get("mem_used_pct")),
                "rssiDbm": _num(st.get("wifi_rssi_dbm")),
                "uptimeS": int(st.get("uptime_s", 0)),
                "uptimeText": _uptime_text(int(st.get("uptime_s", 0))),
                "teensyLink": bool(st.get("teensy_link", False)),
                "wifiOk": bool(st.get("wifi_ok", False)),
                "unicast": bool(st.get("unicast", False)),
                "uartPackets": int(st.get("uart_packets", 0)),
                "syncLosses": int(st.get("sync_losses", 0)),
                "active": nid == self._active_node,
            })
        return out

    # ══════════════════════════════════════════════════════════════════════
    #  Properties: Logbuch (A4/D2)
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty("QVariantList", notify=eventsChanged)
    def events(self):
        """Neueste zuerst — so steht das Interessante ohne Scrollen oben."""
        if self._event_filter <= 0:
            items = list(self._events)
        else:
            items = [e for e in self._events if e["level"] >= self._event_filter]
        return list(reversed(items))

    @pyqtProperty(int, notify=eventsChanged)
    def eventCount(self):
        return len(self._events)

    @pyqtProperty(int, notify=eventsChanged)
    def errorCount(self):
        return self._unseen_errors

    @pyqtProperty(int, notify=eventsChanged)
    def eventFilter(self):
        return self._event_filter

    @pyqtSlot(int)
    def setEventFilter(self, level: int) -> None:
        level = max(0, min(2, int(level)))
        if level != self._event_filter:
            self._event_filter = level
            self.eventsChanged.emit()

    @pyqtSlot()
    def clearEvents(self) -> None:
        self._events.clear()
        self._unseen_errors = 0
        self.eventsChanged.emit()

    @pyqtSlot()
    def acknowledgeErrors(self) -> None:
        if self._unseen_errors:
            self._unseen_errors = 0
            self.eventsChanged.emit()

    def add_local(self, text: str, level: int = 0) -> None:
        """Meldung der GUI selbst ins Logbuch (Node 0 = "lokal")."""
        self._events.append({
            "node": 0,
            "time": strftime("%H:%M:%S", localtime()),
            "kind": "log",
            "level": level,
            "levelName": PDS_EVENT_LEVEL_NAMES.get(level, "?"),
            "text": text,
            "value": 0.0,
        })
        if level >= 2:
            self._unseen_errors += 1
        self.eventsChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Properties: Akku-Warnung (C3)
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(int, notify=alarmChanged)
    def alarmLevel(self):
        """0 = ok, 1 = Warnung, 2 = kritisch. Rein optisch — es wird bewusst
        NICHTS am Roboter verändert."""
        return self._alarm_level

    @pyqtProperty(float, notify=alarmChanged)
    def batteryValue(self):
        return self._batt_value

    @pyqtProperty("QVariantMap", notify=batteryConfigChanged)
    def batteryConfig(self):
        return dict(self._batt)

    @pyqtSlot("QVariantMap")
    def setBatteryConfig(self, cfg) -> None:
        changed = False
        for key in ("enabled", "channel", "warn_below", "critical_below", "hold_seconds"):
            if key not in cfg:
                continue
            value = cfg[key]
            try:
                if key == "enabled":
                    value = bool(value)
                elif key == "channel":
                    value = int(value)
                else:
                    value = float(value)
            except (TypeError, ValueError):
                continue
            if self._batt.get(key) != value:
                self._batt[key] = value
                changed = True
        if changed:
            self._batt_below_since = 0.0
            self.batteryConfigChanged.emit()
            self.alarmChanged.emit()

    def battery_config_dict(self) -> dict:
        return dict(self._batt)

    def load_battery_config(self, cfg: dict) -> None:
        if isinstance(cfg, dict):
            self.setBatteryConfig(cfg)


# ══════════════════════════════════════════════════════════════════════════
#  Hilfsfunktionen
# ══════════════════════════════════════════════════════════════════════════

def _num(value) -> float:
    """NaN (nicht lesbarer Systemwert) wird zu einem Sentinel, den QML als
    "—" darstellt. QVariant kann NaN zwar transportieren, aber jeder
    Vergleich damit in JavaScript ist falsch-negativ."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return -999.0
    return -999.0 if v != v else v


def _uptime_text(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m, _s = divmod(rest, 60)
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"
