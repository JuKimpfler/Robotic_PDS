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
* Gezeichnet wird nur, wenn es etwas Neues gibt. Die Datenbrücke meldet über
  bufferChanged (und Einfrieren/Marken/Auswahl), dass sich etwas geändert
  hat; ohne solche Meldung überspringt der Takt den ganzen Durchlauf. Im
  eingefrorenen Bild oder bei abgerissener Telemetrie kostet der Plotter
  damit gar nichts mehr statt 20 vollständiger Neuzeichnungen pro Sekunde.
* Ist der Plotter nicht sichtbar (anderer Tab) oder abgeschaltet, läuft der
  Takt auf idleFps (Vorgabe 4) herunter, statt 20-mal pro Sekunde nur
  nachzusehen, ob er etwas tun darf.
* pyqtgraph downsampelt große Fenster automatisch (autoDownsample +
  clipToView), sodass auch 8 Kurven × 1000 Punkte kaum Last machen.
* Im Image-Modus wird IN EIN FESTES QPixmap gerendert. QWidget.grab() legt
  bei jedem Aufruf ein neues an — bei 800×400 sind das rund 1,3 MB, also
  über 25 MB pro Sekunde, die nur entstehen, um sofort wieder freigegeben
  zu werden.
* Der Host meldet dem PlotBridge-PerfWatchdog, ob der Plotter sichtbar ist
  und wie lange ein Durchlauf dauerte. Bei anhaltender Überlastung schaltet
  der Wächter den Plotter ab (siehe PlotBridge / PerfWatchdog).
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

import numpy as np

from PyQt6.QtCore import (
    Qt, QObject, QTimer, QRectF, QRect, QSize, QPoint,
    pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QGuiApplication, QPainter, QPixmap, QRegion, QWindow,
)
from PyQt6.QtQuick import QQuickPaintedItem
from PyQt6.QtWidgets import QWidget

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


def _nice_step(raw: float) -> float:
    """Naechstgroesserer „glatter“ Schritt aus der Reihe 1-2-5 x 10^k."""
    if not math.isfinite(raw) or raw <= 0.0:
        return 1.0
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    for m in (1.0, 2.0, 5.0):
        if raw <= m * base * (1.0 + 1e-9):
            return m * base
    return 10.0 * base


# So viele Bilder lang wird der Takt noch nicht nachgefuehrt: die ersten
# Durchlaeufe nach Start oder Tabwechsel sind einmalig teurer, weil das
# Widget erstmals layoutet und Schriften geladen werden.
_ADAPT_WARMUP = 5


def adaptive_interval(frame_ms: float, fast_ms: int, slow_ms: int,
                      budget: float, current_ms: int) -> int:
    """Zieltakt aus der gemessenen Dauer EINES vollstaendigen Bildes.

    `budget` sagt, wie viel Luft zwischen zwei Bildern bleiben soll: bei 4,0
    darf der Plotter hoechstens ein Viertel der Zeit des GUI-Threads
    verbrauchen. Genau das ist die eigentliche Anforderung — der GUI-Thread
    haelt auch den 100-Hz-Sendetakt der Fernsteuerung, und der darf nicht
    warten muessen.

    Zwischen `fast_ms` (maxFps) und `slow_ms` (minFps) begrenzt; die
    Hysterese von 15 % verhindert, dass der Takt bei kleinen Lastwechseln
    hin- und herspringt (das saehe man als ungleichmaessigen Bildlauf).
    """
    if frame_ms <= 0.0 or not math.isfinite(frame_ms):
        return current_ms
    want = frame_ms * budget
    ziel = int(round(max(fast_ms, min(slow_ms, want))))
    # Am Anschlag (maxFps bzw. minFps) ohne Hysterese uebernehmen: sonst
    # bliebe der Takt nach einer Lastspitze fuer immer knapp unter maxFps
    # stehen, weil der letzte kleine Schritt zurueck nie gross genug ist.
    am_anschlag = want <= fast_ms or want >= slow_ms
    if (not am_anschlag and current_ms > 0
            and abs(ziel - current_ms) < 0.15 * current_ms):
        return current_ms
    return ziel


def nice_y_range(mn: float, mx: float) -> tuple[float, float] | None:
    """Glatter Y-Bereich, der [mn, mx] mit etwas Luft sicher enthaelt.

    Warum ueberhaupt: `enableAutoRange(Y)` laeuft nach JEDEM setData und
    liefert fast immer eine minimal andere Zahl. pyqtgraph rechnet daraufhin
    Ticks und Beschriftung neu (QFontMetrics ueber jeden Achsentext) und
    rastert die Achse neu — in jedem Bild. Auf glatte 1-2-5-Schritte
    gerundet aendert sich der Bereich dagegen nur in Spruengen, und
    dazwischen faellt gar keine Achsenarbeit an.

    Nebenbei ist eine Achse mit 0 / 0,5 / 1 auch schlicht besser abzulesen
    als eine mit 0,0317 / 0,4913 / 0,9509.

    Ehrlichkeitshalber: gemessen (tools/plotter_bench.py) faellt eindeutig
    die ZAHL der Bereichswechsel (91 -> 7 je 200 Bilder), der Zeitgewinn
    liegt im Offscreen-Rasterer unter der Streuung. Der belegte Nutzen ist
    damit vorerst die ruhige Achse.

    None heisst: aus diesen Zahlen laesst sich kein Bereich bilden.
    """
    if not (math.isfinite(mn) and math.isfinite(mx)):
        return None
    if mx < mn:
        mn, mx = mx, mn
    span = mx - mn
    if span <= 0.0:
        # Waagerechte Linie: um den Wert herum etwas Platz lassen, damit sie
        # nicht auf einer Bereichsgrenze klebt.
        half = (abs(mx) * 0.1) or 0.5
        mn, mx = mn - half, mx + half
        span = mx - mn
    pad = span * 0.05
    lo, hi = mn - pad, mx + pad
    # Zielgroesse: rund acht Schritte. Grob gerundet (vier Schritte) verschenkt
    # der Sprung von 0,2 auf 0,5 in der 1-2-5-Reihe sonst bis zur Haelfte der
    # Bildhoehe — die Kurve waere unnoetig flach.
    step = _nice_step((hi - lo) / 8.0)
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step
    if hi <= lo:
        hi = lo + step
    return lo, hi


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

        # ── Zustand, um Arbeit zu vermeiden ────────────────────────────────
        #  _dirty       es gibt etwas Neues zu zeichnen (siehe _mark_dirty)
        #  _last_x_max  zuletzt gesetzter X-Bereich; setXRange loest sonst
        #               bei jedem Frame ein volles Neu-Layout der Achsen aus
        #  _pen_cache   Stifte fuer die Marken, einmal je Stufe angelegt
        #  _mark_state  je Markenlinie (Wert, Text, Stufe) — nur was sich
        #               geaendert hat, wird angefasst (setText rendert Text neu)
        #  _plot_size   aktuelle Groesse des Widgets, damit resize() nicht in
        #               jedem Frame laeuft
        #  _live_ys     Puffer fuer die gestrichelte Live-Kurve
        self._dirty = True
        self._last_x_max = -1.0
        self._last_y_range: Optional[tuple[float, float]] = None
        self._pen_cache: list = []
        self._mark_state: list[tuple] = []
        self._plot_size = QSize(0, 0)
        self._plot_pos = QPoint(0, 0)
        self._live_ys: Optional[np.ndarray] = None

        self._max_fps = max(1, int(app_settings.get("plotter.maxFps", 20)))
        self._render_interval = max(1, 1000 // self._max_fps)
        # ── Adaptiver Bildtakt ────────────────────────────────────────────
        #  maxFps ist die OBERgrenze; wie schnell wirklich gezeichnet wird,
        #  entscheidet die gemessene Dauer eines Bildes. Auf schwacher
        #  Hardware sinkt der Takt damit sanft ab, statt dass der Waechter
        #  den Plotter irgendwann ganz abschaltet — vorher gab es nur
        #  "volle 12 fps" oder "gar nichts".
        self._adaptive = bool(app_settings.get("plotter.adaptiveFps", True))
        self._min_fps = max(1, int(app_settings.get("plotter.minFps", 4)))
        self._slow_interval = max(self._render_interval, 1000 // self._min_fps)
        self._fps_budget = max(1.0, float(
            app_settings.get("plotter.fpsBudgetFactor", 4.0)))
        self._frame_ms = 0.0          # Tiefpass ueber die Bilddauer
        self._adapt_calls = 0         # Warmup-Zaehler
        self._active_interval = self._render_interval
        # Wenn nichts zu tun ist (anderer Tab, Plotter aus), reicht ein
        # gemaechlicher Takt zum Nachsehen — 20 Weckrufe pro Sekunde fuer ein
        # sofortiges "nein" sind reine Verschwendung.
        self._idle_fps = max(1, int(app_settings.get("plotter.idleFps", 4)))
        self._idle_interval = max(1, 1000 // self._idle_fps)
        # pyqtgraph-Performance-Schalter aus settings.json ("plotter").
        self._downsample = bool(app_settings.get("plotter.downsample", True))
        self._antialias = bool(app_settings.get("plotter.antialias", False))
        # Gemeinsame Skala: glatter, quantisierter Y-Bereich statt
        # enableAutoRange(Y) nach jedem setData (siehe nice_y_range).
        self._quantize_y = bool(app_settings.get("plotter.quantizeYRange", True))

        self._timer = QTimer(self)
        self._timer.setInterval(self._render_interval)
        self._timer.timeout.connect(self._redraw)

        self.xChanged.connect(self._sync_geometry)
        self.yChanged.connect(self._sync_geometry)
        self.widthChanged.connect(self._on_size_changed)
        self.heightChanged.connect(self._on_size_changed)
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
                self._plotter.bufferChanged.disconnect(self._mark_dirty)
                self._plotter.markersChanged.disconnect(self._mark_dirty)
            except (TypeError, RuntimeError):
                pass
        self._plotter = bridge
        if bridge is not None:
            bridge.channelsChanged.connect(self._on_channels_changed)
            bridge.frozenChanged.connect(self._on_frozen_changed)
            # Nur diese Meldungen bedeuten "es gibt ein neues Bild". Ohne sie
            # ueberspringt der Takt den Durchlauf komplett — siehe _redraw.
            bridge.bufferChanged.connect(self._mark_dirty)
            bridge.markersChanged.connect(self._mark_dirty)
            self._build_if_ready()
        self.plotterChanged.emit()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _on_size_changed(self) -> None:
        # Andere Groesse heisst neues Bild — im Image-Modus muss dafuer auch
        # das Pixmap neu dimensioniert werden (siehe _render_to_pixmap).
        self._dirty = True
        self._sync_geometry()

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
            # Das Pixmap deckt die ganze Flaeche ab. Ohne diesen Hinweis
            # loescht Qt Quick den Zwischenspeicher des Items vor jedem
            # paint() erst transparent — ein voller Durchlauf ueber alle
            # Pixel, den niemand sieht.
            self.setOpaquePainting(True)
        self.modeChanged.emit()

    # QPA-Plattformen, auf denen natives Reparenting nachweislich zuverlässig
    # funktioniert (siehe Modul-Docstring oben). Alles andere — insbesondere
    # Wayland-Compositor wie das auf aktuellem Raspberry Pi OS (Bookworm+)
    # standardmäßige "wayland" (wayfire/labwc), sowie eglfs, offscreen usw. —
    # geht direkt in den Image-Modus. Grund: auf Wayland NIMMT setParent()
    # den Aufruf entgegen (self._plot.windowHandle().parent() zeigt danach
    # scheinbar korrekt auf das QML-Fenster), der Compositor stellt das
    # Widget aber trotzdem als eigenständiges Top-Level-Fenster dar — meist
    # mit fester Startposition oben links und fester Startgröße, die nie der
    # QML-Geometrie folgt. Anders als bei den QPA-Plugins, die setParent()
    # klar mit einer qWarning ablehnen, lässt sich dieser Fall über den
    # Objektstatus danach NICHT zuverlässig erkennen — daher die Prüfung
    # hier vorab über den Plattformnamen statt hinterher über das Ergebnis.
    _NATIVE_OK_PLATFORMS = {"xcb"}

    def _try_native(self) -> bool:
        """Versucht, das Widget als natives Kindfenster einzubetten.

        Gibt False zurück, sobald irgendetwas nicht klappt — dann übernimmt
        der Image-Modus.
        """
        platform = QGuiApplication.platformName()
        if platform not in self._NATIVE_OK_PLATFORMS:
            log.info(
                "QPA-Plattform %r unterstützt kein natives Reparenting "
                "zuverlässig — Image-Modus.", platform)
            return False
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
        # Unveraenderte Geometrie nicht anfassen: setGeometry/resize loesen im
        # Zweifel ein Neu-Layout des Widgets aus, und diese Methode laeuft im
        # nativen Modus bei jedem Takt.
        size = QSize(w, h)
        pos = QPoint(x, y)
        if self._plot_size != size or self._plot_pos != pos:
            self._plot_size = size
            self._plot_pos = pos
            self._native_win.setGeometry(x, y, w, h)
            try:
                self._plot.resize(w, h)
            except Exception:
                pass

    # ── Redraw ───────────────────────────────────────────────────────────────
    def _set_idle(self, idle: bool) -> None:
        """Takt zwischen Zeichen- und Ruhefrequenz umschalten.

        Im Zeichenbetrieb gilt der adaptive Takt (_active_interval), nicht
        starr 1000/maxFps — siehe _adapt_interval.
        """
        want = self._idle_interval if idle else self._active_interval
        if self._timer.interval() != want:
            self._timer.setInterval(want)

    def _adapt_interval(self, dt_ms: float) -> None:
        """Bildtakt an die tatsaechlich gemessene Bilddauer anpassen."""
        if not self._adaptive:
            return
        # Tiefpass: ein einzelner Ausreisser (Tabwechsel, Groessenaenderung)
        # soll den Takt nicht umwerfen, anhaltende Last schon.
        self._frame_ms = (dt_ms if self._frame_ms <= 0.0
                          else self._frame_ms * 0.8 + dt_ms * 0.2)
        self._adapt_calls += 1
        if self._adapt_calls <= _ADAPT_WARMUP:
            # Die ersten Bilder nach Start/Tabwechsel sind einmalig teurer
            # (Widget wird erstmals layoutet); daran darf sich der Dauertakt
            # nicht festbeissen.
            return
        want = adaptive_interval(self._frame_ms, self._render_interval,
                                 self._slow_interval, self._fps_budget,
                                 self._active_interval)
        if want == self._active_interval:
            return
        log.info("Plotter-Bildtakt %d -> %d ms (%.1f -> %.1f fps, "
                 "gemessen %.1f ms je Bild)",
                 self._active_interval, want,
                 1000.0 / self._active_interval, 1000.0 / want, self._frame_ms)
        self._active_interval = want

    def _go_idle(self) -> None:
        """Nichts zu tun: Plotter stilllegen und den Takt herunterfahren."""
        self._plotter.setPlotActive(False)
        if self._mode == "native" and self._native_win is not None:
            self._native_win.setVisible(False)
        self._set_idle(True)
        # Beim naechsten Sichtbarwerden muss wieder ein volles Bild kommen.
        self._dirty = True
        # ... und das erste Bild danach ist einmalig teuer (das Widget wird
        # neu layoutet). Ohne diesen Rueckstellpunkt zoege genau dieses eine
        # Bild den Tiefpass hoch und der Takt bliebe fuer ein bis zwei
        # Sekunden nach jedem Tabwechsel unnoetig langsam.
        self._adapt_calls = 0

    def _redraw(self) -> None:
        if self._plot is None or self._plotter is None:
            return
        # Sichtbarkeit zuerst, und ausdruecklich UNABHAENGIG von
        # enabled/overloaded: Legende und Statistikzeile stehen auch dann im
        # Bild, wenn der Plotter selbst abgeschaltet ist. Erst wenn der ganze
        # Tab weg ist, darf die Bruecke aufhoeren zu rechnen.
        sichtbar = self._on_screen()
        self._plotter.setStatsActive(sichtbar)
        if not self._plotter.enabled or self._plotter.overloaded:
            self._go_idle()
            return
        if not sichtbar:
            self._go_idle()
            return

        self._set_idle(False)
        self._plotter.setPlotActive(True)

        # Die Geometrie kann sich auch ohne neue Daten verschieben (Tabwechsel,
        # Layout) — das nachzuziehen ist billig und muss immer passieren.
        if self._mode == "native":
            self._sync_geometry()

        if not self._dirty:
            return                 # nichts Neues -> kein Bild, keine Last
        self._dirty = False

        # Das Messfenster muss den GANZEN Durchlauf umfassen — im Image-Modus
        # gehoert _render_to_pixmap() ausdruecklich dazu. Genau dort rastert
        # Qt das komplette Widget (Gitter, Achsen, alle Polylinien), und das
        # ist der teuerste Schritt ueberhaupt. Frueher endete die Messung
        # davor: der Waechter hat ein Budget von 80 ms ueberwacht, von dem er
        # den groessten Posten gar nicht gesehen hat, und der adaptive Takt
        # unten haette sich an einer Zahl orientiert, die nicht die Wahrheit
        # sagt.
        t0 = time.perf_counter()
        try:
            arrays = self._plotter.get_plot_arrays()
            self._update_curves(arrays)
            self._update_markers(arrays)
            self._update_frozen_overlay(arrays)
            if self._mode == "image":
                self._render_to_pixmap()
        except Exception as exc:  # noqa: BLE001
            log.warning("Plot-Redraw fehlgeschlagen: %s", exc)
            self._fail_to_error(f"Plot-Redraw fehlgeschlagen: {exc}")
            return
        dt = (time.perf_counter() - t0) * 1000.0

        if self._mode == "image":
            self.update()          # QQuickPaintedItem neu zeichnen lassen

        # Takt an die gemessene Dauer anpassen und sofort uebernehmen.
        self._adapt_interval(dt)
        self._set_idle(False)

        # Erst ganz zum Schluss melden: note_render() kann den Plotter
        # abschalten (Ueberlastung), und dann sollen die Kurven wenigstens
        # in dem Zustand stehenbleiben, den dieser Durchlauf erzeugt hat.
        self._plotter.note_render(dt)

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
            self._last_x_max = -1.0     # Achsen werden ohnehin neu aufgebaut
            self._last_y_range = None
            if shared and not self._quantize_y:
                self._plot.enableAutoRange(axis=_Y_AXIS, enable=True)
            else:
                self._plot.enableAutoRange(axis=_Y_AXIS, enable=False)
                if not shared:
                    # Normiert wird auf 0..1 — der Bereich steht damit fest
                    # und muss nie wieder angefasst werden.
                    self._plot.setYRange(-0.1, 1.1, padding=0.0)
        if shared and self._quantize_y:
            self._apply_shared_y_range()
        # setXRange stoesst ein vollstaendiges Neu-Layout der Achsen an. Die
        # Fensterbreite aendert sich aber nur beim Zoomen oder waehrend sich
        # der Ring fuellt — nicht in jedem Frame.
        if last > 0 and last != self._last_x_max:
            self._last_x_max = last
            self._plot.setXRange(0, last, padding=0.0)

    def _apply_shared_y_range(self) -> None:
        """Y-Bereich bei gemeinsamer Skala setzen — aber nur, wenn noetig.

        Wachsen sofort (sonst liefe die Kurve aus dem Bild), schrumpfen erst,
        wenn der aktuelle Bereich mehr als doppelt so gross ist wie noetig.
        Zusammen mit der 1-2-5-Rundung ergibt das eine Achse, die im
        Normalbetrieb minutenlang unveraendert stehen bleibt — und ein
        unveraenderter Bereich kostet gar nichts.
        """
        values = self._plotter.value_range()
        if values is None:
            return
        nice = nice_y_range(*values)
        if nice is None:
            return
        lo, hi = nice
        cur = self._last_y_range
        if cur is not None:
            clo, chi = cur
            passt = clo <= values[0] and values[1] <= chi
            if passt and (hi - lo) > 0.5 * (chi - clo):
                return
        self._last_y_range = (lo, hi)
        self._plot.setYRange(lo, hi, padding=0.0)

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

    def _marker_pen(self, level: int):
        """Stift je Markenstufe — einmal angelegt, dann wiederverwendet.

        pg.mkPen() baut jedes Mal einen neuen QPen (und parst die Farbe);
        vorher passierte das für JEDE Marke in JEDEM Frame.
        """
        if not self._pen_cache:
            self._pen_cache = [
                pg.mkPen(c, width=1.2, style=Qt.PenStyle.DashLine)
                for c in _MARKER_COLORS
            ]
        return self._pen_cache[min(level, len(self._pen_cache) - 1)]

    def _update_markers(self, arrays) -> None:
        marks = self._plotter.visible_markers(self._plotter.pointsCount)
        if not marks and not self._marker_lines:
            return                    # Normalfall: keine Marken, nichts zu tun
        n = len(arrays[0][0]) if arrays else 0
        last = max(0, n - 1)
        # Pool nur so weit vergrößern, wie wirklich Marken da sind (früher
        # immer mindestens acht Linien samt Textobjekt in der Szene, auch
        # ohne eine einzige Marke). Mit label="" wird das Label-Objekt
        # angelegt (InfiniteLine.label), das wir unten mit Text fuellen.
        while len(self._marker_lines) < len(marks):
            line = pg.InfiniteLine(angle=90, movable=False, label="")
            self._plot.addItem(line)
            self._marker_lines.append(line)
            self._mark_state.append(None)
        for i, (pos, text, level) in enumerate(marks):
            # Marken stehen fest im Verlauf; solange sich Position, Text und
            # Stufe nicht ändern, ist jedes Anfassen der Linie verlorene
            # Arbeit — label.setText() rendert den Text komplett neu.
            state = (pos * last, text, level)
            if self._mark_state[i] == state:
                continue
            self._mark_state[i] = state
            line = self._marker_lines[i]
            line.setVisible(True)
            try:
                line.setValue(state[0])
                line.setPen(self._marker_pen(level))
                label = getattr(line, "label", None)
                if label is not None and text:
                    label.setText(text)
                    label.setColor(
                        QColor(*_MARKER_COLORS[min(level, len(_MARKER_COLORS) - 1)]))
            except Exception:
                pass
        for i in range(len(marks), len(self._marker_lines)):
            if self._mark_state[i] is not None:
                self._mark_state[i] = None
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
        n = live.shape[1]
        # Gleiche x-Achse wie die Hauptkurven (dasselbe zwischengespeicherte
        # Array) und ein eigener, mitwachsender y-Puffer statt vier frischer
        # Arrays pro Frame.
        xs = self._plotter.x_axis(n)
        if self._live_ys is None or self._live_ys.shape[0] < n:
            self._live_ys = np.empty(n, dtype=np.float32)
        ys = self._live_ys[:n]
        series = live[0]
        if shared:
            np.copyto(ys, series)
        else:
            finite = np.isfinite(series)
            if finite.any():
                mn = float(series.min(where=finite, initial=np.inf))
                mx = float(series.max(where=finite, initial=-np.inf))
                span = (mx - mn) or 1.0
                np.subtract(series, mn, out=ys)
                np.multiply(ys, np.float32(1.0 / span), out=ys)
            else:
                ys.fill(0.0)
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
        size = QSize(w, h)
        if self._pixmap is None or self._pixmap.size() != size:
            self._pixmap = QPixmap(size)
            # Ein frisches QPixmap ist uninitialisiert; einmal Grundfarbe,
            # danach ueberdeckt jeder Render den ganzen Bereich.
            self._pixmap.fill(QColor("#1a1a1a"))
        if self._plot_size != size:
            self._plot_size = size
            self._plot.resize(w, h)

        # QWidget.grab() legt bei JEDEM Aufruf ein neues QPixmap an — bei
        # 800x400 gut 1,3 MB, 20-mal pro Sekunde. Intern macht grab() nichts
        # anderes als QWidget.render() in genau so ein Pixmap; das rufen wir
        # direkt auf und behalten das Pixmap.
        #
        # Es muss ausdruecklich QWidget.render sein: self._plot ist ein
        # pyqtgraph.PlotWidget (QGraphicsView-Subklasse), und
        # QGraphicsView.render() verdeckt die Ueberladungen von QWidget mit
        # einer voellig anderen Signatur (painter, target: QRectF,
        # source: QRect, aspectRatioMode).
        try:
            QWidget.render(
                self._plot, self._pixmap, QPoint(0, 0), QRegion(),
                QWidget.RenderFlag.DrawWindowBackground
                | QWidget.RenderFlag.DrawChildren,
            )
        except Exception as exc:  # noqa: BLE001
            # Fallback auf den teuren, aber maximal robusten Weg.
            log.warning("Pixmap-Render fehlgeschlagen (%s) — grab() als Ersatz.", exc)
            try:
                grabbed = self._plot.grab(QRect(0, 0, w, h))
                if not grabbed.isNull():
                    self._pixmap = grabbed
            except Exception as exc2:  # noqa: BLE001
                log.warning("Auch grab() fehlgeschlagen: %s", exc2)
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
        self._mark_state.clear()
        self._live_curve = None
        if self._plot is not None:
            try:
                self._plot.clear()
            except Exception:
                pass
        self._last_shared = None
        self._last_x_max = -1.0
        self._last_y_range = None
        # Beim nächsten Redraw werden die Kurven neu erzeugt.
        self._dirty = True
        if self._mode == "image":
            self.update()

    def _on_frozen_changed(self) -> None:
        self._dirty = True
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
            # Der Timer laeuft nicht mehr, es kommt also keine Meldung ueber
            # die Sichtbarkeit nach. Im Fehler-Modus ist die Legende das
            # Einzige, was noch Zahlen zeigt — die darf nicht stehenbleiben.
            self._plotter.setStatsActive(True)
        self.update()

    # ── Paint (Image-/Fehler-Modus; native zeichnet selbst) ────────────────
    def paint(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        if self._mode == "image":
            # Mit setOpaquePainting(True) raeumt Qt Quick den Hintergrund
            # nicht mehr auf — solange noch kein Bild da ist, muss deshalb
            # hier gefuellt werden, sonst stuenden Speicherreste im Item.
            if self._pixmap is not None and not self._pixmap.isNull():
                # Das Pixmap wird in Item-Groesse gerendert; dann ist das ein
                # glattes Kopieren. Nur wenn die Groesse gerade nachzieht
                # (ein Frame lang nach dem Umschalten), wird skaliert — das
                # ist der deutlich teurere Weg.
                if self._pixmap.size() == QSize(int(w), int(h)):
                    painter.drawPixmap(0, 0, self._pixmap)
                else:
                    painter.drawPixmap(QRectF(0, 0, w, h), self._pixmap,
                                        QRectF(self._pixmap.rect()))
            else:
                painter.fillRect(QRectF(0, 0, w, h), QColor("#1a1a1a"))
        elif self._mode == "error":
            painter.fillRect(QRectF(0, 0, w, h), QColor("#1a1a1a"))
            painter.setPen(QColor("#f48771"))
            painter.drawText(QRectF(0, 0, w, h),
                             Qt.AlignmentFlag.AlignCenter,
                             "Plotter nicht verfügbar:\n" + self._error_text)
        # native: transparent — das Widget liegt als Kindfenster darüber.
