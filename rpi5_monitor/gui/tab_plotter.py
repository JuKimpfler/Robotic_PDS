"""
tab_plotter.py — Tab 2: High-Rate Live-Plotter
================================================
PyQtGraph PlotWidget mit:
  • Variablen-Auswahl (Dropdown)
  • Konfigurierbarem Anzeigebereich (SpinBox)
  • Freeze/Pause-Modus: Plotter einfrieren, Pan/Zoom,
    im Hintergrund läuft die Queue weiter
"""

import collections
import numpy as np

import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox,
)
from PyQt6.QtCore import Qt

from rpi5_monitor.config import MAX_FLOATS, PLOT_BUFFER_SIZE, VARIABLE_NAMES

# Globale PyQtGraph-Konfiguration für maximale Performance
pg.setConfigOptions(antialias=False, useOpenGL=False, background="#1a1a1a")


class LivePlotterWidget(QWidget):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.is_frozen       = False
        self._selected_var   = 0
        self._buffer: collections.deque[float] = collections.deque(maxlen=PLOT_BUFFER_SIZE)
        self._frozen_snapshot: np.ndarray | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("Variable:"))
        self._var_combo = QComboBox()
        self._var_combo.setMinimumWidth(220)
        for i in range(MAX_FLOATS):
            self._var_combo.addItem(VARIABLE_NAMES.get(i, f"Var_{i:03d}"), i)
        self._var_combo.currentIndexChanged.connect(self._on_var_changed)
        toolbar.addWidget(self._var_combo)

        toolbar.addWidget(QLabel("  Punkte:"))
        self._spin_pts = QSpinBox()
        self._spin_pts.setRange(50, PLOT_BUFFER_SIZE)
        self._spin_pts.setValue(200)
        self._spin_pts.setSuffix(" Samples")
        self._spin_pts.setFixedWidth(120)
        toolbar.addWidget(self._spin_pts)

        toolbar.addStretch()

        self._btn_freeze = QPushButton("⏸  Einfrieren")
        self._btn_freeze.setCheckable(True)
        self._btn_freeze.setFixedWidth(130)
        self._btn_freeze.toggled.connect(self._on_freeze_toggled)
        toolbar.addWidget(self._btn_freeze)

        btn_clear = QPushButton("🗑  Löschen")
        btn_clear.setFixedWidth(100)
        btn_clear.clicked.connect(self.clear_buffer)
        toolbar.addWidget(btn_clear)

        layout.addLayout(toolbar)

        # ── Plot-Widget ───────────────────────────────────────────────────────
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1a1a1a")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("left",   "Wert",   color="#aaa")
        self._plot.setLabel("bottom", "Samples", color="#aaa")

        # Hauptkurve (Live-Daten)
        self._curve_live = self._plot.plot(
            pen=pg.mkPen(color="#00d4ff", width=1.5),
        )
        # Eingefrierene Kurve (sichtbar im Freeze-Modus)
        self._curve_frozen = self._plot.plot(
            pen=pg.mkPen(color="#f0a500", width=1.5, style=Qt.PenStyle.DashLine),
        )

        layout.addWidget(self._plot, stretch=1)

        # ── Statuszeile ───────────────────────────────────────────────────────
        self._lbl_stats = QLabel("Min: —  |  Max: —  |  Aktuell: —  |  σ: —")
        self._lbl_stats.setStyleSheet("color: #888; font-family: monospace;")
        layout.addWidget(self._lbl_stats)

        # ── Freeze-Hinweis ────────────────────────────────────────────────────
        self._lbl_frozen = QLabel("⏸  EINGEFROREN — Pan/Zoom aktiv. Live-Queue läuft weiter.")
        self._lbl_frozen.setStyleSheet(
            "background: #3a2f00; color: #f0a500; "
            "padding: 4px 8px; border-radius: 3px; font-weight: bold;"
        )
        self._lbl_frozen.hide()
        layout.addWidget(self._lbl_frozen)

    # ── Daten-Schnittstelle ───────────────────────────────────────────────────

    def append_data(self, values: np.ndarray) -> None:
        """
        Fügt den Wert der ausgewählten Variable in den Ring-Buffer ein
        und aktualisiert den Plot. Wird vom GUI-Timer aufgerufen.
        Kein-Op wenn eingefroren.
        """
        if self._selected_var < len(values):
            self._buffer.append(float(values[self._selected_var]))
            self._redraw_live()

    def _redraw_live(self) -> None:
        """Zeichnet die letzten N Samples neu."""
        n   = self._spin_pts.value()
        buf = list(self._buffer)

        if not buf:
            return

        data = np.array(buf[-n:], dtype=np.float32)
        self._curve_live.setData(data)
        self._update_stats(data)

    def _update_stats(self, data: np.ndarray) -> None:
        if data.size == 0:
            return
        mn   = float(np.min(data))
        mx   = float(np.max(data))
        cur  = float(data[-1])
        std  = float(np.std(data))
        self._lbl_stats.setText(
            f"Min: {mn:.4f}  |  Max: {mx:.4f}  |  Aktuell: {cur:.4f}  |  σ: {std:.4f}"
        )

    # ── Freeze-Logik ─────────────────────────────────────────────────────────

    def _on_freeze_toggled(self, frozen: bool) -> None:
        self.is_frozen = frozen

        if frozen:
            # Snapshot des aktuellen Live-Puffers anfertigen
            n = self._spin_pts.value()
            buf = list(self._buffer)
            self._frozen_snapshot = np.array(buf[-n:], dtype=np.float32)

            # Eingefrierten Snapshot gelb einzeichnen
            self._curve_frozen.setData(self._frozen_snapshot)
            self._update_stats(self._frozen_snapshot)

            # Auto-Range deaktivieren → Pan/Zoom via Maus
            self._plot.enableAutoRange(enable=False)

            self._btn_freeze.setText("▶  Weiter")
            self._lbl_frozen.show()

        else:
            self._frozen_snapshot = None
            self._curve_frozen.setData([])

            self._plot.enableAutoRange(enable=True)

            self._btn_freeze.setText("⏸  Einfrieren")
            self._lbl_frozen.hide()
            self._redraw_live()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_var_changed(self, idx: int) -> None:
        self._selected_var = self._var_combo.itemData(idx) or 0
        self.clear_buffer()

    def clear_buffer(self) -> None:
        """Löscht den Ring-Buffer und den Plot-Inhalt."""
        self._buffer.clear()
        self._frozen_snapshot = None
        self._curve_live.setData([])
        self._curve_frozen.setData([])
        self._lbl_stats.setText("Min: —  |  Max: —  |  Aktuell: —  |  σ: —")
