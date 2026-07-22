"""
bridge/plot_bridge.py — Tab 2 (Live-Plotter)
================================================
Migrationsplan Abschnitt 4.4, Option C: PyQtGraph wird ersetzt durch ein
eigenes QQuickPaintedItem ("PlotCanvas"), das direkt mit QPainter zeichnet.
Das ist die "echte" QML-native Lösung mit mittlerem Aufwand (siehe
Trade-off-Tabelle im Plan) — kein zusätzliches Widget-Fenster, kein
PyQtGraph mehr nötig.

Zwei Klassen:
  PlotBridge  — hält den Ring-Buffer + Zustand (Freeze, ausgewählte Variable,
                Statistik), analog zu gui/tab_plotter.py::LivePlotterWidget,
                aber ohne jede Zeichenlogik.
  PlotCanvas  — QQuickPaintedItem, zeichnet den Inhalt von PlotBridge.
                Wird per qmlRegisterType als <PlotCanvas> in QML nutzbar
                gemacht (siehe main_qml.py).
"""
from __future__ import annotations

import collections

import numpy as np
from PyQt5.QtCore import Qt, QObject, QRectF, pyqtSignal, pyqtProperty, pyqtSlot
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtQuick import QQuickPaintedItem

from config import MAX_FLOATS, PLOT_BUFFER_SIZE, VARIABLE_NAMES


# ══════════════════════════════════════════════════════════════════════════
#  PlotBridge — Datenhaltung (kein Rendering)
# ══════════════════════════════════════════════════════════════════════════

class PlotBridge(QObject):
    bufferChanged      = pyqtSignal()
    statsChanged        = pyqtSignal()
    selectedVarChanged  = pyqtSignal()
    frozenChanged        = pyqtSignal()
    pointsChanged        = pyqtSignal()
    variableNamesChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._buffer: collections.deque[float] = collections.deque(maxlen=PLOT_BUFFER_SIZE)
        self._frozen_snapshot: list[float] = []
        self._selected_var = 0
        self._points = 500
        self._frozen = False
        self._stats = "Min: —  |  Max: —  |  Aktuell: —  |  σ: —"
        self._names = [VARIABLE_NAMES.get(i, f"Var_{i:03d}") for i in range(MAX_FLOATS)]

    # ── Properties für QML-Bindings ───────────────────────────────────────
    @pyqtProperty(int, notify=selectedVarChanged)
    def selectedVar(self) -> int:
        return self._selected_var

    @pyqtSlot(int)
    def setSelectedVar(self, idx: int) -> None:
        if idx == self._selected_var:
            return
        self._selected_var = idx
        self.clearBuffer()
        self.selectedVarChanged.emit()

    @pyqtProperty(bool, notify=frozenChanged)
    def frozen(self) -> bool:
        return self._frozen

    @pyqtSlot(bool)
    def setFrozen(self, value: bool) -> None:
        if value == self._frozen:
            return
        self._frozen = value
        if value:
            n = self._points
            self._frozen_snapshot = list(self._buffer)[-n:]
        else:
            self._frozen_snapshot = []
        self.frozenChanged.emit()

    @pyqtProperty(int, notify=pointsChanged)
    def pointsCount(self) -> int:
        return self._points

    @pyqtSlot(int)
    def setPointsCount(self, n: int) -> None:
        n = max(50, min(600, n))
        if n == self._points:
            return
        self._points = n
        self.pointsChanged.emit()
        self.bufferChanged.emit()

    @pyqtProperty(str, notify=statsChanged)
    def statsText(self) -> str:
        return self._stats

    @pyqtProperty("QVariantList", constant=True)
    def variableNames(self):
        return self._names

    # ── Slots ──────────────────────────────────────────────────────────────
    @pyqtSlot()
    def clearBuffer(self) -> None:
        self._buffer.clear()
        self._frozen_snapshot = []
        self._stats = "Min: —  |  Max: —  |  Aktuell: —  |  σ: —"
        self.statsChanged.emit()
        self.bufferChanged.emit()

    # ── Vom AppBridge-Poll-Loop aufgerufen ────────────────────────────────
    def append_batch(self, batch: list[np.ndarray]) -> None:
        if self._frozen:
            return
        idx = self._selected_var
        changed = False
        for values in batch:
            if idx < len(values):
                self._buffer.append(float(values[idx]))
                changed = True
        if not changed:
            return
        self._update_stats()
        self.bufferChanged.emit()

    def _update_stats(self) -> None:
        data = list(self._buffer)[-self._points:]
        if not data:
            return
        arr = np.array(data, dtype=np.float32)
        self._stats = (
            f"Min: {float(np.min(arr)):.4f}  |  Max: {float(np.max(arr)):.4f}  |  "
            f"Aktuell: {float(arr[-1]):.4f}  |  σ: {float(np.std(arr)):.4f}"
        )
        self.statsChanged.emit()

    # ── Von PlotCanvas beim Zeichnen gelesen ──────────────────────────────
    def live_snapshot(self) -> list[float]:
        return list(self._buffer)[-self._points:]

    def frozen_snapshot(self) -> list[float]:
        return self._frozen_snapshot


# ══════════════════════════════════════════════════════════════════════════
#  PlotCanvas — QQuickPaintedItem, per qmlRegisterType("App", 1, 0, "PlotCanvas")
# ══════════════════════════════════════════════════════════════════════════

class PlotCanvas(QQuickPaintedItem):
    plotBridgeChanged = pyqtSignal()

    _LIVE_COLOR   = QColor("#00d4ff")
    _FROZEN_COLOR = QColor("#f0a500")
    _GRID_COLOR   = QColor(255, 255, 255, 25)

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
            self._bridge.bufferChanged.disconnect(self.update)
            self._bridge.frozenChanged.disconnect(self.update)
        self._bridge = bridge
        if bridge is not None:
            bridge.bufferChanged.connect(self.update)
            bridge.frozenChanged.connect(self.update)
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
        painter.fillRect(QRectF(0, 0, w, h), QColor("#1a1a1a"))

        # Horizontales Grid (analog PyQtGraph showGrid)
        painter.setPen(QPen(self._GRID_COLOR, 1))
        for i in range(1, 5):
            y = h * i / 5
            painter.drawLine(0, int(y), int(w), int(y))
        for i in range(1, 8):
            x = w * i / 8
            painter.drawLine(int(x), 0, int(x), int(h))

        if self._bridge is None:
            return

        live = self._bridge.live_snapshot()
        self._draw_curve(painter, live, self._LIVE_COLOR, w, h, dashed=False)

        if self._bridge.frozen:
            frozen = self._bridge.frozen_snapshot()
            self._draw_curve(painter, frozen, self._FROZEN_COLOR, w, h, dashed=True)

    @staticmethod
    def _draw_curve(painter: QPainter, data: list[float], color: QColor,
                     w: float, h: float, dashed: bool) -> None:
        n = len(data)
        if n < 2:
            return

        mn, mx = min(data), max(data)
        span = (mx - mn) or 1.0
        margin = h * 0.08   # etwas Rand oben/unten, wie AutoRange bei PyQtGraph

        pen = QPen(color, 1.8)
        if dashed:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)

        path = QPainterPath()
        for i, v in enumerate(data):
            x = w * i / (n - 1)
            y = (h - 2 * margin) * (1.0 - (v - mn) / span) + margin
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)
