"""
tab_table.py — Tab 1: Live-Telemetrie Tabelle
===============================================
Performante Darstellung per QAbstractTableModel + QTableView.
Speichert Current/Min/Max in NumPy-Arrays für O(1)-Zugriff.
"""

import numpy as np

from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableView, QLabel, QPushButton, QHeaderView,
)
from PyQt6.QtGui import QFont, QColor

from config import MAX_FLOATS, VARIABLE_NAMES


# ══════════════════════════════════════════════════════════════════════════════
#  Datenmodell
# ══════════════════════════════════════════════════════════════════════════════

class TelemetryTableModel(QAbstractTableModel):
    """
    Custom Table-Model für die Telemetrie-Anzeige.

    Spalten: Variable | Aktuell | Min | Max | Δ
    Zeilen:  Nur aktive (gefilterte) Kanäle
    """

    HEADERS = ["Variable", "Aktuell", "Min", "Max", "Δ (Range)"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        n = MAX_FLOATS
        self._names   = [VARIABLE_NAMES.get(i, f"Var_{i:03d}") for i in range(n)]
        self._current = np.zeros(n,     dtype=np.float32)
        self._min     = np.full(n,  np.inf,  dtype=np.float32)
        self._max     = np.full(n, -np.inf,  dtype=np.float32)
        self._n_active = 0   # Sichtbare Zeilen

    # ── QAbstractTableModel Interface ────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return self._n_active

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row, col = index.row(), index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            match col:
                case 0:
                    return self._names[row]
                case 1:
                    return f"{self._current[row]:.4f}"
                case 2:
                    v = self._min[row]
                    return f"{v:.4f}" if not np.isinf(v) else "—"
                case 3:
                    v = self._max[row]
                    return f"{v:.4f}" if not np.isinf(v) else "—"
                case 4:
                    mn, mx = self._min[row], self._max[row]
                    if np.isinf(mn) or np.isinf(mx):
                        return "—"
                    return f"{mx - mn:.4f}"

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return (
                int(Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter)
                if col == 0 else
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            )

        elif role == Qt.ItemDataRole.ForegroundRole and col == 1:
            # Aktuellen Wert farbig kennzeichnen
            v = float(self._current[row])
            if v > 0:
                return QColor("#4ec9b0")   # Grünlich
            elif v < 0:
                return QColor("#f48771")   # Rötlich
            return None

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.HEADERS[section]
        return None

    # ── Daten-Update ─────────────────────────────────────────────────────────

    def update_data(self, values: np.ndarray) -> None:
        """
        Aktualisiert das Modell mit einem neuen Wert-Array.
        Min/Max werden vektorisiert via NumPy berechnet.
        """
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
            # Nur geänderte Datenspalten signalisieren
            self.dataChanged.emit(
                self.index(0, 1),
                self.index(n - 1, 4),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole],
            )

    def clear_stats(self) -> None:
        """Setzt Min/Max und aktuelle Werte zurück (z.B. bei Node-Wechsel)."""
        self._current[:] = 0.0
        self._min[:]     = np.inf
        self._max[:]     = -np.inf
        if self._n_active > 0:
            self.dataChanged.emit(
                self.index(0, 1),
                self.index(self._n_active - 1, 4),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ForegroundRole],
            )


# ══════════════════════════════════════════════════════════════════════════════
#  Widget
# ══════════════════════════════════════════════════════════════════════════════

class TelemetryTableWidget(QWidget):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = TelemetryTableModel()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Info-Zeile ────────────────────────────────────────────────────────
        top_row = QHBoxLayout()
        self._lbl_info = QLabel("Warte auf Daten…")
        self._lbl_info.setStyleSheet("color: #888; font-style: italic;")
        top_row.addWidget(self._lbl_info)
        top_row.addStretch()

        btn_reset = QPushButton("↺  Min/Max zurücksetzen")
        btn_reset.clicked.connect(self.clear_stats)
        btn_reset.setFixedWidth(180)
        top_row.addWidget(btn_reset)
        layout.addLayout(top_row)

        # ── Tabelle ───────────────────────────────────────────────────────────
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setAlternatingRowColors(True)
        self._view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._view.setSortingEnabled(False)   # Kein Sortieren (Performance)
        self._view.setFont(QFont("Monospace", 9))

        hh = self._view.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self._view.setColumnWidth(0, 160)
        self._view.setColumnWidth(1, 110)
        self._view.setColumnWidth(2, 110)
        self._view.setColumnWidth(3, 110)

        vh = self._view.verticalHeader()
        vh.setDefaultSectionSize(20)
        vh.hide()

        layout.addWidget(self._view)

    # ── Öffentliche Schnittstelle ─────────────────────────────────────────────

    def update_data(self, values: np.ndarray) -> None:
        self._model.update_data(values)
        self._lbl_info.setStyleSheet("color: #4ec9b0;")
        self._lbl_info.setText(f"Aktive Kanäle: {len(values)}")

    def clear_stats(self) -> None:
        self._model.clear_stats()
