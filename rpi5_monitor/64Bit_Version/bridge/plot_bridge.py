"""
bridge/plot_bridge.py — Tab 2 (Live-Plotter), Daten- und Logik-Schicht
======================================================================

Zwei Verantwortlichkeiten, sauber getrennt:

  PlotBridge  — Datenhaltung + Trigger + Marken + Performance-Wächter.
                KEINE Zeichenlogik mehr. Die Darstellung übernimmt
                bridge/plot_host.py (PyQtGraphHost), das diese Brücke
                über die Methode get_plot_arrays() mit NumPy-Arrays
                füttert.

────────────────────────────────────────────────────────────────────────────
WARUM AUSSCHLIESSLICH NUMPY
────────────────────────────────────────────────────────────────────────────
Bei 100 Hz, zwei Nodes und bis zu acht gleichzeitig dargestellten Kanälen
gehen pro Sekunde einige tausend Werte durch diesen Code — und zwar im
GUI-Thread, der gleichzeitig die Oberfläche zeichnet und den 100-Hz-Takt der
Fernsteuerung hält. Jede Python-Schleife über Einzelwerte kostet hier
unmittelbar Reaktionszeit der Fernsteuerung.

Deshalb: EIN vorab angelegter 2D-Ringpuffer (Kurven x Samples, float32), in
den blockweise geschrieben wird. Kein deque, keine Listen, kein Umkopieren
pro Wert. Auch Trigger-Auswertung und Statistik laufen vektorisiert über
ganze Blöcke.

────────────────────────────────────────────────────────────────────────────
PYQTGRAPH STATT QPAINTER
────────────────────────────────────────────────────────────────────────────
Die ursprüngliche Zeichenroutine (PlotCanvas) baute pro Frame und Kurve eine
QPainterPath PUNKTWEISE in einer Python-Schleife auf — bis ~8000
Pfad-Operationen pro Frame bei 20 fps. Genau das hat den Raspberry Pi 4
(2 GB) überlastet. Stattdessen liefert diese Brücke fertige NumPy-Arrays;
pyqtgraph zeichnet die Polylinien in C++ und kann bei Bedarf downsampeln.
Den Rest (Überlastung erkennen und den Plotter abschalten) macht der
PerfWatchdog.

────────────────────────────────────────────────────────────────────────────
TRIGGER (Oszilloskop-Prinzip)
────────────────────────────────────────────────────────────────────────────
Ein Trigger friert den Verlauf im Moment eines Ereignisses ein, statt dass man
danebensitzen und im richtigen Augenblick „Einfrieren“ drücken muss. Die
Aufzeichnung läuft im Ring immer mit; löst der Trigger aus, wird noch
`postFraction` der Fensterbreite weiter aufgezeichnet und dann eingefroren.
"""
from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, pyqtProperty

import app_settings
from config import MAX_FLOATS, PLOT_BUFFER_SIZE, VARIABLE_NAMES
from bridge.perf_watchdog import PerfWatchdog

log = logging.getLogger("bridge.plot")

# Alles hier kommt aus settings.json -> "plotter" (siehe app_settings.py).
# Gelesen wird beim IMPORT: der Ringpuffer wird damit dimensioniert, eine
# Aenderung wirkt deshalb erst beim naechsten Start.

# Bis zu so viele Kurven gleichzeitig. Mehr wird unlesbar, und der Ringpuffer
# ist mit dieser Zahl fest dimensioniert (8 x 1000 x 4 B = 32 kB).
MAX_CURVES = max(1, int(app_settings.get("plotter.maxCurves", 8)))

# Gut unterscheidbar auch auf einem hellen Hintergrund im Freien.
CURVE_COLORS = list(app_settings.get("plotter.curveColors")
                    or app_settings.DEFAULTS["plotter"]["curveColors"])

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

# Performance-Schwellen (settings.json -> "plotter"). Eine falsche Zahl hier
# fängt app_settings ab und behält den Standardwert.
_PERF = {
    "measureMs":       float(app_settings.get("plotter.perfMeasureMs", 250)),
    "warnStallMs":     float(app_settings.get("plotter.perfWarnStallMs", 35.0)),
    "disableStallMs":  float(app_settings.get("plotter.perfDisableStallMs", 80.0)),
    "streak":          int(app_settings.get("plotter.perfStreak", 5)),
    "renderDisableMs": float(app_settings.get("plotter.renderDisableMs", 80.0)),
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
    # Neu: Plotter ein/aus, Überlastung, Warntext
    enabledChanged       = pyqtSignal()
    overloadedChanged    = pyqtSignal()
    perfMessageChanged   = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cap = int(PLOT_BUFFER_SIZE)
        self._points = self._clamp_points(
            int(app_settings.get("plotter.defaultPoints", 500)))

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
        self._markers: list[tuple[int, str, int]] = []   # (abs_index, text, level)

        # ── Ein/Aus & Überlastung ──────────────────────────────────────────
        self._enabled = True
        self._overloaded = False
        self._perf_message = ""
        self._plot_active = False      # liefert der Host (sichtbar + ein)
        self._render_ms = 0.0         # gleitender Max. eines Plot-Durchlaufs
        self._render_calls = 0        # Warmup-Zähler für note_render

        # ── Performance-Wächter ────────────────────────────────────────────
        self._watchdog = PerfWatchdog(
            self,
            measure_ms=_PERF["measureMs"],
            warn_stall_ms=_PERF["warnStallMs"],
            disable_stall_ms=_PERF["disableStallMs"],
            streak=_PERF["streak"],
        )
        self._watchdog.overload.connect(self._on_overload)
        self._watchdog.warning.connect(self._on_warning)
        self._watchdog.start()

    # ══════════════════════════════════════════════════════════════════════
    #  Ein / Aus / Überlastung
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(bool, notify=enabledChanged)
    def enabled(self) -> bool:
        return self._enabled

    @pyqtSlot(bool)
    def setEnabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._enabled and (value or not self._overloaded):
            return
        self._enabled = value
        if value:
            # Wieder einschalten: Überlastung zurücksetzen und Wächter neu
            # starten. Ist die Ursache nicht behoben (zu viele Kurven),
            # schaltet der Wächter von selbst wieder ab.
            self._overloaded = False
            self._perf_message = ""
            self._watchdog.reset()
            self._watchdog.set_active(self._plot_active)
        else:
            self._watchdog.set_active(False)
        self.enabledChanged.emit()
        self.overloadedChanged.emit()
        self.perfMessageChanged.emit()

    @pyqtSlot()
    def retryPlotter(self) -> None:
        """Vom Warnbanner aufgerufen: Plotter erneut versuchen."""
        self.setEnabled(True)

    @pyqtProperty(bool, notify=overloadedChanged)
    def overloaded(self) -> bool:
        return self._overloaded

    @pyqtProperty(str, notify=perfMessageChanged)
    def perfMessage(self) -> str:
        return self._perf_message

    def _on_overload(self, reason: str) -> None:
        """Vom Wächter: nicht genug Rechenleistung -> Plotter aus."""
        if self._overloaded:
            return
        self._overloaded = True
        self._enabled = False
        self._plot_active = False
        self._watchdog.set_active(False)
        self._perf_message = (
            "⚠ Zu wenig Rechenleistung — Plotter ausgeschaltet. "
            "Kurven reduzieren oder „Erneut versuchen“. "
            + (f"({reason})" if reason else "")
        )
        log.warning("Plotter wegen Überlastung deaktiviert: %s", reason)
        self.overloadedChanged.emit()
        self.enabledChanged.emit()
        self.perfMessageChanged.emit()

    def _on_warning(self, msg: str) -> None:
        if self._overloaded:
            return
        self._perf_message = msg
        self.perfMessageChanged.emit()

    def setPlotActive(self, active: bool) -> None:
        """Host meldet, ob der Plotter gerade sichtbar und eingeschaltet ist.

        Nur dann darf der Plotter Last erzeugen — und nur dann wertet der
        Wächter die Event-Loop-Last aus (sonst würde fremde Last dem Plotter
        angelastet).
        """
        active = bool(active) and self._enabled and not self._overloaded
        if active == self._plot_active:
            return
        self._plot_active = active
        self._watchdog.set_active(active)

    def note_render(self, dt_ms: float) -> None:
        """Host meldet die Dauer eines Plot-Durchlaufs (setData + evtl. Grab).

        Ein einzelner Durchlauf, der das Zeitbudget sprengt, ist ein
        sicheres Zeichen für Überlastung — unabhängig vom groben
        Event-Loop-Stall misst der Wächter ohnehin mit.
        """
        # Gleitender Max: nur sehr langsame Einzelbilder zählen.
        self._render_ms = max(self._render_ms * 0.8, dt_ms)
        # Warmup: die ersten Durchläufe nach dem Start/Tab-Wechsel dürfen
        # einmalig teurer sein (Widget wird erstmals layoutet/gezeichnet) —
        # sonst würde ein einziger unkritischer Ruckler sofort abschalten.
        self._render_calls += 1
        if self._render_calls <= 20:
            return
        if (not self._overloaded and self._enabled
                and dt_ms >= _PERF["renderDisableMs"]):
            self._on_overload(
                f"Ein Plot-Durchlauf dauerte {dt_ms:.0f} ms "
                f"(Budget {_PERF['renderDisableMs']:.0f} ms).")

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

    def _clamp_points(self, n: int) -> int:
        """Auf denselben Bereich begrenzen, den auch das Drehfeld in QML
        anbietet (settings.json -> "ranges.plotPoints") — zusaetzlich
        gedeckelt durch den tatsaechlichen Ringpuffer, denn mehr Punkte, als
        gespeichert werden, kann niemand anzeigen."""
        rng = app_settings.get("ranges.plotPoints",
                                app_settings.DEFAULTS["ranges"]["plotPoints"])
        lo = max(1, int(rng["min"]))
        hi = min(self._cap, int(rng["max"]))
        return max(lo, min(hi, int(n)))

    @pyqtSlot(int)
    def setPointsCount(self, n: int) -> None:
        n = self._clamp_points(n)
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
            # Loest ein Neuzeichnen aus (PyQtGraphHost liest sharedScale neu).
            self.frozenChanged.emit()
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
        # Grenzen wie im Drehfeld: settings.json -> "ranges.plotTriggerPost".
        rng = app_settings.get("ranges.plotTriggerPost",
                                app_settings.DEFAULTS["ranges"]["plotTriggerPost"])
        value = min(rng["max"], max(rng["min"], float(value)))
        if value != self._trig_post:
            self._trig_post = value
            self.triggerChanged.emit()

    @pyqtProperty(bool, notify=triggerChanged)
    def triggerMarkOnly(self) -> bool:
        """true = beim Ausloesen nur eine Marke setzen, nicht einfrieren.

        Damit laesst sich zaehlen und im Verlauf wiederfinden, wie oft eine
        Bedingung eingetreten ist, ohne dass die Anzeige jedes Mal stehen
        bleibt — bei einem seltenen Aussetzer will man einfrieren, bei einem
        regelmaessigen Ereignis nur die Marken.
        """
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
        # liegt am rechten Rand.
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
        True-Eintrag.
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
        im eingefrorenen Bild sichtbar, was inzwischen weiterlaeuft.
        """
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

    # ══════════════════════════════════════════════════════════════════════
    #  Ausgabe für die Darstellung (pyqtgraph)
    # ══════════════════════════════════════════════════════════════════════

    def get_plot_arrays(self, shared_scale: bool | None = None
                        ) -> list[tuple[np.ndarray, np.ndarray]]:
        """Bereitet die sichtbaren Kurven als (x, y)-NumPy-Paare auf.

        x ist der Sample-Index (0..n-1); y sind die Werte als float64.

        Bei EINZELSKALA (shared_scale=False) wird jede Kurve auf den eigenen
        Wertebereich normiert (0..1), damit Kanaele völlig verschiedener
        Groessenordnung (12 V Akku neben 0.3 Ballwinkel) gleichzeitig
        sichtbar sind. Bei GEMEINSAMER SKALA werden die Rohwerte geliefert
        und pyqtgraph auto-skaliert die Y-Achse.
        """
        if shared_scale is None:
            shared_scale = self._shared_scale
        data = self.snapshot()
        n = data.shape[1]
        if n == 0:
            return []
        xs = np.arange(n, dtype=np.float64)
        out: list[tuple[np.ndarray, np.ndarray]] = []
        if shared_scale:
            for row in range(data.shape[0]):
                out.append((xs, data[row].astype(np.float64)))
        else:
            for row in range(data.shape[0]):
                series = data[row].astype(np.float64)
                finite = np.isfinite(series)
                if finite.any():
                    mn = float(series[finite].min())
                    mx = float(series[finite].max())
                    span = (mx - mn) or 1.0
                    ys = (series - mn) / span
                else:
                    ys = np.zeros(n, dtype=np.float64)
                out.append((xs, ys))
        return out

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
