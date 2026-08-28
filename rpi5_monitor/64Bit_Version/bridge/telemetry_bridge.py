"""
bridge/telemetry_bridge.py — Tab 1 (Live-Tabelle) + zentrale Live-Werte
==========================================================================
Migrationsplan Abschnitt 4.3: Das bestehende QAbstractTableModel wird
fast unverändert übernommen — es bekommt lediglich `roleNames()` +
rollenbasierten `data()`-Zugriff dazu, damit Qt Quick's `TableView`
es konsumieren kann (Spalten-Header-Zugriff wie im alten `QTableView`
gibt es in QML nicht, dort wird pro Delegate über Rollen gebunden).

Zusätzlich stellt `TelemetryBridge.latestValues` das komplette aktuelle
Werte-Array als reaktive Property bereit — das brauchen SystemView.qml
(Overlays/Gauges) und ParamsView nicht, aber es ist der zentrale Ort,
über den jede QML-Seite an "den letzten Datenpunkt" herankommt, ohne
selbst eine Queue lesen zu müssen.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject,
    pyqtSignal, pyqtProperty, pyqtSlot,
)

from config import MAX_FLOATS, VARIABLE_NAMES


# ══════════════════════════════════════════════════════════════════════════
#  TelemetryTableModel — für QML TableView
# ══════════════════════════════════════════════════════════════════════════

class TelemetryTableModel(QAbstractTableModel):
    """Wie gui/tab_table.py::TelemetryTableModel, aber mit benannten Rollen
    für den Zugriff aus QML-Delegates (`model.varName`, `model.current`, ...)."""

    NameRole    = Qt.ItemDataRole.UserRole + 1
    CurrentRole = Qt.ItemDataRole.UserRole + 2
    MinRole     = Qt.ItemDataRole.UserRole + 3
    MaxRole     = Qt.ItemDataRole.UserRole + 4
    DeltaRole   = Qt.ItemDataRole.UserRole + 5
    ColorRole   = Qt.ItemDataRole.UserRole + 6
    UnitRole    = Qt.ItemDataRole.UserRole + 7
    ChannelRole = Qt.ItemDataRole.UserRole + 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        n = MAX_FLOATS
        self._names    = [VARIABLE_NAMES.get(i, f"Var_{i:03d}") for i in range(n)]
        self._current  = np.zeros(n, dtype=np.float32)
        self._min      = np.full(n,  np.inf, dtype=np.float32)
        self._max      = np.full(n, -np.inf, dtype=np.float32)
        self._n_active = 0
        # Zeile -> Kanalindex. Der Filter wird BEWUSST hier im Modell
        # ausgewertet und nicht per `visible: false` im QML-Delegate: eine
        # TableView reserviert die Höhe unsichtbarer Zeilen weiterhin, die
        # gefilterte Liste war deshalb voller Lücken.
        self._visible: list[int] = []
        self._filter = ""
        # Einheit je Kanal ("V", "cm", ...), vom Teensy gemeldet.
        # Nur ein Anzeige-Zusatz, aendert nie einen Wert.
        self._units: dict[int, str] = {}

    # ── Filter ───────────────────────────────────────────────────────────
    def _matches(self, ch: int) -> bool:
        # Auch die Kanalnummer durchsuchbar: "42" findet Kanal 42, auch
        # wenn er noch "Var_042" heisst.
        return self._filter in self._names[ch].lower() or self._filter == str(ch)

    def _rebuild_visible(self) -> list[int]:
        if not self._filter:
            return list(range(self._n_active))
        return [i for i in range(self._n_active) if self._matches(i)]

    def set_filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        if text == self._filter:
            return
        self._filter = text
        self.beginResetModel()
        self._visible = self._rebuild_visible()
        self.endResetModel()

    @property
    def visible_count(self) -> int:
        return len(self._visible)

    @property
    def active_count(self) -> int:
        return self._n_active

    # ── QAbstractTableModel-Interface ────────────────────────────────────
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        # QML TableView erzeugt EIN Delegate pro (row, col) — da wir die
        # fünf "Spalten" (Variable/Aktuell/Min/Max/Delta) als Rollen
        # innerhalb eines einzigen Zeilen-Delegates rendern (siehe
        # TelemetryView.qml), bleibt das Modell hier bewusst einspaltig.
        return 1

    def roleNames(self):
        return {
            self.NameRole:    b"varName",
            self.CurrentRole: b"current",
            self.MinRole:     b"minVal",
            self.MaxRole:     b"maxVal",
            self.DeltaRole:   b"delta",
            self.ColorRole:   b"valueColor",
            self.UnitRole:    b"unit",
            self.ChannelRole: b"channel",
        }

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._visible):
            return None
        ch = self._visible[row]

        if role == self.NameRole:
            return self._names[ch]
        if role == self.ChannelRole:
            return ch
        if role == self.UnitRole:
            return self._units.get(ch, "")
        if role == self.CurrentRole:
            return float(self._current[ch])
        if role == self.MinRole:
            v = self._min[ch]
            return None if np.isinf(v) else float(v)
        if role == self.MaxRole:
            v = self._max[ch]
            return None if np.isinf(v) else float(v)
        if role == self.DeltaRole:
            mn, mx = self._min[ch], self._max[ch]
            if np.isinf(mn) or np.isinf(mx):
                return None
            return float(mx - mn)
        if role == self.ColorRole:
            v = float(self._current[ch])
            if v > 0:
                return "#4ec9b0"
            if v < 0:
                return "#f48771"
            return "#d4d4d4"
        return None

    # ── Daten-Update (identische Logik zu gui/tab_table.py) ─────────────
    def update_data(self, values: np.ndarray) -> None:
        n = min(len(values), MAX_FLOATS)
        row_count_changed = (n != self._n_active)

        if row_count_changed:
            self.beginResetModel()
            self._n_active = n
            self._visible = self._rebuild_visible()

        self._current[:n] = values[:n]
        np.minimum(self._min[:n], values[:n], out=self._min[:n])
        np.maximum(self._max[:n], values[:n], out=self._max[:n])

        if row_count_changed:
            self.endResetModel()
        else:
            self._emit_value_change()

    def _emit_value_change(self) -> None:
        rows = len(self._visible)
        if rows <= 0:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(rows - 1, 0),
            [self.CurrentRole, self.MinRole, self.MaxRole,
             self.DeltaRole, self.ColorRole],
        )

    @pyqtSlot()
    def clear_stats(self) -> None:
        self._current[:] = 0.0
        self._min[:] = np.inf
        self._max[:] = -np.inf
        self._emit_value_change()

    def set_units(self, units: dict[int, str]) -> None:
        """Einheiten aus dem Teensy-Deskriptor uebernehmen."""
        if units == self._units:
            return
        self._units = dict(units)
        if self._visible:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._visible) - 1, 0),
                [self.UnitRole],
            )

    def set_names(self, names: dict[int, str]) -> None:
        """Aktualisiert Kanalnamen live (z. B. nach Empfang des Teensy-
        Namens-Deskriptors) — Indizes ohne Eintrag behalten ihren bisherigen
        (Fallback-)Namen."""
        if not names:
            return
        changed = False
        for i, name in names.items():
            if 0 <= i < len(self._names) and self._names[i] != name:
                self._names[i] = name
                changed = True
        if not changed:
            return
        if self._filter:
            # Die Namen bestimmen, welche Zeilen sichtbar sind -> neu aufbauen.
            self.beginResetModel()
            self._visible = self._rebuild_visible()
            self.endResetModel()
        elif self._visible:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._visible) - 1, 0),
                [self.NameRole],
            )


# ══════════════════════════════════════════════════════════════════════════
#  TelemetryBridge — Fassade für Tab 1 + geteilte Live-Werte
# ══════════════════════════════════════════════════════════════════════════

class TelemetryBridge(QObject):
    valuesChanged      = pyqtSignal()
    countsChanged      = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table_model = TelemetryTableModel(self)
        self._latest: list[float] = []
        self._active_channels = 0
        self._visible_channels = 0

    # ── Property: kompletter letzter Werte-Vektor, für Overlays/Gauges ───
    @pyqtProperty("QVariantList", notify=valuesChanged)
    def latestValues(self):
        return self._latest

    @pyqtProperty(int, notify=countsChanged)
    def activeChannels(self):
        """Anzahl vom Teensy gelieferter Kanäle. Als Property (statt eines
        `telemetryModel.rowCount()`-Aufrufs im QML-Text) — ein Methodenaufruf
        in einem Binding wird nie neu ausgewertet, die Anzeige stand deshalb
        dauerhaft auf 0."""
        return self._active_channels

    @pyqtProperty(int, notify=countsChanged)
    def visibleChannels(self):
        """Anzahl der nach Filterung sichtbaren Kanäle."""
        return self._visible_channels

    @pyqtSlot(str)
    def setFilter(self, text: str) -> None:
        """Filtert die Kanaltabelle nach Namensbestandteil (aus QML)."""
        self.table_model.set_filter(text)
        self._sync_counts()

    @pyqtSlot(int, result=float)
    def valueFor(self, channel: int) -> float:
        """Bequemer Einzelwert-Zugriff aus QML (z. B. Gauge-Bindings),
        wenn ein Binding an `latestValues[idx]` unhandlich wäre."""
        if 0 <= channel < len(self._latest):
            return float(self._latest[channel])
        return 0.0

    # ── Vom AppBridge-Poll-Loop aufgerufen ────────────────────────────────
    def update_data(self, values: np.ndarray) -> None:
        self.table_model.update_data(values)
        # ndarray.tolist() konvertiert in C statt über eine Python-Schleife
        # mit 200 float()-Aufrufen pro Durchlauf (20x/s = 4000 Aufrufe/s,
        # alle im GUI-Thread, der parallel den 100-Hz-Sendetimer bedienen muss).
        self._latest = values.tolist()
        self.valuesChanged.emit()
        self._sync_counts()

    def _sync_counts(self) -> None:
        active = self.table_model.active_count
        visible = self.table_model.visible_count
        if active == self._active_channels and visible == self._visible_channels:
            return
        self._active_channels = active
        self._visible_channels = visible
        self.countsChanged.emit()

    @pyqtSlot()
    def clear_stats(self) -> None:
        self.table_model.clear_stats()

    def set_names(self, names: dict[int, str]) -> None:
        self.table_model.set_names(names)
        self._sync_counts()

    def set_units(self, units: dict[int, str]) -> None:
        self.table_model.set_units(units)
