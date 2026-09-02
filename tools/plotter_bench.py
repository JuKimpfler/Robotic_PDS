#!/usr/bin/env python3
"""
tools/plotter_bench.py — Messwerkzeug fuer den Live-Plotter
===========================================================
Im Repository gilt: eine Optimierung wird mit einer Zahl belegt, nicht mit
einem Adjektiv. Dieses Werkzeug erzeugt genau diese Zahlen — getrennt nach
den drei Ebenen, die sich voellig unterschiedlich verhalten:

  1. DATENPFAD   append_block() + get_plot_arrays(), ohne jedes Zeichnen.
                 Rund 5 % der Plotter-Last, aber der einzige Teil, der im
                 100-Hz-Datentakt laeuft.
  2. RASTERN     ein vollstaendiger _redraw() des echten Hosts im
                 Bild-Modus, INKLUSIVE _render_to_pixmap(). Rund 95 % der
                 Last. Das Messfenster von note_render() endete frueher vor
                 dem Pixmap-Rendern — der teuerste Schritt ging damit in
                 keiner Zahl auf.
  3. LEGENDE     ein echter QML-Repeater ueber curveInfo. Jedes
                 statsChanged laesst QML alle Delegates zerstoeren und neu
                 erzeugen; wie teuer das ist, entscheidet darueber, ob sich
                 ein QAbstractListModel lohnt.

Dazu `--verify`: Wert-fuer-Wert-Vergleiche, die belegen, dass die
Sparmassnahmen das ERGEBNIS nicht veraendert haben. Diese Stufe braucht
kein pyqtgraph und laeuft deshalb in der CI mit.

Aufruf
------
    python tools/plotter_bench.py              alles, was hier moeglich ist
    python tools/plotter_bench.py --verify     nur die Wert-Vergleiche
    python tools/plotter_bench.py --data       nur den Datenpfad
    python tools/plotter_bench.py --render     nur das Rastern
    python tools/plotter_bench.py --legend     nur die QML-Legende

Exit-Code 0 = alles in Ordnung (bei --verify: alle Vergleiche bestanden).

Auf dem Zielgeraet gehoert daneben ein `pidstat -p <GUI-PID> 1`: die
eigentliche Anforderung ist nicht "der Plotter ist schnell", sondern "der
Plotter bremst den 100-Hz-Sendetakt der Fernsteuerung nicht".
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rpi5_monitor" / "64Bit_Version"))
sys.path.insert(0, str(ROOT / "shared"))

# Muss vor dem ersten Qt-Import stehen.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_failures: list[str] = []
_checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    if condition:
        print(f"  [ ok ] {name}")
    else:
        print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")
        _failures.append(name)


def section(title: str) -> None:
    print(f"\n== {title} ==")


def _need(*mods: str) -> bool:
    """True, wenn alle Module wirklich ladbar sind.

    Wie im Selbsttest ausdruecklich importieren statt find_spec(): PyQt6
    kann vollstaendig installiert sein und sich trotzdem nicht laden lassen,
    weil die Qt-Systembibliotheken fehlen.
    """
    import importlib
    for mod in mods:
        try:
            importlib.import_module(mod)
        except Exception as exc:            # noqa: BLE001
            print(f"  [ -- ] uebersprungen: {mod} laesst sich nicht laden ({exc})")
            return False
    return True


def _ms(values: list[float]) -> str:
    """Median, Minimum und Maximum einer Messreihe in ms."""
    v = sorted(values)
    return (f"{statistics.median(v) * 1000:7.3f} ms  "
            f"(min {v[0] * 1000:6.3f}  max {v[-1] * 1000:6.3f})")


# ══════════════════════════════════════════════════════════════════════════
#  Wert-fuer-Wert-Vergleiche (--verify) — brauchen kein pyqtgraph
# ══════════════════════════════════════════════════════════════════════════
def verify() -> None:
    section("Wert-fuer-Wert: die Sparmassnahmen aendern das Ergebnis nicht")
    if not _need("numpy", "PyQt6.QtCore", "PyQt6.QtGui"):
        return
    import numpy as np
    import bridge.plot_bridge as pbm
    from bridge.app_bridge import AppBridge
    from config import MAX_FLOATS

    rng = np.random.default_rng(20260901)

    # ── 1) Ringpuffer gegen eine schlichte Referenz ───────────────────────
    #  Die Referenz haelt einfach eine Liste — langsam, aber offensichtlich
    #  richtig. Der Ringpuffer muss dasselbe Fenster liefern.
    pb = pbm.PlotBridge()
    pb.setChannels([0, 3, 5])
    pb.setPointsCount(120)
    referenz: list[list[float]] = [[], [], []]
    for _ in range(60):
        blk = rng.standard_normal((7, MAX_FLOATS)).astype(np.float32)
        pb.append_block(blk)
        for row, chn in enumerate((0, 3, 5)):
            referenz[row].extend(float(v) for v in blk[:, chn])
    fenster = pb.snapshot()
    erwartet = np.array([r[-120:] for r in referenz], dtype=np.float32)
    check("Ringpuffer liefert dasselbe Fenster wie eine Listen-Referenz",
          np.array_equal(fenster, erwartet),
          f"{fenster.shape} vs {erwartet.shape}")

    # ── 2) _stack(): neuer Puffer gegen die alte Fassung ──────────────────
    def stack_alt(batch):
        n = len(batch)
        width = max(v.shape[0] for v in batch)
        if n == 1:
            return batch[0].reshape(1, -1)
        block = np.full((n, width), np.nan, dtype=np.float32)
        for i, v in enumerate(batch):
            block[i, :v.shape[0]] = v
        return block

    class _NurStack:
        _stack = AppBridge._stack

    halter = _NurStack()
    halter._stack_buf = None
    gleich = True
    for _ in range(300):
        batch = [rng.standard_normal(int(rng.integers(1, MAX_FLOATS + 1))
                                     ).astype(np.float32)
                 for _ in range(int(rng.integers(1, 7)))]
        if not np.array_equal(halter._stack(batch), stack_alt(batch),
                              equal_nan=True):
            gleich = False
            break
    check("_stack(): Puffer-Fassung wertgleich zur alten (300 Batches, NaN mit)",
          gleich)

    # ── 3) Normierung: gepufferte Grenzen gegen die Rechnung je Bild ──────
    def kurven(cache: bool):
        pbm._CACHE_NORM_BOUNDS = cache
        lokal = np.random.default_rng(4711)
        br = pbm.PlotBridge()
        br.setChannels([0, 1, 2, 3])
        br.setPointsCount(200)
        raus = []
        for k in range(80):
            br.append_block((lokal.standard_normal((5, MAX_FLOATS)) * (k + 1)
                             ).astype(np.float32))
            br._refresh_stats()      # Statistik-Takt erzwingen
            raus.append([y.copy() for _, y in br.get_plot_arrays()])
        return raus

    try:
        mit, ohne = kurven(True), kurven(False)
        check("get_plot_arrays(): gepufferte Grenzen wertgleich, "
              "solange die Statistik frisch ist",
              all(np.array_equal(a, b, equal_nan=True)
                  for fa, fb in zip(mit, ohne) for a, b in zip(fa, fb)))

        # ── 4) ... und die Kurve bleibt auch bei harten Pegelspruengen im Bild
        pbm._CACHE_NORM_BOUNDS = True
        lokal = np.random.default_rng(99)
        br = pbm.PlotBridge()
        br.setChannels([0, 1])
        br.setPointsCount(200)
        lo, hi = 1.0, 0.0
        for k in range(400):
            amp = 3.0 * (10 ** (k // 50))       # alle 50 Bloecke Faktor 10
            br.append_block((lokal.standard_normal((5, MAX_FLOATS)) * amp
                             ).astype(np.float32))
            for _, y in br.get_plot_arrays():
                lo = min(lo, float(np.nanmin(y)))
                hi = max(hi, float(np.nanmax(y)))
        check("gepufferte Grenzen halten die Kurve auch bei Pegelspruengen "
              "in 0..1", -1e-6 <= lo and hi <= 1.0 + 1e-6, f"{lo:.4f} .. {hi:.4f}")
    finally:
        pbm._CACHE_NORM_BOUNDS = bool(
            __import__("app_settings").get("plotter.cacheNormBounds", True))

    # ── 5) Trigger: Puffer-Fassung gegen eine Schleifen-Referenz ──────────
    def referenz_trigger(werte, modus, level, delta):
        """Dieselbe Bedingung, aber Wert fuer Wert in Python."""
        prev = float("nan")
        for i, v in enumerate(werte):
            treffer = {
                "above":   v > level,
                "below":   v < level,
                "rising":  prev <= level < v,
                "falling": prev >= level > v,
                "change":  abs(v - prev) >= delta,
                "outside": abs(v - level) > delta,
            }[modus]
            prev = v
            if treffer:
                return i
        return None

    alle_gleich = True
    details = ""
    for modus in pbm.TRIGGER_MODES:
        for versuch in range(20):
            werte = (rng.standard_normal(9) * 2.0).astype(np.float32)
            br = pbm.PlotBridge()
            br.setPointsCount(100)
            br.setTriggerChannel(0)
            br.setTriggerMode(modus)
            br.setTriggerLevel(0.5)
            br.setTriggerDelta(1.0)
            br.setTriggerMarkOnly(True)
            br.setTriggerEnabled(True)
            blk = np.zeros((9, MAX_FLOATS), dtype=np.float32)
            blk[:, 0] = werte
            br.append_block(blk)
            soll = referenz_trigger([float(v) for v in werte], modus, 0.5, 1.0)
            ist = br._trig_fired_at
            if soll != ist:
                alle_gleich = False
                details = f"{modus}/{versuch}: Referenz {soll}, Bruecke {ist}"
                break
        if not alle_gleich:
            break
    check("Trigger: Puffer-Fassung loest an derselben Stelle aus wie eine "
          "Schleifen-Referenz (6 Modi x 20 Bloecke)", alle_gleich, details)

    # ── 6) Hilfsfunktionen des Hosts ──────────────────────────────────────
    if _need("PyQt6.QtQuick"):
        import math
        from bridge.plot_host import nice_y_range, adaptive_interval

        enthalten = True
        for _ in range(500):
            a, b = (rng.standard_normal(2) * 10.0 ** rng.integers(-6, 7))
            r = nice_y_range(float(a), float(b))
            if r is None or not (r[0] <= min(a, b) and max(a, b) <= r[1]):
                enthalten = False
                break
        check("nice_y_range() enthaelt immer die Daten (500 Zufallsbereiche)",
              enthalten)
        check("nice_y_range() weist unbrauchbare Zahlen ab",
              nice_y_range(float("nan"), 1.0) is None
              and nice_y_range(0.0, float("inf")) is None)

        in_grenzen = all(
            83 <= adaptive_interval(ms, 83, 250, 4.0, 83) <= 250
            for ms in (0.1, 1, 5, 12, 30, 60, 200, 5000))
        check("adaptive_interval() bleibt zwischen maxFps und minFps",
              in_grenzen)
        werte = {adaptive_interval(ms, 83, 250, 4.0, 100)
                 for ms in (24.0, 25.0, 26.0, 24.5, 25.5)}
        check("adaptive_interval() springt bei kleinen Lastwechseln nicht",
              len(werte) == 1, str(werte))
        check("adaptive_interval() kehrt an den Anschlag zurueck",
              adaptive_interval(2.0, 83, 250, 4.0, 96) == 83)
        check("adaptive_interval() ignoriert unbrauchbare Messungen",
              adaptive_interval(0.0, 83, 250, 4.0, 120) == 120
              and adaptive_interval(math.nan, 83, 250, 4.0, 120) == 120)


# ══════════════════════════════════════════════════════════════════════════
#  1) Datenpfad
# ══════════════════════════════════════════════════════════════════════════
def bench_data(pakete: int = 2000) -> None:
    section(f"1) Datenpfad — {pakete} Pakete a 5 Samples (100 Hz, 20-Hz-Poll)")
    if not _need("numpy", "PyQt6.QtCore", "PyQt6.QtGui"):
        return
    import numpy as np
    import bridge.plot_bridge as pbm
    from config import MAX_FLOATS

    print("  Kurven  Modus         append_block            get_plot_arrays")
    for n_kurven in (1, 4, 8):
        for modus, shared in (("normiert", False), ("gemeinsam", True)):
            br = pbm.PlotBridge()
            br.setChannels(list(range(n_kurven)))
            br.setSharedScale(shared)
            br.setPointsCount(500)
            rng = np.random.default_rng(1)
            bloecke = [rng.standard_normal((5, MAX_FLOATS)).astype(np.float32)
                       for _ in range(pakete)]
            for b in bloecke[:200]:                     # aufwaermen
                br.append_block(b)
                br.get_plot_arrays()

            t_app: list[float] = []
            t_get: list[float] = []
            for b in bloecke:
                t0 = time.perf_counter()
                br.append_block(b)
                t1 = time.perf_counter()
                br.get_plot_arrays()
                t2 = time.perf_counter()
                t_app.append(t1 - t0)
                t_get.append(t2 - t1)
            print(f"  {n_kurven:>6}  {modus:<11}  {_ms(t_app)}  {_ms(t_get)}")


# ══════════════════════════════════════════════════════════════════════════
#  2) Rastern — der echte Host im Bild-Modus
# ══════════════════════════════════════════════════════════════════════════
def bench_render(bilder: int = 200, breite: int = 800, hoehe: int = 400) -> None:
    section(f"2) Rastern — {bilder} vollstaendige _redraw() im Bild-Modus "
            f"({breite}x{hoehe})")
    if not _need("numpy", "PyQt6.QtWidgets", "pyqtgraph"):
        return
    import numpy as np
    from PyQt6.QtWidgets import QApplication
    import bridge.plot_bridge as pbm
    from bridge.plot_host import PyQtGraphHost
    from config import MAX_FLOATS

    # Muss existieren und am Leben bleiben, solange Widgets leben.
    _app = QApplication.instance() or QApplication([])
    assert _app is not None

    def einen_lauf(n_kurven: int, punkte: int, shared: bool,
                   quantize: bool) -> tuple[float, int, int]:
        br = pbm.PlotBridge()
        br.setChannels(list(range(n_kurven)))
        br.setSharedScale(shared)
        br.setPointsCount(punkte)
        host = PyQtGraphHost()
        host.setWidth(breite)
        host.setHeight(hoehe)
        host._plotter = br
        host._quantize_y = quantize
        # Genau der Aufbau der Anwendung — auf der Plattform "offscreen"
        # scheitert die native Einbettung und der Host geht in den
        # Bild-Modus, also in den Pfad mit _render_to_pixmap().
        host._build_plot()
        host._built = True
        if host.mode != "image":
            return float("nan"), 0, 0

        rng = np.random.default_rng(3)
        vb = host._plot.getViewBox()
        bereiche = 0
        letzter = None

        def block(k):
            basis = 12.0 + 0.4 * np.sin(k / 30.0)
            return (basis + rng.standard_normal((8, MAX_FLOATS)) * 0.05
                    ).astype(np.float32)

        # Fenster vollaufen lassen: solange es waechst, laeuft in jedem Bild
        # ein setXRange, und das misst man sonst mit.
        for k in range(punkte // 8 + 30):
            br.append_block(block(k))
            host._redraw()

        t0 = time.perf_counter()
        for k in range(bilder):
            br.append_block(block(k))
            host._dirty = True
            host._redraw()
            jetzt = tuple(round(v, 9) for v in vb.viewRange()[1])
            if jetzt != letzter:
                bereiche += 1
                letzter = jetzt
        dt = (time.perf_counter() - t0) / bilder * 1000.0
        # Die Zahl der Y-Ticks erklaert die Rasterzeit besser als alles
        # andere: jeder Tick ist eine Gitterlinie, jeder beschriftete Tick
        # zusaetzlich ein Stueck gerasterter Text.
        achse = host._plot.getAxis("left")
        stufen = achse.tickValues(*achse.range, achse.height()) or []
        return dt, bereiche, sum(len(t[1]) for t in stufen)

    print("  Kurven  Punkte  Modus                     ms/Bild")
    for n_kurven in (1, 4, 8):
        for punkte in (250, 500, 600):
            dt, _, _ = einen_lauf(n_kurven, punkte, False, True)
            print(f"  {n_kurven:>6}  {punkte:>6}  normiert                "
                  f"{dt:8.2f}")
    print("  Der Abstand zwischen 1x250 und 8x600 ist klein gegen den")
    print("  Grundbetrag: das meiste kostet nicht die Kurve, sondern das")
    print("  Rastern von Hintergrund, Gitter und Achsen (Plan: K2/M8).")

    print()
    print("  Gemeinsame Skala: was der quantisierte Y-Bereich bringt")
    # Ein Durchlauf je Variante reicht hier NICHT: der Unterschied liegt in
    # derselben Groessenordnung wie die Streuung zwischen zwei Durchlaeufen.
    # Deshalb abwechselnd wiederholen und den Median nehmen — sonst misst man
    # die Tageslaune des Rechners und nicht die Aenderung.
    runden = 6
    ergebnis: dict[bool, list[float]] = {False: [], True: []}
    bereiche_je: dict[bool, int] = {}
    ticks_je: dict[bool, int] = {}
    for i in range(runden * 2):
        quantize = bool(i % 2)
        dt, bereiche, ticks = einen_lauf(4, 500, True, quantize)
        ergebnis[quantize].append(dt)
        bereiche_je[quantize] = bereiche
        ticks_je[quantize] = ticks
    print("  Kurven  Punkte  Modus                     ms/Bild   Y neu   Ticks")
    for quantize in (False, True):
        v = sorted(ergebnis[quantize])
        name = "quantisiert" if quantize else "autoRange"
        print(f"  {4:>6}  {500:>6}  gemeinsam, {name:<13}"
              f"{statistics.median(v):8.2f}  {bereiche_je[quantize]:>3}/{bilder}"
              f"   {ticks_je[quantize]:>3}"
              f"   (min {v[0]:.2f}  max {v[-1]:.2f})")
    streuung = max(max(ergebnis[False]) - min(ergebnis[False]),
                   max(ergebnis[True]) - min(ergebnis[True]))
    unterschied = abs(statistics.median(ergebnis[True])
                      - statistics.median(ergebnis[False]))
    print(f"  Streuung innerhalb einer Variante: {streuung:.2f} ms, "
          f"Unterschied zwischen beiden: {unterschied:.2f} ms.")
    if unterschied <= streuung:
        print("  -> Der Zeitunterschied liegt im Rauschen DIESER Umgebung.")
        print("     Belegt ist nur die Zahl der Bereichswechsel; ob daraus")
        print("     Rechenzeit wird, ist auf dem Zielgeraet zu messen.")


# ══════════════════════════════════════════════════════════════════════════
#  3) QML-Legende
# ══════════════════════════════════════════════════════════════════════════
_LEGEND_QML = """
import QtQuick
Item {
    width: 600; height: 60
    property var bridge: null
    Flow {
        anchors.fill: parent
        Repeater {
            model: parent.parent.bridge ? parent.parent.bridge.curveInfo : []
            delegate: Row {
                required property var modelData
                Rectangle { width: 18; height: 4; color: modelData.color }
                Text {
                    text: modelData.name + "  " + (modelData.valid
                          ? modelData.last.toFixed(3) + " ("
                            + modelData.min.toFixed(2) + " bis "
                            + modelData.max.toFixed(2) + ")" : "—")
                }
            }
        }
    }
}
"""


def bench_legend(runden: int = 300) -> None:
    section(f"3) QML-Legende — {runden} x statsChanged, echter Repeater")
    if not _need("numpy", "PyQt6.QtQml", "PyQt6.QtQuick"):
        return
    import tempfile
    import numpy as np
    from PyQt6.QtCore import QCoreApplication, QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlComponent, QQmlEngine
    import bridge.plot_bridge as pbm
    from config import MAX_FLOATS

    _app = QGuiApplication.instance() or QGuiApplication([])
    assert _app is not None
    engine = QQmlEngine()
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(tmp) / "Legende.qml"
        pfad.write_text(_LEGEND_QML, encoding="utf-8")
        comp = QQmlComponent(engine, QUrl.fromLocalFile(str(pfad)))
        if comp.isError():
            print("  [ -- ] uebersprungen: QML liess sich nicht laden — "
                  + "; ".join(e.toString() for e in comp.errors()))
            return
        item = comp.create()
        if item is None:
            print("  [ -- ] uebersprungen: QML-Objekt liess sich nicht erzeugen")
            return

        for n_kurven in (1, 4, 8):
            br = pbm.PlotBridge()
            br.setChannels(list(range(n_kurven)))
            br.setPointsCount(500)
            rng = np.random.default_rng(5)
            for _ in range(120):
                br.append_block(rng.standard_normal((5, MAX_FLOATS)
                                                    ).astype(np.float32))
            item.setProperty("bridge", br)
            QCoreApplication.processEvents()

            zeiten: list[float] = []
            for _ in range(runden):
                br._refresh_stats()
                t0 = time.perf_counter()
                br.statsChanged.emit()
                QCoreApplication.processEvents()
                zeiten.append(time.perf_counter() - t0)
            print(f"  {n_kurven:>2} Kurven  Delegates neu aufbauen: "
                  f"{_ms(zeiten)}")
    del item


# ══════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Messwerkzeug fuer den Live-Plotter.")
    ap.add_argument("--verify", action="store_true",
                    help="nur die Wert-fuer-Wert-Vergleiche (ohne pyqtgraph)")
    ap.add_argument("--data", action="store_true", help="nur den Datenpfad")
    ap.add_argument("--render", action="store_true", help="nur das Rastern")
    ap.add_argument("--legend", action="store_true", help="nur die QML-Legende")
    args = ap.parse_args()

    einzeln = args.verify or args.data or args.render or args.legend
    print("Power Debug System — Plotter-Messung")
    print(f"Qt-Plattform: {os.environ.get('QT_QPA_PLATFORM', '(Vorgabe)')}")

    if args.verify or not einzeln:
        verify()
    if args.data or not einzeln:
        bench_data()
    if args.render or not einzeln:
        bench_render()
    if args.legend or not einzeln:
        bench_legend()

    print(f"\n{'=' * 62}")
    if _failures:
        print(f"{len(_failures)} von {_checks} Vergleichen FEHLGESCHLAGEN:")
        for f in _failures:
            print(f"  * {f}")
        return 1
    if _checks:
        print(f"Alle {_checks} Vergleiche bestanden.")
    else:
        print("Messung beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
