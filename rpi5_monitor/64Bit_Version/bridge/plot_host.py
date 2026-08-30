"""
bridge/plot_host.py — PyQtGraphHost: pyqtgraph in die QML-Oberfläche einbetten
============================================================================

Die Plotter-Darstellung läuft über pyqtgraph (NumPy-Array -> C++-Polyline),
nicht über QPainter. Dieses Modul bettet ein pyqtgraph-PlotWidget in die
QML-Szene ein und treibt es aus der Datenbrücke (PlotBridge.get_plot_arrays)
mit NumPy-Arrays an.

────────────────────────────────────────────────────────────────────────────
EINBETTUNG (native vs. Image-Fallback)
────────────────────────────────────────────────────────────────────────────
pyqtgraph ist eine QWidget-Bibliothek. Ein QWidget in eine Qt-Quick-Szene
einzubetten, geht am saubersten über ein nativ reparentetes Fenster
(QWindow.setParent des QML-Fensters). Das funktioniert unter X11 zuverlässig.

Auf Wayland / eglfs (Raspberry Pi OS kann beides nutzen) gibt es keine
stabilen Fenster-IDs für solch ein Reparenting — dort fällt der Host
automatisch in den IMAGE-MODUS zurück: pyqtgraph zeichnet in ein offscreen
QPixmap, das per QQuickPaintedItem in die QML-Szene geblittet wird. Das ist
auf allen Plattformen gleich robust und immer noch sehr günstig, weil nur ein
einziges Pixmap kopiert wird.

Schlägt auch das fehl (z. B. pyqtgraph nicht installiert), zeigt der Host
einen lesbaren Fehlerhinweis statt die ganze GUI abstürzen zu lassen.

────────────────────────────────────────────────────────────────────────────
LEISTUNG
────────────────────────────────────────────────────────────────────────────
* Redraw ist auf maxFps (Vorgabe 20) gedeckelt — unabhängig von
  Daten-Bursts. Mehrere Pakete pro Poll werden ohnehin zu einem Block
  zusammengefasst.
* pyqtgraph downsampelt große Fenster automatisch (autoDownsample +
  clipToView), sodass auch 8 Kurven × 1000 Punkte kaum Last machen.
* Der Host meldet dem PlotBridge-PerfWatchdog, ob der Plotter sichtbar ist
  und wie lange ein Durchlauf dauerte. Bei anhaltender Überlastung schaltet
  der Wächter den Plotter ab (siehe PlotBridge / PerfWatchdog).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

from PyQt6.QtCore import (
    Qt, QObject, QTimer, QRectF, QRect, QSize, QPoint,
    pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPixmap, QWindow
from PyQt6.QtQuick import QQuickPaintedItem

import app_settings
from bridge.plot_bridge import PlotBridge, CURVE_COLORS

log = logging.getLogger("bridge.plot.host")

# pyqtgraph KONNTENIGSTENS beim Import konfigurieren (bevor ein Widget
# entsteht). Fällt das Importieren fehl, läuft der Host im Fehler-Modus.
try:
    import pyqtgraph as pg
    _PG_AVAILABLE = True
    pg.setConfigOption("useOpenGL", False)
    # Antialiasing global aus (Performance); über settings.json ("plotter.antialias")
    # wieder einschaltbar. PlotDataItem hat KEINE setAntialiasing()-Methode —
    # die Einstellung wirkt nur ueber diese globale Option.
    pg.setConfigOption("antialias",
                       bool(app_settings.get("plotter.antialias", False)))
    pg.setConfigOption("background", "#1a1a1a")
    pg.setConfigOption("foreground", "#d4d4d4")
    _Y_AXIS = pg.ViewBox.YAxis
    _X_AXIS = pg.ViewBox.XAxis
except Exception as _exc:  # noqa: BLE001
    pg = None
    _PG_AVAILABLE = False
    _Y_AXIS = _X_AXIS = None
    log.warning("pyqtgraph ist nicht verfügbar — Plotter läuft im Fehler-Modus: %s", _exc)


def _parse_color(hexc: str) -> tuple[int, int, int, int]:
    """#aarrggbb / #rrggbb / #rgb -> (r, g, b, a)."""
    h = str(hexc).lstrip("#")
    try:
        if len(h) == 8:
            return (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), int(h[0:2], 16))
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 3:
            return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 255)
    except ValueError:
        pass
    return (255, 255, 255, 255)


_MARKER_COLORS = [
    _parse_color(c) for c in (
        app_settings.get("plotter.markerColors")
        or app_settings.DEFAULTS["plotter"]["markerColors"]
    )
]


class PyQtGraphHost(QQuickPaintedItem):
    plotterChanged = pyqtSignal()
    modeChanged = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setAntialiasing(False)
        self._plotter: Optional[PlotBridge] = None

        self._plot = None              # pyqtgraph PlotWidget
        self._curves: list = []        # aktive PlotDataItems
        self._marker_lines: list = []  # InfiniteLine-Pool
        self._live_curve = None        # gestrichelte Live-Kurve (eingefroren)
        self._native_win: Optional[QWindow] = None
        self._pixmap: Optional[QPixmap] = None
        self._mode = "init"            # init | native | image | error
        self._error_text = ""
        self._last_shared: Optional[bool] = None
        self._built = False
        self._pixmap_fail = 0

        self._max_fps = max(1, int(app_settings.get("plotter.maxFps", 20)))
        self._render_interval = max(1, 1000 // self._max_fps)
        # pyqtgraph-Performance-Schalter aus settings.json ("plotter").
        self._downsample = bool(app_settings.get("plotter.downsample", True))
        self._antialias = bool(app_settings.get("plotter.antialias", False))

        self._timer = QTimer(self)
        self._timer.setInterval(self._render_interval)
        self._timer.timeout.connect(self._redraw)

        self.xChanged.connect(self._sync_geometry)
        self.yChanged.connect(self._sync_geometry)
        self.widthChanged.connect(self._sync_geometry)
        self.heightChanged.connect(self._sync_geometry)
        self.windowChanged.connect(self._on_window_changed)

    # ── QML-Property: die Datenbrücke ───────────────────────────────────────
    def getPlotter(self) -> Optional[PlotBridge]:
        return self._plotter

    def setPlotter(self, bridge: PlotBridge) -> None:
        if self._plotter is bridge:
            return
        if self._plotter is not None:
            try:
                self._plotter.channelsChanged.disconnect(self._on_channels_changed)
                self._plotter.frozenChanged.disconnect(self._on_frozen_changed)
            except (TypeError, RuntimeError):
                pass
        self._plotter = bridge
        if bridge is not None:
            bridge.channelsChanged.connect(self._on_channels_changed)
            bridge.frozenChanged.connect(self._on_frozen_changed)
            self._build_if_ready()
        self.plotterChanged.emit()

    plotter = pyqtProperty(QObject, fget=getPlotter, fset=setPlotter,
                            notify=plotterChanged)

    @pyqtProperty(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    # ── Aufbau ──────────────────────────────────────────────────────────────
    def componentComplete(self) -> None:
        super().componentComplete()
        self._build_if_ready()

    def _on_window_changed(self, _win) -> None:
        self._build_if_ready()

    def _build_if_ready(self) -> None:
        if self._built or self._plotter is None:
            return
        win = self.window()
        if win is None:
            return
        if not _PG_AVAILABLE:
            self._fail_to_error("pyqtgraph ist nicht installiert "
                                "(pip install pyqtgraph).")
            return
        try:
            self._build_plot()
        except Exception as exc:  # noqa: BLE001
            log.warning("Plotter-Aufbau fehlgeschlagen: %s", exc)
            self._fail_to_error(f"Plotter konnte nicht erstellt werden: {exc}")
            return
        self._built = True
        self._timer.start()

    def _build_plot(self) -> None:
        self._plot = pg.PlotWidget(background=QColor("#1a1a1a"))
        self._plot.setAntialiasing(self._antialias)
        self._plot.setMouseEnabled(x=False, y=False)   # Bedienung läuft in QML
        self._plot.hideButtons()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "")
        self._plot.setLabel("bottom", "Sample")
        # Immer manueller X-Bereich (0..n-1); Y je nach Skalierung.
        self._plot.enableAutoRange(axis=_X_AXIS, enable=False)

        # Native Einbettung versuchen; sonst Image-Fallback.
        if self._try_native():
            self._mode = "native"
        else:
            self._mode = "image"
            try:
                self._plot.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            except Exception:
                pass
        self.modeChanged.emit()

    def _try_native(self) -> bool:
        """Versucht, das Widget als natives Kindfenster einzubetten.

        Gibt False zurück, sobald irgendetwas nicht klappt — dann übernimmt
        der Image-Modus.
        """
        try:
            self._plot.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
            self._plot.show()
            native = self._plot.windowHandle()
            if native is None:
                # Manche Plattformen liefern erst nach winId() einen Handle.
                native = QWindow.fromWinId(self._plot.winId())
            if native is None:
                return False
            qw = self.window()
            if qw is None:
                return False
            native.setParent(qw)
            # Manche QPA-Plugins (offscreen, teils Wayland/eglfs — siehe
            # Docstring oben) lehnen setParent() nur mit einer Qt-internen
            # qWarning ("... does not support setParent!") ab, OHNE eine
            # Python-Exception zu werfen. Ohne diese Prüfung hier würde
            # _try_native() das als Erfolg werten: self._plot bliebe ein
            # eigenständiges, sichtbares Top-Level-Fenster, das nie zur
            # QML-Szene gehört — mit spürbaren Folgen bis hin zu einem
            # sauberen Beenden der Anwendung. Deshalb wird das Ergebnis
            # verifiziert statt nur angenommen.
            if native.parent() is not qw:
                self._plot.hide()
                return False
            # Touch/Events sollen an die QML-Ebene durchgereicht werden
            # (Pinch-to-Zoom, Buttons), nicht vom Widget geschluckt.
            self._plot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._native_win = native
            self._sync_geometry()
            if self._native_win is not None:
                self._native_win.setVisible(self._on_screen())
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("Native-Einbettung nicht möglich, Image-Modus: %s", exc)
            return False

    # ── Geometrie (nur native) ─────────────────────────────────────────────
    def _on_screen(self, win=None, x=None, y=None, w=None, h=None) -> bool:
        win = win or self.window()
        if win is None:
            return True
        if x is None:
            try:
                tl = self.mapToItem(win.contentItem(), 0.0, 0.0)
                x, y = tl.x(), tl.y()
            except Exception:
                return True
        if w is None:
            w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return False
        ww, wh = win.width(), win.height()
        if ww <= 0 or wh <= 0:
            return True
        return (x + w > 0) and (x < ww) and (y + h > 0) and (y < wh)

    def _sync_geometry(self) -> None:
        if self._mode != "native" or self._native_win is None:
            return
        win = self.window()
        if win is None:
            return
        try:
            tl = self.mapToItem(win.contentItem(), 0.0, 0.0)
            x, y = int(round(tl.x())), int(round(tl.y()))
            w, h = int(round(self.width())), int(round(self.height()))
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        on = self._on_screen(win, x, y, w, h)
        self._native_win.setVisible(on)
        if not on:
            return
        self._native_win.setGeometry(x, y, w, h)
        try:
            self._plot.resize(w, h)
        except Exception:
            pass

    # ── Redraw ───────────────────────────────────────────────────────────────
    def _redraw(self) -> None:
        if self._plot is None or self._plotter is None:
            return
        if not self._plotter.enabled or self._plotter.overloaded:
            self._plotter.setPlotActive(False)
            if self._mode == "native" and self._native_win is not None:
                self._native_win.setVisible(False)
            return
        if not self._on_screen():
            self._plotter.setPlotActive(False)
            if self._mode == "native" and self._native_win is not None:
                self._native_win.setVisible(False)
            return

        self._plotter.setPlotActive(True)
        t0 = time.perf_counter()
        try:
            arrays = self._plotter.get_plot_arrays()
            self._update_curves(arrays)
            self._update_markers(arrays)
            self._update_frozen_overlay(arrays)
        except Exception as exc:  # noqa: BLE001
            log.warning("Plot-Redraw fehlgeschlagen: %s", exc)
            self._fail_to_error(f"Plot-Redraw fehlgeschlagen: {exc}")
            return
        dt = (time.perf_counter() - t0) * 1000.0
        self._plotter.note_render(dt)

        if self._mode == "image":
            self._render_to_pixmap()
            self.update()          # QQuickPaintedItem neu zeichnen lassen
        elif self._mode == "native":
            self._sync_geometry()

    def _update_curves(self, arrays) -> None:
        n = len(arrays)
        self._ensure_curves(n)
        shared = self._plotter.sharedScale
        last = (len(arrays[0][0]) - 1) if n else 0

        for i, (xs, ys) in enumerate(arrays):
            self._curves[i].setData(xs, ys)
            self._curves[i].show()
        for i in range(n, len(self._curves)):
            self._curves[i].hide()

        if shared != self._last_shared:
            self._last_shared = shared
            if shared:
                self._plot.enableAutoRange(axis=_Y_AXIS, enable=True)
            else:
                self._plot.enableAutoRange(axis=_Y_AXIS, enable=False)
                self._plot.setYRange(-0.1, 1.1, padding=0.0)
        if last > 0:
            self._plot.setXRange(0, last, padding=0.0)

    def _ensure_curves(self, n: int) -> None:
        while len(self._curves) < n:
            i = len(self._curves)
            pen = pg.mkPen(CURVE_COLORS[i % len(CURVE_COLORS)], width=1.8)
            ci = self._plot.plot(pen=pen, connect="auto")
            ci.setDownsampling(auto=self._downsample, method="peak")
            ci.setClipToView(True)
            # Achtung: PlotDataItem hat KEINE setAntialiasing()-Methode; die
            # Antialiasing-Einstellung wirkt ueber die globale pg-Option oben.
            self._curves.append(ci)

    def _update_markers(self, arrays) -> None:
        marks = self._plotter.visible_markers(self._plotter.pointsCount)
        n = len(arrays[0][0]) if arrays else 0
        last = max(0, n - 1)
        # Pool vergrößern. Mit label="" wird das Label-Objekt angelegt
        # (InfiniteLine.label), das wir unten mit Text fuellen.
        while len(self._marker_lines) < max(8, len(marks)):
            line = pg.InfiniteLine(angle=90, movable=False, label="")
            self._plot.addItem(line)
            self._marker_lines.append(line)
        for i, (pos, text, level) in enumerate(marks):
            line = self._marker_lines[i]
            line.setVisible(True)
            try:
                line.setValue(pos * last)
                line.setPen(pg.mkPen(_MARKER_COLORS[min(level, len(_MARKER_COLORS) - 1)],
                                     width=1.2, style=Qt.PenStyle.DashLine))
                label = getattr(line, "label", None)
                if label is not None and text:
                    label.setText(text)
                    label.setColor(QColor(*_MARKER_COLORS[min(level, len(_MARKER_COLORS) - 1)]))
            except Exception:
                pass
        for i in range(len(marks), len(self._marker_lines)):
            self._marker_lines[i].setVisible(False)

    def _update_frozen_overlay(self, arrays) -> None:
        if not self._plotter.frozen:
            if self._live_curve is not None:
                self._live_curve.hide()
            return
        live = self._plotter.live_snapshot()
        if live.shape[1] == 0:
            if self._live_curve is not None:
                self._live_curve.hide()
            return
        shared = self._plotter.sharedScale
        xs = np.arange(live.shape[1], dtype=np.float64)
        series = live[0].astype(np.float64)
        if shared:
            ys = series
        else:
            finite = np.isfinite(series)
            if finite.any():
                mn = float(series[finite].min())
                mx = float(series[finite].max())
                span = (mx - mn) or 1.0
                ys = (series - mn) / span
            else:
                ys = np.zeros_like(xs)
        if self._live_curve is None:
            pen = pg.mkPen(CURVE_COLORS[0], width=1.4)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._live_curve = self._plot.plot(pen=pen, connect="auto")
            self._live_curve.setDownsampling(auto=self._downsample, method="peak")
            self._live_curve.setClipToView(True)
            # (Antialiasing ueber die globale pg-Option, s.o.)
        self._live_curve.setData(xs, ys)
        self._live_curve.show()

    def _render_to_pixmap(self) -> None:
        w = max(1, int(round(self.width())))
        h = max(1, int(round(self.height())))
        try:
            self._plot.resize(w, h)
            grabbed = self._plot.grab(QRect(0, 0, w, h))
            if not grabbed.isNull():
                self._pixmap = grabbed
                return
        except Exception:
            pass
        # Fallback: explizit in ein Pixmap rendern.
        try:
            if self._pixmap is None or self._pixmap.size() != QSize(w, h):
                self._pixmap = QPixmap(w, h)
            self._pixmap.fill(QColor("#1a1a1a"))
            p = QPainter(self._pixmap)
            # self._plot ist ein pyqtgraph.PlotWidget (QGraphicsView-Subklasse).
            # QGraphicsView.render() hat eine andere Signatur als QWidget.render():
            # render(painter, target: QRectF, source: QRect, aspectRatioMode).
            self._plot.render(p, QRectF(0, 0, w, h), QRect(0, 0, w, h))
            p.end()
        except Exception as exc:  # noqa: BLE001
            log.warning("Pixmap-Render fehlgeschlagen: %s", exc)
        # Sicherheitsnetz: bleibt die Bildausgabe im Image-Modus dauerhaft
        # leer, zeigen wir einen lesbaren Fehler statt eines schwarzen Kastens.
        if self._pixmap is None or self._pixmap.isNull():
            self._pixmap_fail += 1
            if self._pixmap_fail >= 3:
                self._fail_to_error("Plotter-Bildausgabe lieferte kein Bild.")
        else:
            self._pixmap_fail = 0

    # ── QML-Reaktionen ────────────────────────────────────────────────────
    def _on_channels_changed(self) -> None:
        # Kurvenzahl/Farben können sich geändert haben -> neu aufbauen.
        self._curves.clear()
        self._marker_lines.clear()
        self._live_curve = None
        if self._plot is not None:
            try:
                self._plot.clear()
            except Exception:
                pass
        self._last_shared = None
        # Beim nächsten Redraw werden die Kurven neu erzeugt.
        if self._mode == "image":
            self.update()

    def _on_frozen_changed(self) -> None:
        if self._mode == "image":
            self.update()

    # ── Fehler-Modus ────────────────────────────────────────────────────────
    def _fail_to_error(self, text: str) -> None:
        self._error_text = text
        self._mode = "error"
        self.modeChanged.emit()
        self._timer.stop()
        if self._plotter is not None:
            self._plotter.setPlotActive(False)
        self.update()

    # ── Paint (Image-/Fehler-Modus; native zeichnet selbst) ────────────────
    def paint(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        if self._mode == "image" and self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(QRectF(0, 0, w, h), self._pixmap,
                                QRectF(self._pixmap.rect()))
        elif self._mode == "error":
            painter.fillRect(QRectF(0, 0, w, h), QColor("#1a1a1a"))
            painter.setPen(QColor("#f48771"))
            painter.drawText(QRectF(0, 0, w, h),
                             Qt.AlignmentFlag.AlignCenter,
                             "Plotter nicht verfügbar:\n" + self._error_text)
        # native: transparent — das Widget liegt als Kindfenster darüber.
