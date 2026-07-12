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
from PyQt6.QtGui import QColor

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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        n = MAX_FLOATS
        self._names    = [VARIABLE_NAMES.get(i, f"Var_{i:03d}") for i in range(n)]
        self._current  = np.zeros(n, dtype=np.float32)
        self._min      = np.full(n,  np.inf, dtype=np.float32)
        self._max      = np.full(n, -np.inf, dtype=np.float32)
        self._n_active = 0

    # ── QAbstractTableModel-Interface ────────────────────────────────────
    def rowCount(self, parent=QModelIndex()) -> int:
        return self._n_active

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
        }

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= self._n_active:
            return None

        if role == self.NameRole:
            return self._names[row]
        if role == self.CurrentRole:
            return float(self._current[row])
        if role == self.MinRole:
            v = self._min[row]
            return None if np.isinf(v) else float(v)
        if role == self.MaxRole:
            v = self._max[row]
            return None if np.isinf(v) else float(v)
        if role == self.DeltaRole:
            mn, mx = self._min[row], self._max[row]
            if np.isinf(mn) or np.isinf(mx):
                return None
            return float(mx - mn)
        if role == self.ColorRole:
            v = float(self._current[row])
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

        self._current[:n] = values[:n]
        np.minimum(self._min[:n], values[:n], out=self._min[:n])
        np.maximum(self._max[:n], values[:n], out=self._max[:n])
        self._n_active = n

        if row_count_changed:
            self.endResetModel()
        else:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(n - 1, 0),
                [self.CurrentRole, self.MinRole, self.MaxRole,
                 self.DeltaRole, self.ColorRole],
            )

    @pyqtSlot()
    def clear_stats(self) -> None:
        self._current[:] = 0.0
        self._min[:] = np.inf
        self._max[:] = -np.inf
        if self._n_active > 0:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self._n_active - 1, 0),
                [self.CurrentRole, self.MinRole, self.MaxRole,
                 self.DeltaRole, self.ColorRole],
            )


# ══════════════════════════════════════════════════════════════════════════
#  TelemetryBridge — Fassade für Tab 1 + geteilte Live-Werte
# ══════════════════════════════════════════════════════════════════════════

class TelemetryBridge(QObject):
    valuesChanged      = pyqtSignal()
    activeChannelCount  = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table_model = TelemetryTableModel(self)
        self._latest: list[float] = []

    # ── Property: kompletter letzter Werte-Vektor, für Overlays/Gauges ───
    @pyqtProperty("QVariantList", notify=valuesChanged)
    def latestValues(self):
        return self._latest

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
        self._latest = [float(v) for v in values]
        self.valuesChanged.emit()

    @pyqtSlot()
    def clear_stats(self) -> None:
        self.table_model.clear_stats()
