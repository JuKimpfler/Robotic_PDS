"""
bridge/plot_bridge.py — Tab 2 (Live-Plotter)
================================================
Zwei Klassen:
  PlotBridge  — Datenhaltung + Trigger + Marken, keine Zeichenlogik
  PlotCanvas  — QQuickPaintedItem, zeichnet den Inhalt von PlotBridge
                (per qmlRegisterType als <PlotCanvas> in QML nutzbar,
                 siehe main_qml.py)

────────────────────────────────────────────────────────────────────────────
WARUM AUSSCHLIESSLICH NUMPY
────────────────────────────────────────────────────────────────────────────
Bei 100 Hz, zwei Nodes und bis zu acht gleichzeitig dargestellten Kanaelen
gehen pro Sekunde einige tausend Werte durch diesen Code — und zwar im
GUI-Thread, der gleichzeitig die Oberflaeche zeichnet und den 100-Hz-Takt der
Fernsteuerung haelt. Jede Python-Schleife ueber Einzelwerte kostet hier
unmittelbar Reaktionszeit der Fernsteuerung.

Deshalb: EIN vorab angelegter 2D-Ringpuffer (Kurven x Samples, float32), in
den blockweise geschrieben wird. Kein deque, keine Listen, kein Umkopieren
pro Wert. Auch Trigger-Auswertung, Statistik und die Umrechnung in
Bildschirmkoordinaten laufen vektorisiert ueber ganze Bloecke.

────────────────────────────────────────────────────────────────────────────
TRIGGER (Oszilloskop-Prinzip)
────────────────────────────────────────────────────────────────────────────
Ein Trigger friert den Verlauf im Moment eines Ereignisses ein, statt dass man
danebensitzen und im richtigen Augenblick "Einfrieren" druecken muss. Die
Aufzeichnung laeuft im Ring immer mit; loest der Trigger aus, wird noch
`postFraction` der Fensterbreite weiter aufgezeichnet und dann eingefroren.
Im Bild steht die Ausloesestelle damit an der gewuenschten Position und man
sieht, was DAVOR passiert ist — der eigentliche Zweck der Sache.
"""
from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import Qt, QObject, QRectF, QPointF, pyqtSignal, pyqtProperty, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtQuick import QQuickPaintedItem

from config import MAX_FLOATS, PLOT_BUFFER_SIZE, VARIABLE_NAMES

log = logging.getLogger("bridge.plot")

# Bis zu so viele Kurven gleichzeitig. Mehr wird unlesbar, und der Ringpuffer
# ist mit dieser Zahl fest dimensioniert (8 x 500 x 4 B = 16 kB).
MAX_CURVES = 8

# Gut unterscheidbar auch auf einem hellen Hintergrund im Freien.
CURVE_COLORS = [
    "#00d4ff", "#f0a500", "#4ec9b0", "#f48771",
    "#c586c0", "#9cdcfe", "#b5cea8", "#ffd700",
]

# Trigger-Bedingungen. Die Namen gehen 1:1 an QML (siehe PlotterView.qml).
TRIGGER_MODES = ("above", "below", "rising", "falling", "change", "outside")
TRIGGER_LABELS = {
    "above":   "steigt über Schwelle",
    "below":   "fällt unter Schwelle",
    "rising":  "steigende Flanke",
    "falling": "fallende Flanke",
    "change":  "Sprung größer als",
    "outside": "verlässt Band ±",
}


class PlotBridge(QObject):
    bufferChanged        = pyqtSignal()
    statsChanged         = pyqtSignal()
    selectedVarChanged   = pyqtSignal()
    frozenChanged        = pyqtSignal()
    pointsChanged        = pyqtSignal()
    variableNamesChanged = pyqtSignal()
    channelsChanged      = pyqtSignal()
    triggerChanged       = pyqtSignal()
    markersChanged       = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cap = int(PLOT_BUFFER_SIZE)
        self._points = min(500, self._cap)

        # ── Ringpuffer: Zeile = Kurve, Spalte = Zeitpunkt ─────────────────
        #  NaN heisst "kein Wert" — der Kanal war in diesem Paket nicht
        #  belegt. np.nanmin/nanmax gehen damit sauber um, und die
        #  Zeichenroutine unterbricht die Linie an solchen Stellen.
        self._ring = np.full((MAX_CURVES, self._cap), np.nan, dtype=np.float32)
        self._write = 0        # naechster Schreibindex im Ring
        self._filled = 0       # wie viele Spalten gueltig sind
        self._total = 0        # absolut gezaehlte Samples seit clear()

        self._channels: list[int] = [0]
        self._names = [VARIABLE_NAMES.get(i, f"Var_{i:03d}") for i in range(MAX_FLOATS)]
        self._units: dict[int, str] = {}

        self._frozen = False
        self._frozen_snapshot: np.ndarray | None = None
        self._shared_scale = False
        self._stats = "—"

        # ── Trigger ───────────────────────────────────────────────────────
        self._trig_enabled = False
        self._trig_channel = 0
        self._trig_mode = "above"
        self._trig_level = 0.0
        self._trig_delta = 1.0        # fuer "change" / "outside"
        self._trig_post = 0.5         # Anteil des Fensters NACH der Ausloesung
        self._trig_auto_rearm = False
        self._trig_capture_at: int | None = None   # absoluter Sample-Index
        self._trig_fired_at: int | None = None
        self._trig_count = 0
        self._last_trig_value = np.nan

        # ── Marken (PDS.event auf dem Teensy) ─────────────────────────────
        #  Gespeichert wird der absolute Sample-Index bei EINTREFFEN des
        #  Ereignisses. Der Teensy schickt zwar einen micros()-Zeitstempel
        #  mit, aber die Zuordnung ueber ihn waere wegen des 71-Minuten-
        #  Ueberlaufs und der Funklaufzeit aufwendig, ohne sichtbar genauer
        #  zu sein: zwischen Ereignis und Eintreffen liegen typisch 10-30 ms,
        #  also ein bis drei Samples.
        self._markers: list[tuple[int, str, int]] = []   # (abs_index, text, level)

    # ══════════════════════════════════════════════════════════════════════
    #  Kanalauswahl
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty("QVariantList", notify=channelsChanged)
    def channels(self):
        return list(self._channels)

    @pyqtProperty(int, notify=channelsChanged)
    def maxCurves(self):
        return MAX_CURVES

    @pyqtSlot("QVariantList")
    def setChannels(self, channels) -> None:
        """Komplette Auswahl setzen (aus QML als Liste von Zahlen)."""
        clean: list[int] = []
        for c in channels:
            try:
                idx = int(c)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < MAX_FLOATS and idx not in clean:
                clean.append(idx)
            if len(clean) >= MAX_CURVES:
                break
        if not clean:
            clean = [0]
        if clean == self._channels:
            return

        # Die Zeilen des Ringpuffers haengen an der POSITION in der Auswahl,
        # nicht am Kanal. Beim Hinzufuegen einer fuenften Kurve wuerde ein
        # simples clearBuffer() den Verlauf der vier bereits laufenden Kurven
        # mitloeschen — genau in dem Moment, in dem man vergleichen will.
        # Deshalb werden die Zeilen umsortiert statt verworfen; neue Kurven
        # starten mit NaN und werden bis zum ersten Wert einfach nicht
        # gezeichnet.
        old = self._channels
        moved = np.full_like(self._ring, np.nan)
        for dst, chn in enumerate(clean):
            if chn in old:
                moved[dst] = self._ring[old.index(chn)]
        self._ring = moved
        self._channels = clean
        self._frozen_snapshot = None      # Zeilenzahl kann sich geaendert haben
        self.channelsChanged.emit()
        self._update_stats()
        self.bufferChanged.emit()

    @pyqtSlot(int)
    def toggleChannel(self, idx: int) -> None:
        """Kanal zur Auswahl hinzufuegen bzw. daraus entfernen."""
        current = list(self._channels)
        if idx in current:
            if len(current) == 1:
                return          # mindestens eine Kurve muss bleiben
            current.remove(idx)
        else:
            if len(current) >= MAX_CURVES:
                return
            current.append(idx)
        self.setChannels(current)

    @pyqtSlot(int)
    def setSelectedVar(self, idx: int) -> None:
        """Auswahl auf genau EINEN Kanal setzen (Einzelkurven-Betrieb)."""
        self.setChannels([idx])

    @pyqtProperty(int, notify=channelsChanged)
    def selectedVar(self) -> int:
        return self._channels[0] if self._channels else 0

    @pyqtProperty("QVariantList", notify=channelsChanged)
    def curveColors(self):
        return [CURVE_COLORS[i % len(CURVE_COLORS)] for i in range(len(self._channels))]

    @pyqtProperty("QVariantList", notify=statsChanged)
    def curveInfo(self):
        """Legende: je Kurve Name, Einheit, Farbe und Min/Max/Aktuell im
        sichtbaren Fenster. Wird nur beim Statistik-Update neu gebaut, nicht
        bei jedem Paket."""
        data = self.snapshot()
        out = []
        for row, chn in enumerate(self._channels):
            info = {
                "channel": chn,
                "name": self._names[chn] if chn < len(self._names) else f"Var_{chn:03d}",
                "unit": self._units.get(chn, ""),
                "color": CURVE_COLORS[row % len(CURVE_COLORS)],
                "min": 0.0, "max": 0.0, "last": 0.0, "valid": False,
            }
            if data is not None and data.shape[1] > 0:
                series = data[row]
                if np.any(np.isfinite(series)):
                    info["min"] = float(np.nanmin(series))
                    info["max"] = float(np.nanmax(series))
                    finite = series[np.isfinite(series)]
                    info["last"] = float(finite[-1])
                    info["valid"] = True
            out.append(info)
        return out

    # ══════════════════════════════════════════════════════════════════════
    #  Namen / Einheiten
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty("QVariantList", notify=variableNamesChanged)
    def variableNames(self):
        return self._names

    def set_names(self, names: dict[int, str]) -> None:
        if not names:
            return
        changed = False
        for i, name in names.items():
            if 0 <= i < len(self._names) and self._names[i] != name:
                self._names[i] = name
                changed = True
        if changed:
            self.variableNamesChanged.emit()

    def set_units(self, units: dict[int, str]) -> None:
        if units != self._units:
            self._units = dict(units)
            self.variableNamesChanged.emit()
            self.statsChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Fensterbreite / Einfrieren
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(int, notify=pointsChanged)
    def pointsCount(self) -> int:
        return self._points

    @pyqtSlot(int)
    def setPointsCount(self, n: int) -> None:
        n = max(50, min(self._cap, int(n)))
        if n == self._points:
            return
        self._points = n
        self.pointsChanged.emit()
        self.bufferChanged.emit()

    @pyqtProperty(bool, notify=frozenChanged)
    def frozen(self) -> bool:
        return self._frozen

    @pyqtSlot(bool)
    def setFrozen(self, value: bool) -> None:
        value = bool(value)
        if value == self._frozen:
            return
        # Reihenfolge ist wichtig: snapshot() liefert bei gesetztem _frozen
        # den ALTEN Schnappschuss zurueck. Erst holen, dann einfrieren.
        snap = self.snapshot().copy() if value else None
        self._frozen = value
        self._frozen_snapshot = snap
        if not value:
            self._trig_fired_at = None
            self._trig_capture_at = None
        self.frozenChanged.emit()

    @pyqtProperty(bool, notify=frozenChanged)
    def sharedScale(self) -> bool:
        return self._shared_scale

    @pyqtSlot(bool)
    def setSharedScale(self, value: bool) -> None:
        """Gemeinsame Y-Achse fuer alle Kurven statt einer eigenen je Kurve.

        Standard ist AUS: die Kanaele haben typischerweise voellig
        verschiedene Groessenordnungen (Akku 12 V neben einem Ballwinkel von
        0.3), auf einer gemeinsamen Achse waere davon nur eine Kurve
        erkennbar. Fuer den Vergleich zweier gleichartiger Werte (linker vs.
        rechter Motor) ist die gemeinsame Achse dagegen genau richtig.
        """
        value = bool(value)
        if value != self._shared_scale:
            self._shared_scale = value
            self.frozenChanged.emit()   # loest ein Neuzeichnen aus
            self.bufferChanged.emit()

    @pyqtProperty(str, notify=statsChanged)
    def statsText(self) -> str:
        return self._stats

    # ══════════════════════════════════════════════════════════════════════
    #  Trigger
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(bool, notify=triggerChanged)
    def triggerEnabled(self) -> bool:
        return self._trig_enabled

    @pyqtSlot(bool)
    def setTriggerEnabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._trig_enabled:
            return
        self._trig_enabled = value
        self._trig_capture_at = None
        self._last_trig_value = np.nan
        if value:
            self.setFrozen(False)      # scharf machen heisst: wieder mitlaufen
        self.triggerChanged.emit()

    @pyqtProperty(int, notify=triggerChanged)
    def triggerChannel(self) -> int:
        return self._trig_channel

    @pyqtSlot(int)
    def setTriggerChannel(self, idx: int) -> None:
        idx = max(0, min(MAX_FLOATS - 1, int(idx)))
        if idx != self._trig_channel:
            self._trig_channel = idx
            self._last_trig_value = np.nan
            self.triggerChanged.emit()

    @pyqtProperty(str, notify=triggerChanged)
    def triggerMode(self) -> str:
        return self._trig_mode

    @pyqtSlot(str)
    def setTriggerMode(self, mode: str) -> None:
        if mode in TRIGGER_MODES and mode != self._trig_mode:
            self._trig_mode = mode
            self._last_trig_value = np.nan
            self.triggerChanged.emit()

    @pyqtProperty("QVariantList", constant=True)
    def triggerModes(self):
        return [{"value": m, "label": TRIGGER_LABELS[m]} for m in TRIGGER_MODES]

    @pyqtProperty(float, notify=triggerChanged)
    def triggerLevel(self) -> float:
        return self._trig_level

    @pyqtSlot(float)
    def setTriggerLevel(self, value: float) -> None:
        if value != self._trig_level:
            self._trig_level = float(value)
            self.triggerChanged.emit()

    @pyqtProperty(float, notify=triggerChanged)
    def triggerDelta(self) -> float:
        return self._trig_delta

    @pyqtSlot(float)
    def setTriggerDelta(self, value: float) -> None:
        value = abs(float(value))
        if value != self._trig_delta:
            self._trig_delta = value
            self.triggerChanged.emit()

    @pyqtProperty(float, notify=triggerChanged)
    def triggerPostFraction(self) -> float:
        return self._trig_post

    @pyqtSlot(float)
    def setTriggerPostFraction(self, value: float) -> None:
        value = min(0.95, max(0.05, float(value)))
        if value != self._trig_post:
            self._trig_post = value
            self.triggerChanged.emit()

    @pyqtProperty(bool, notify=triggerChanged)
    def triggerMarkOnly(self) -> bool:
        """true = beim Ausloesen nur eine Marke setzen, nicht einfrieren.

        Damit laesst sich zaehlen und im Verlauf wiederfinden, wie oft eine
        Bedingung eingetreten ist, ohne dass die Anzeige jedes Mal stehen
        bleibt — bei einem seltenen Aussetzer will man einfrieren, bei einem
        regelmaessigen Ereignis nur die Marken."""
        return self._trig_auto_rearm

    @pyqtSlot(bool)
    def setTriggerMarkOnly(self, value: bool) -> None:
        value = bool(value)
        if value != self._trig_auto_rearm:
            self._trig_auto_rearm = value
            self._trig_capture_at = None
            self.triggerChanged.emit()

    @pyqtProperty(int, notify=triggerChanged)
    def triggerCount(self) -> int:
        return self._trig_count

    @pyqtProperty(bool, notify=triggerChanged)
    def triggerArmed(self) -> bool:
        """Scharf und wartend (noch nicht ausgeloest)."""
        return self._trig_enabled and not self._frozen

    @pyqtSlot()
    def rearmTrigger(self) -> None:
        """Nach einer Ausloesung wieder scharf machen."""
        self._trig_capture_at = None
        self._trig_fired_at = None
        self._last_trig_value = np.nan
        self.setFrozen(False)
        self.triggerChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Marken
    # ══════════════════════════════════════════════════════════════════════

    def add_marker(self, text: str, level: int = 0, at: int | None = None) -> None:
        """Ereignis als senkrechte Marke eintragen.

        `at` ist der ABSOLUTE Sample-Index, an dem die Marke stehen soll.
        Ohne Angabe gilt `self._total` — der Index des naechsten Samples, das
        geschrieben wird. Das ist fuer Ereignisse aus dem Aux-Uplink genau
        richtig: die werden im Poll-Durchlauf VOR append_block() verteilt,
        die Marke sitzt damit am Anfang des gleich eintreffenden Blocks.

        Der Trigger ruft dagegen NACH append_block() auf und muss seine
        Ausloesestelle mitgeben (siehe _evaluate_trigger).
        """
        idx = self._total if at is None else int(at)
        self._markers.append((idx, str(text)[:32], int(level)))
        # Alles, was aus dem Ring herausgelaufen ist, kann nie wieder sichtbar
        # werden -> wegwerfen, damit die Liste im Dauerbetrieb nicht waechst.
        cutoff = self._total - self._cap
        if len(self._markers) > 64:
            self._markers = [m for m in self._markers if m[0] > cutoff][-64:]
        self.markersChanged.emit()

    def visible_markers(self, points: int) -> list[tuple[float, str, int]]:
        """Marken im sichtbaren Fenster als (0..1-Position, Text, Level)."""
        count = min(points, self._filled)
        if count <= 1:
            return []
        # Sichtbar sind die Samples first .. self._total - 1; der letzte davon
        # liegt am rechten Rand. Ohne das -1 kam eine gerade erst gesetzte
        # Marke auf Position count/(count-1) > 1 heraus und wurde damit
        # ausserhalb der Zeichenflaeche gezeichnet, also gar nicht.
        last = self._total - 1
        first = last - (count - 1)
        out = []
        for abs_idx, text, level in self._markers:
            if abs_idx < first:
                continue
            pos = (min(abs_idx, last) - first) / (count - 1)
            out.append((pos, text, level))
        return out

    @pyqtSlot()
    def clearMarkers(self) -> None:
        self._markers.clear()
        self.markersChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Daten
    # ══════════════════════════════════════════════════════════════════════

    @pyqtSlot()
    def clearBuffer(self) -> None:
        self._ring.fill(np.nan)
        self._write = 0
        self._filled = 0
        self._total = 0
        self._markers.clear()
        self._frozen_snapshot = None
        self._trig_capture_at = None
        self._trig_fired_at = None
        self._last_trig_value = np.nan
        self._stats = "—"
        self.statsChanged.emit()
        self.markersChanged.emit()
        self.bufferChanged.emit()

    def append_block(self, block: np.ndarray) -> None:
        """Einen ganzen Paketblock uebernehmen.

        block: 2D float32-Array (Samples x Kanaele). Fehlende Kanaele am
        rechten Rand sind erlaubt — sie werden zu NaN.
        """
        if block.ndim != 2 or block.shape[0] == 0:
            return
        if self._frozen:
            return

        n_new, width = block.shape
        # Mehr Samples als der Ring fasst kann nur bei einem massiven
        # GUI-Hänger auftreten; dann zaehlt ohnehin nur der jüngste Teil.
        if n_new > self._cap:
            block = block[-self._cap:]
            n_new = self._cap

        # ── Auswahl der dargestellten Kanaele, vektorisiert ───────────────
        n_curves = len(self._channels)
        cols = np.full((n_curves, n_new), np.nan, dtype=np.float32)
        idx = np.fromiter(self._channels, dtype=np.intp, count=n_curves)
        in_range = idx < width
        if np.any(in_range):
            cols[in_range] = block[:, idx[in_range]].T

        # ── In den Ring schreiben (mit Umbruch) ───────────────────────────
        start = self._write
        end = start + n_new
        if end <= self._cap:
            self._ring[:n_curves, start:end] = cols
            if n_curves < MAX_CURVES:
                self._ring[n_curves:, start:end] = np.nan
        else:
            head = self._cap - start
            self._ring[:n_curves, start:] = cols[:, :head]
            self._ring[:n_curves, :end - self._cap] = cols[:, head:]
            if n_curves < MAX_CURVES:
                self._ring[n_curves:, start:] = np.nan
                self._ring[n_curves:, :end - self._cap] = np.nan

        self._write = end % self._cap
        self._filled = min(self._filled + n_new, self._cap)
        self._total += n_new

        if self._trig_enabled:
            self._evaluate_trigger(block, width, n_new)

        self._update_stats()
        self.bufferChanged.emit()

    def _evaluate_trigger(self, block: np.ndarray, width: int, n_new: int) -> None:
        """Trigger auf dem gerade eingetroffenen Block auswerten.

        Komplett vektorisiert: die Bedingung wird als Boolean-Array ueber
        alle neuen Samples ausgewertet, die Ausloesestelle ist dann der erste
        True-Eintrag. Eine Python-Schleife ueber die Samples waere bei
        100 Hz zwar auch machbar, aber unnoetig.
        """
        # Steht die Aufzeichnung nach einer Ausloesung noch offen?
        if self._trig_capture_at is not None:
            if self._total >= self._trig_capture_at:
                self._trig_capture_at = None
                self._frozen = True
                self._frozen_snapshot = self.snapshot().copy()
                self.frozenChanged.emit()
                self.triggerChanged.emit()
            return

        chn = self._trig_channel
        if chn >= width:
            return
        series = block[:, chn].astype(np.float32, copy=False)
        prev = self._last_trig_value
        # Letzter Wert des VORHERIGEN Blocks vorangestellt, damit eine Flanke
        # genau an der Blockgrenze nicht verloren geht.
        extended = np.concatenate(([prev], series))
        lvl = self._trig_level
        mode = self._trig_mode

        if mode == "above":
            hit = series > lvl
        elif mode == "below":
            hit = series < lvl
        elif mode == "rising":
            hit = (extended[:-1] <= lvl) & (series > lvl)
        elif mode == "falling":
            hit = (extended[:-1] >= lvl) & (series < lvl)
        elif mode == "change":
            hit = np.abs(np.diff(extended)) >= self._trig_delta
        elif mode == "outside":
            hit = np.abs(series - lvl) > self._trig_delta
        else:
            hit = np.zeros(series.shape, dtype=bool)

        # NaN-Vergleiche liefern False, das ist genau richtig; nur bei
        # "rising"/"falling"/"change" muss der noch unbekannte Vorgaengerwert
        # (NaN beim allerersten Block) die Ausloesung unterdruecken.
        self._last_trig_value = float(series[-1]) if series.size else prev

        where = np.flatnonzero(hit)
        if where.size == 0:
            return

        fire_offset = int(where[0])
        self._trig_fired_at = self._total - n_new + fire_offset
        self._trig_count += 1
        # Die Marke gehoert an die AUSLOESESTELLE, nicht an das Ende des
        # gerade verarbeiteten Blocks: add_marker() laeuft hier nach
        # append_block(), self._total zeigt also schon hinter den Block.
        self.add_marker(f"Trigger {self._trig_count}", 1, at=self._trig_fired_at)
        if not self._trig_auto_rearm:
            post = int(self._points * self._trig_post)
            self._trig_capture_at = self._trig_fired_at + max(1, post)
        self.triggerChanged.emit()

    def snapshot(self, points: int | None = None) -> np.ndarray:
        """Die letzten `points` Samples aller aktiven Kurven, in Zeitreihenfolge.

        Rueckgabe: 2D-Array (Kurven x Samples). Bei Umbruch im Ring wird
        genau einmal kopiert (np.concatenate); sonst ist es ein View.
        """
        if self._frozen and self._frozen_snapshot is not None:
            return self._frozen_snapshot
        n_curves = len(self._channels)
        count = min(points if points is not None else self._points, self._filled)
        if count <= 0:
            return np.empty((n_curves, 0), dtype=np.float32)
        start = (self._write - count) % self._cap
        if start + count <= self._cap:
            return self._ring[:n_curves, start:start + count]
        return np.concatenate(
            (self._ring[:n_curves, start:], self._ring[:n_curves, :start + count - self._cap]),
            axis=1,
        )

    def live_snapshot(self) -> np.ndarray:
        """Immer der LAUFENDE Verlauf, auch wenn eingefroren ist — so bleibt
        im eingefrorenen Bild sichtbar, was inzwischen weiterlaeuft."""
        n_curves = len(self._channels)
        count = min(self._points, self._filled)
        if count <= 0:
            return np.empty((n_curves, 0), dtype=np.float32)
        start = (self._write - count) % self._cap
        if start + count <= self._cap:
            return self._ring[:n_curves, start:start + count]
        return np.concatenate(
            (self._ring[:n_curves, start:], self._ring[:n_curves, :start + count - self._cap]),
            axis=1,
        )

    def frozen_snapshot(self) -> np.ndarray | None:
        return self._frozen_snapshot

    def _update_stats(self) -> None:
        data = self.snapshot()
        if data.shape[1] == 0 or not np.any(np.isfinite(data)):
            return
        row = data[0]
        if not np.any(np.isfinite(row)):
            return
        name = self._names[self._channels[0]] if self._channels else "—"
        unit = self._units.get(self._channels[0], "")
        suffix = f" {unit}" if unit else ""
        finite = row[np.isfinite(row)]
        self._stats = (
            f"{name}:  Min {float(np.min(finite)):.4g}{suffix}  |  "
            f"Max {float(np.max(finite)):.4g}{suffix}  |  "
            f"Aktuell {float(finite[-1]):.4g}{suffix}  |  "
            f"σ {float(np.std(finite)):.4g}"
        )
        if len(self._channels) > 1:
            self._stats += f"   (+{len(self._channels) - 1} weitere Kurven)"
        self.statsChanged.emit()


# ══════════════════════════════════════════════════════════════════════════
#  PlotCanvas — QQuickPaintedItem
# ══════════════════════════════════════════════════════════════════════════

class PlotCanvas(QQuickPaintedItem):
    plotBridgeChanged = pyqtSignal()

    _GRID_COLOR   = QColor(255, 255, 255, 25)
    _BG_COLOR     = QColor("#1a1a1a")
    _MARKER_COLOR = (QColor(120, 200, 255, 160), QColor(255, 190, 60, 200),
                     QColor(255, 90, 70, 220))

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._bridge: PlotBridge | None = None
        self.setAntialiasing(True)

    def getPlotBridge(self):
        return self._bridge

    def setPlotBridge(self, bridge: PlotBridge) -> None:
        if self._bridge is bridge:
            return
        if self._bridge is not None:
            # Beim Abbau der Anwendung kann die Bruecke auf der C++-Seite
            # bereits weg sein, waehrend QML die Property noch einmal
            # zuruecksetzt. Der Zugriff auf ihre Signale wirft dann
            #     RuntimeError: wrapped C/C++ object ... has been deleted
            # und PyQt macht daraus in einem Slot ein abort(). Abmelden ist zu
            # diesem Zeitpunkt ohnehin gegenstandslos — das Objekt ist fort.
            try:
                for sig in (self._bridge.bufferChanged, self._bridge.frozenChanged,
                            self._bridge.channelsChanged, self._bridge.markersChanged,
                            self._bridge.triggerChanged):
                    sig.disconnect(self.update)
            except (RuntimeError, TypeError):
                pass
        self._bridge = bridge
        if bridge is not None:
            for sig in (bridge.bufferChanged, bridge.frozenChanged,
                        bridge.channelsChanged, bridge.markersChanged,
                        bridge.triggerChanged):
                sig.connect(self.update)
        self.plotBridgeChanged.emit()
        self.update()

    plotBridge = pyqtProperty(QObject, fget=getPlotBridge, fset=setPlotBridge,
                               notify=plotBridgeChanged)

    # ── Zeichnen ──────────────────────────────────────────────────────────
    def paint(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(QRectF(0, 0, w, h), self._BG_COLOR)

        painter.setPen(QPen(self._GRID_COLOR, 1))
        for i in range(1, 5):
            y = h * i / 5
            painter.drawLine(0, int(y), int(w), int(y))
        for i in range(1, 8):
            x = w * i / 8
            painter.drawLine(int(x), 0, int(x), int(h))

        b = self._bridge
        if b is None:
            return

        data = b.snapshot()
        margin = h * 0.08

        if b.sharedScale and data.size and np.any(np.isfinite(data)):
            lo = float(np.nanmin(data))
            hi = float(np.nanmax(data))
            common = (lo, hi)
        else:
            common = None

        for row in range(data.shape[0]):
            color = QColor(CURVE_COLORS[row % len(CURVE_COLORS)])
            self._draw_curve(painter, data[row], color, w, h, margin, common,
                              dashed=False)

        # Im eingefrorenen Bild zusaetzlich der weiterlaufende Verlauf der
        # ersten Kurve, damit man sieht, dass die Anlage noch lebt.
        if b.frozen:
            live = b.live_snapshot()
            if live.shape[0] > 0:
                pen_color = QColor(CURVE_COLORS[0])
                pen_color.setAlpha(90)
                self._draw_curve(painter, live[0], pen_color, w, h, margin, common,
                                  dashed=True)

        self._draw_markers(painter, b, w, h)

    def _draw_markers(self, painter: QPainter, b: PlotBridge, w: float, h: float) -> None:
        markers = b.visible_markers(b.pointsCount)
        if not markers:
            return
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        for pos, text, level in markers:
            x = w * pos
            color = self._MARKER_COLOR[min(level, len(self._MARKER_COLOR) - 1)]
            pen = QPen(color, 1.2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            painter.setPen(QPen(color, 1))
            # Beschriftung nach links kippen, wenn sie sonst rechts hinausragt
            tw = painter.fontMetrics().horizontalAdvance(text) + 6
            tx = x + 4 if x + tw < w else x - tw
            painter.drawText(QPointF(tx, 14), text)

    @staticmethod
    def _draw_curve(painter: QPainter, series: np.ndarray, color: QColor,
                     w: float, h: float, margin: float,
                     common: tuple[float, float] | None, dashed: bool) -> None:
        n = series.shape[0]
        if n < 2:
            return
        finite = np.isfinite(series)
        if not np.any(finite):
            return

        if common is not None:
            mn, mx = common
        else:
            mn = float(np.nanmin(series))
            mx = float(np.nanmax(series))
        span = (mx - mn) or 1.0

        # Komplette Koordinatenumrechnung in zwei Array-Operationen statt in
        # einer Python-Schleife ueber bis zu 600 Punkte je Kurve und Frame.
        xs = np.linspace(0.0, w, n, dtype=np.float64)
        ys = (h - 2 * margin) * (1.0 - (series.astype(np.float64) - mn) / span) + margin

        pen = QPen(color, 1.8)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        path = QPainterPath()
        pen_down = False
        for i in range(n):
            if not finite[i]:
                pen_down = False          # Luecke: Linie unterbrechen
                continue
            if pen_down:
                path.lineTo(xs[i], ys[i])
            else:
                path.moveTo(xs[i], ys[i])
                pen_down = True
        painter.drawPath(path)
