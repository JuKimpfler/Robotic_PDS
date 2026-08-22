#!/usr/bin/env python3
"""
tools/qml_smoketest.py — die komplette Oberflaeche einmal wirklich starten
============================================================================
Startet Main.qml mit dem echten Backend in einem Offscreen-Fenster, fuettert
synthetische Daten hinein, bedient ein paar Schalter und beendet sich wieder.
JEDE Qt-Warnung waehrend des Laufs gilt als Fehler.

WARUM: tools/check_qml_bindings.py prueft statisch, ob ein Zugriff wie
`appBridge.diag.linkStats` in Python existiert. Es kann aber nicht wissen, ob
eine QML-Datei ueberhaupt uebersetzt (Syntaxfehler, unbekannte Property,
falscher Typ) oder ob eine Bindung zur Laufzeit auf `undefined` laeuft. Genau
das faengt dieser Test — und zwar ohne Bildschirm, ohne Teensy und ohne Node.

Durchgespielt wird auch der Overlay-Editor: alle sieben Element-Arten
anlegen (damit FieldEditor jeden Feldtyp einmal rendert), im Bild ziehen,
Reihenfolge, Kopie, Loeschen, Rueckgaengig, Gruppen, Speichern/Verwerfen und
die Rueckfrage bei einer neuen Teensy-Anordnung.

Netzwerkprozesse werden bewusst NICHT gestartet (NetworkManager wird nur
angelegt): in einer CI-Umgebung sind UDP-Ports unzuverlaessig, und der Test
soll die Oberflaeche pruefen, nicht das Netzwerk.

Aufruf:
    python tools/qml_smoketest.py
Exit-Code 0 = die Oberflaeche laedt und laeuft warnungsfrei.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Muessen VOR dem Qt-Import gesetzt sein.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")   # kein OpenGL noetig
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "rpi5_monitor" / "64Bit_Version"
sys.path.insert(0, str(GUI))

# Der Test speichert (Einstellungen, Overlay-Editor). Das darf NICHT in die
# echte Konfiguration des Geraets laufen — sonst haette ein Testlauf auf dem
# RPi 5 die Anordnung des Bedieners ueberschrieben. config.runtime_config_path
# liest RUNTIME_CONFIG_DIR bei jedem Aufruf aus dem Modul-Namensraum, deshalb
# genuegt es, den Namen VOR dem Import der Bruecken umzubiegen.
import tempfile                                              # noqa: E402
import config                                                # noqa: E402
_tmp_cfg = tempfile.TemporaryDirectory(prefix="pds-smoketest-")
config.RUNTIME_CONFIG_DIR = Path(_tmp_cfg.name)
config.UI_SETTINGS_PATH = config.RUNTIME_CONFIG_DIR / "ui_settings.json"

import numpy as np                                          # noqa: E402
from PyQt6.QtCore import QTimer, QUrl                       # noqa: E402
from PyQt6.QtGui import QGuiApplication                     # noqa: E402
from PyQt6.QtQml import (QQmlApplicationEngine,             # noqa: E402
                          qmlRegisterType, qmlRegisterSingletonType)

from network_worker import NetworkManager                   # noqa: E402
from bridge.app_bridge import AppBridge                     # noqa: E402
from bridge.plot_bridge import PlotCanvas                   # noqa: E402

QML_DIR = GUI / "qml"

_warnings: list[str] = []


def _exercise(bridge: AppBridge) -> None:
    """Alles anfassen, was eine QML-Bindung auszuwerten zwingt."""
    rng = np.random.default_rng(1234)

    # Telemetrie: ein Block wie ihn app_bridge._stack() baut
    block = rng.normal(0.0, 5.0, (5, 64)).astype(np.float32)
    bridge._telemetry.update_data(block[-1])
    bridge._plotter.append_block(block)
    bridge._diag.note_values(block[-1])
    bridge._diag.note_packet(1, 10_000)
    bridge._diag.note_packet(1, 20_000)
    bridge._diag.note_pps(1, 100)

    # Aux-Uplink
    bridge._diag.apply_event(1, {"kind": 0, "level": 0, "text": "Marke", "value": 1.0,
                                  "ts_us": 12345})
    bridge._diag.apply_event(1, {"kind": 1, "level": 2, "text": "Fehler", "value": 0.0,
                                  "ts_us": 12346})
    bridge._diag.apply_node_status(1, {
        "node_id": 1, "teensy_link": True, "wifi_ok": True, "unicast": True,
        "cpu_temp_c": 51.0, "load1": 0.4, "mem_used_pct": 38.0,
        "wifi_rssi_dbm": -57.0, "uptime_s": 7200, "uart_packets": 1000,
        "sync_losses": 0, "udp_tx": 1000,
    })
    bridge._params.apply_ack(1, {
        "slow_seq": 1, "fast_seq": 2, "slow_age_ms": 100, "fast_age_ms": 5,
        "floats": tuple(0.0 for _ in range(50)),
        "bools": tuple(False for _ in range(50)),
        "fast_floats": tuple(0.0 for _ in range(5)),
    })

    # Bedienung
    bridge._telemetry.setFilter("var")
    bridge._telemetry.setFilter("")
    bridge._plotter.setChannels([0, 1, 2, 3])
    bridge._plotter.setSharedScale(True)
    bridge._plotter.setTriggerEnabled(True)
    bridge._plotter.setTriggerMode("rising")
    bridge._plotter.setTriggerLevel(0.5)
    bridge._plotter.append_block(block)
    bridge._plotter.setTriggerEnabled(False)
    bridge._plotter.setFrozen(True)
    bridge._plotter.setFrozen(False)

    bridge._settings.setDark(False)
    bridge._settings.setFontScale(1.3)
    bridge._settings.setKiosk(True)
    bridge._settings.setKiosk(False)
    bridge._settings.setDark(True)
    bridge._settings.setFontScale(1.0)

    # hold_seconds=0: sonst wuerde die Haltezeit den Alarm im kurzen Testlauf
    # unterdruecken und der Alarmrahmen nie gezeichnet.
    bridge._diag.setBatteryConfig({"enabled": True, "channel": 0,
                                    "warn_below": 1e9, "critical_below": 1e9,
                                    "hold_seconds": 0.0})
    bridge._diag.note_values(block[-1])
    bridge._diag.note_values(block[-1])
    bridge._diag.setBatteryConfig({"enabled": False})
    bridge._diag.setEventFilter(1)
    bridge._diag.setEventFilter(0)

    bridge._params.setSlowFloat(0, 1.25)
    bridge._params.setSlowBool(0, True)
    bridge._params.setKeyboardAxes(1.0, 0.5, 0.0, 1.0, 0.0)
    bridge._params.setKeyboardAxes(0.0, 0.0, 0.0, 0.0, 0.0)
    bridge._params.undo()
    bridge._params.stopAll()

    bridge.setActiveNode(2)
    bridge.setActiveNode(1)


def _exercise_editor(bridge: AppBridge) -> list:
    """Schritte des Overlay-Editors — je einer pro Zeitscheibe.

    Einzeln und nicht am Stueck, weil QML die Delegates erst beim naechsten
    Durchlauf der Ereignisschleife neu aufbaut. Ein Formularfeld, das nie
    erzeugt wurde, kann auch keine Warnung ausloesen — der Test wuerde gruen
    melden, ohne etwas geprueft zu haben.
    """
    v = bridge._visuals
    steps = [lambda: v.setEditing(True)]

    # Jede der sieben Arten anlegen: addEntry() waehlt den neuen Eintrag
    # gleich aus, damit rendert FieldEditor JEDEN Feldtyp mindestens einmal.
    import overlay_schema
    for kind in overlay_schema.OVERLAY_KINDS + overlay_schema.GRAPHIC_KINDS:
        steps.append(lambda k=kind: v.addEntry(k))

    steps += [
        # Ziehen im Bild (relativ, wie DragHandler es meldet)
        lambda: v.select("overlays", 0),
        lambda: v.moveOverlayBy(0, 7.5, -3.25),
        lambda: v.moveOverlayBy(0, -500.0, 500.0),      # Begrenzung
        # Formularfelder aller Typen setzen
        lambda: v.setField("label", "Testname"),
        lambda: v.setField("x_pct", "12,5"),            # deutsches Komma
        lambda: v.setField("color", "#f0c060"),
        lambda: v.select("overlays", 1),                # Textraster
        lambda: v.setField("channels", "0-11,20"),
        lambda: v.setField("cols", "3"),
        lambda: v.setField("labels", False),
        lambda: v.select("graphics", 4),                # Feldansicht
        lambda: v.setField("body1.label", "Roboter"),
        lambda: v.setField("body1.channel_x", 3),       # nur x -> Warnhinweis
        lambda: v.setField("field_x_cm", 180),
        # Reihenfolge, Kopie, Loeschen, Rueckgaengig
        lambda: v.moveSelectedInList(-1),
        lambda: v.duplicateSelected(),
        lambda: v.removeSelected(),
        lambda: v.undo(),
        lambda: v.clearSelection(),
        # Gruppen
        lambda: v.addGroup(),
        lambda: v.renameGroup("Testgruppe"),
        lambda: v.setGroupImage(2),
        lambda: v.removeGroup(),
        # Speichern und Verwerfen
        lambda: v.save(),
        lambda: _warnings.extend(_verify_saved_file()),
        lambda: v.select("overlays", 0),
        lambda: v.setField("label", "wird verworfen"),
        lambda: v.revert(),
        # Der Teensy meldet eine andere Anordnung -> Rueckfrage im Banner
        lambda: _pending_teensy(bridge),
        lambda: v.dismissPendingTeensyConfig(),
        lambda: _pending_teensy(bridge),
        lambda: v.applyPendingTeensyConfig(),
        lambda: v.select("overlays", 0),
    ]
    return steps


def _verify_saved_file() -> list[str]:
    """Was der Editor gespeichert hat, wirklich nachlesen.

    Die wichtigste Zusicherung steht hier: ein TEXTRASTER muss in der Datei
    EIN Eintrag bleiben. Wuerde der Editor die aufbereitete Fassung
    zurueckschreiben, waeren daraus stillschweigend ein Dutzend
    Einzelpositionen geworden — sichtbar identisch, aber beim naechsten
    Verschieben muesste man jede davon einzeln anfassen. Genau der Sinn des
    Rasters waere weg, und auffallen wuerde es erst Wochen spaeter.
    """
    import json
    import runtime_config

    path = runtime_config.runtime_config_path(1, runtime_config.VISUALS_NAME)
    if not path.exists():
        return [f"Speichern hat keine Datei erzeugt: {path}"]

    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[str] = []
    if not raw.get(runtime_config.LOCAL_EDIT_KEY):
        out.append("gespeicherte Datei ist nicht als handbearbeitet markiert "
                   "— eine neue Firmware wuerde sie kommentarlos ersetzen")

    grids = [o for g in raw.get("groups", [])
             for o in g.get("overlays", [])
             if isinstance(o, dict) and o.get("type") == "textgrid"]
    if not grids:
        out.append("kein Textraster in der gespeicherten Datei — der Test "
                   "prueft dann nichts")
    for grid in grids:
        if not isinstance(grid.get("channels"), str):
            out.append(f"Textraster: 'channels' ist {type(grid.get('channels')).__name__}, "
                       "erwartet wird die kompakte Schreibweise als Text")
        for key in ("cols", "x_pct", "y_pct"):
            if key not in grid:
                out.append(f"Textraster: '{key}' fehlt in der gespeicherten Datei")
    return out


def _pending_teensy(bridge: AppBridge) -> None:
    """Eine vom Teensy gemeldete Anordnung einspielen. Weil vorher im Editor
    gespeichert wurde (_locally_edited), muss sie als Rueckfrage haengen
    bleiben statt die Handarbeit zu ueberschreiben."""
    from channel_registry import ChannelRegistry
    reg = ChannelRegistry()
    reg.overlays = [
        {"type": "text", "label": "Vom Teensy", "channel": 5,
         "x_pct": 20.0, "y_pct": 30.0, "group": 1},
        {"type": "gauge", "label": "Teensy-Zeiger", "channel": 6,
         "min": 0.0, "max": 10.0, "group": 1},
    ]
    # Zufallszahl im Label -> jedes Mal ein anderer Fingerabdruck, sonst
    # entschiede merge_decision beim zweiten Aufruf auf "keep".
    reg.overlays[0]["label"] += str(id(reg))
    bridge._visuals.apply_overlay_defaults_from_registry(reg, 1)


def _visual_types(root) -> dict[str, int]:
    """Zaehlt die eigenen QML-Typen im SICHTBAREN Baum.

    Ueber childItems() und NICHT ueber findChildren(): von einem Repeater
    oder Loader erzeugte Elemente bekommen gar keinen QObject-Elternteil,
    sie haengen nur visuell am Baum. findChildren() findet sie deshalb nie —
    eine Pruefung darueber meldet "0 Instanzen", obwohl alles da ist.

    Nebeneffekt mit Absicht: das Abfragen von width/height ERZWINGT eine
    Layout-Runde. Offscreen und ohne Renderer passiert die sonst nie, und
    genau dort entstehen die Meldungen zu Bindungsschleifen und zu Ankern in
    einem Positionierer. Ein zusammenklappender Kasten im Plotter blieb
    deshalb unbemerkt, obwohl der Test ihn angefasst hat.
    """
    out: dict[str, int] = {}

    def walk(item, depth: int = 0) -> None:
        if depth > 80:                       # Schutz vor Zyklen
            return
        for child in item.childItems():
            child.width(), child.height()    # erzwingt das Layout
            name = child.metaObject().className()
            if "_QMLTYPE" in name:
                # QML haengt an jeden eigenen Typ eine laufende Nummer an
                # ("FieldEditor_QMLTYPE_71") — die interessiert hier nicht.
                key = name.split("_QMLTYPE")[0]
                out[key] = out.get(key, 0) + 1
            walk(child, depth + 1)

    content = root.contentItem() if hasattr(root, "contentItem") else root
    walk(content)
    return out


def _verify_positioners(engine) -> list[str]:
    """Kein Positionierer darf flacher sein als sein hoechstes Kind.

    Das ist eine echte Invariante von Flow/Row/Column — und genau die war im
    Plotter verletzt: eine Bindungsschleife zwischen der Hoehe des
    Trigger-Kastens und der Hoehe seiner Flow liess den Kasten beim
    Einschalten von 192 auf 16 Pixel zusammenfallen, die Flow meldete 0. Qt
    gibt dabei keinen Fehler aus, es rechnet stillschweigend eine Seite der
    Schleife nicht mehr.

    Bewusst KEINE Mindesthoehe in Pixeln: die Kurvenlegende des Plotters ist
    voellig zu Recht nur 13 Pixel hoch. Die Invariante trifft dagegen immer.
    """
    from PyQt6.QtQuick import QQuickItem

    def _chain(item) -> str:
        """Elternkette als Wegbeschreibung — ohne die ist ein Befund in einem
        Baum aus hunderten Elementen nicht auffindbar."""
        parts, node = [], item
        while node is not None and len(parts) < 9:
            parts.append(node.metaObject().className().split("_QMLTYPE")[0])
            node = node.parentItem()
        return " < ".join(parts)

    found: list[str] = []

    def walk(item, depth: int = 0) -> None:
        if depth > 80:
            return
        for child in item.childItems():
            if not isinstance(child, QQuickItem):
                continue
            name = child.metaObject().className()
            if (name.startswith(("QQuickFlow", "QQuickColumn", "QQuickRow"))
                    and child.isVisible() and child.width() > 1):
                kids = [c for c in child.childItems()
                        if isinstance(c, QQuickItem) and c.isVisible()]
                tallest = max((c.height() for c in kids), default=0.0)
                if tallest > 0 and child.height() < tallest - 0.5:
                    found.append(
                        f"{name.split('_QMLTYPE')[0]} ist {child.height():.0f} px "
                        f"hoch, sein hoechstes von {len(kids)} Kindern aber "
                        f"{tallest:.0f} px — Inhalt ragt heraus oder eine "
                        f"Bindungsschleife um die Hoehe. Ort: {_chain(child)}")
            walk(child, depth + 1)

    root = engine.rootObjects()[0]
    walk(root.contentItem() if hasattr(root, "contentItem") else root)
    return found


def _open_channel_picker(engine) -> None:
    """Die Kanalauswahl aufklappen. Ein geschlossenes Popup haengt NICHT im
    sichtbaren Baum — ohne Oeffnen wuerden seine 200 Listenzeilen nie gebaut
    und damit auch nie geprueft."""
    from PyQt6.QtCore import QObject as _QObject
    for obj in engine.rootObjects()[0].findChildren(_QObject):
        if obj.metaObject().className().startswith("ChannelPicker"):
            obj.setProperty("current", 12)
            obj.setProperty("visible", True)      # Popup.visible = geoeffnet
            return


def _close_channel_picker(engine) -> None:
    from PyQt6.QtCore import QObject as _QObject
    for obj in engine.rootObjects()[0].findChildren(_QObject):
        if obj.metaObject().className().startswith("ChannelPicker"):
            obj.setProperty("visible", False)
            return


def _verify_editor_rendered(engine) -> list[str]:
    """Wurde der Editor wirklich gezeichnet?

    Ohne diese Pruefung koennte der Test vollkommen leer gruen melden: haette
    QML den Editor gar nicht instanziiert (falsche Bedingung, leeres Modell,
    Tippfehler im Dateinamen), gaebe es auch keine Warnung — und "keine
    Warnung" hiesse dann "nichts geprueft".
    """
    from PyQt6.QtCore import QObject as _QObject
    root = engine.rootObjects()[0]
    counts = _visual_types(root)
    out: list[str] = []

    # FieldEditor: das ausgewaehlte Element ist ein Text-Overlay mit fuenf
    # Feldern; weniger hiesse, dass das Formular nicht aufgebaut wurde.
    for want, minimum in (("OverlayEditor", 1), ("FieldEditor", 5),
                          ("AppButton", 10)):
        if counts.get(want, 0) < minimum:
            out.append(f"{want}: {counts.get(want, 0)} Instanz(en) im "
                       f"sichtbaren Baum, mindestens {minimum} erwartet")

    # Die Kanalauswahl NICHT ueber den sichtbaren Baum: ein Popup ist in Qt
    # kein Item und taucht dort grundsaetzlich nicht auf — nur sein Inhalt,
    # und der heisst dann schlicht "Column". Ueber den QObject-Baum ist es
    # dagegen auffindbar; `visible` sagt, ob der vorige Schritt es wirklich
    # geoeffnet hat.
    pickers = [o for o in root.findChildren(_QObject)
               if o.metaObject().className().startswith("ChannelPicker")]
    if not pickers:
        out.append("ChannelPicker: nicht im Objektbaum")
    elif not pickers[0].property("visible"):
        out.append("ChannelPicker: liess sich nicht oeffnen")
    return out


def main() -> int:
    app = QGuiApplication(sys.argv[:1])

    qmlRegisterType(PlotCanvas, "App", 1, 0, "PlotCanvas")
    qmlRegisterSingletonType(QUrl.fromLocalFile(str(QML_DIR / "Theme.qml")),
                              "App", 1, 0, "Theme")
    qmlRegisterSingletonType(QUrl.fromLocalFile(str(QML_DIR / "UiState.qml")),
                              "App", 1, 0, "UiState")

    nm = NetworkManager()          # bewusst ohne start()
    bridge = AppBridge(nm)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    engine.warnings.connect(
        lambda ws: _warnings.extend(w.toString() for w in ws))
    ctx = engine.rootContext()
    ctx.setContextProperty("appBridge", bridge)
    ctx.setContextProperty("telemetryModel", bridge.telemetry.table_model)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("FEHLER: Main.qml konnte nicht geladen werden.")
        for w in _warnings:
            print("  " + w)
        bridge.shutdown()
        return 1

    # Zweimal durchspielen: beim ersten Mal sind viele Bindungen noch nicht
    # ausgewertet, beim zweiten Mal laufen sie durch die Aenderungssignale.
    QTimer.singleShot(200, lambda: _exercise(bridge))
    QTimer.singleShot(700, lambda: _exercise(bridge))

    # Danach der Overlay-Editor, ein Schritt je Zeitscheibe.
    # Zuerst der Plotter-Trigger. Beim Einschalten kommen mehrere
    # Bedienelemente hinzu, der Kasten muss also nachwachsen — genau dabei
    # faellt eine Bindungsschleife auf. Nach jedem Schalten eine Layout-Runde
    # erzwingen, sonst rechnet Qt offscreen gar nicht.
    steps: list = [
        lambda: bridge._plotter.setTriggerEnabled(True),
        lambda: _visual_types(engine.rootObjects()[0]),
        lambda: bridge._plotter.setTriggerMode("outside"),
        lambda: _warnings.extend(_verify_positioners(engine)),
        lambda: bridge._plotter.setTriggerEnabled(False),
        lambda: _visual_types(engine.rootObjects()[0]),
    ]

    steps += _exercise_editor(bridge)
    steps.append(lambda: _open_channel_picker(engine))
    steps.append(lambda: _warnings.extend(_verify_editor_rendered(engine)))
    steps.append(lambda: _close_channel_picker(engine))
    steps.append(lambda: bridge._settings.setFontScale(1.4))   # Layout skaliert
    steps.append(lambda: bridge._settings.setFontScale(1.0))
    steps.append(lambda: bridge._visuals.setEditing(False))
    step_timer = QTimer()
    step_timer.setInterval(40)
    pos = {"i": 0}

    def _next() -> None:
        if pos["i"] >= len(steps):
            step_timer.stop()
            QTimer.singleShot(300, app.quit)
            return
        try:
            steps[pos["i"]]()
        except Exception:
            import traceback
            _warnings.append(
                f"Schritt {pos['i']} hat eine Ausnahme ausgeloest:\n"
                + traceback.format_exc())
            step_timer.stop()
            QTimer.singleShot(0, app.quit)
            return
        pos["i"] += 1

    step_timer.timeout.connect(_next)
    QTimer.singleShot(1200, step_timer.start)
    app.exec()

    bridge.shutdown()

    # Qt meldet fehlende Properties und Typfehler als Warnung, nicht als
    # Fehler — deshalb sind sie hier das eigentliche Pruefkriterium.
    real = [w for w in _warnings if w.strip()]
    if real:
        print(f"FEHLER: {len(real)} Qt-Warnung(en)/Befund(e) waehrend des Laufs:")
        for w in dict.fromkeys(real):      # Reihenfolge behalten, Dubletten weg
            print("  " + w)
        return 1

    print(f"OK — Oberflaeche laedt und laeuft warnungsfrei "
          f"({len(engine.rootObjects())} Wurzelobjekt(e), "
          f"{len(steps)} Editor-Schritte).")
    return 0


if __name__ == "__main__":
    rc = main()
    # ── Warum os._exit() und nicht SystemExit ─────────────────────────────
    #  Auf Windows mit Python 3.14 + PyQt6 6.11 bricht der Prozess in etwa
    #  vier von zehn Laeufen BEIM ABBAU mit 0xC0000409 ab — auch dann, wenn
    #  das Skript nichts weiter tut als Main.qml zu laden und sofort wieder
    #  zu beenden. Gemessen: 5 von 8 Fehlschlaegen ohne jede Bedienung, mit
    #  und ohne Software-Renderer, und durch keine Abbaureihenfolge zu
    #  beheben (rootObjects zuerst loeschen macht es sogar deterministisch).
    #  Der Absturz haengt also weder an dieser Datei noch an der Oberflaeche.
    #
    #  Ein Test, der zu 40 % zufaellig rot wird, ist als CI-Wachposten
    #  wertlos. Zu diesem Zeitpunkt ist ohnehin alles Gepruefte gelaufen und
    #  das Urteil steht auf der Konsole — deshalb hier hart beenden, ohne
    #  Interpreter- und Qt-Abbau.
    #
    #  WAS DAMIT NICHT GEPRUEFT WIRD: ein Fehler im Aufraeumen der Anwendung
    #  selbst (AppBridge.shutdown, Empfaengerprozesse). Der laeuft oben
    #  weiterhin durch, sein Ergebnis wird nur nicht mehr am Exit-Code
    #  gemessen.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
