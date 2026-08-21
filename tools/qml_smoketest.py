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

    bridge._diag.setBatteryConfig({"enabled": True, "channel": 0,
                                    "warn_below": 1e9, "critical_below": 1e9})
    bridge._diag.note_values(block[-1])
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
    QTimer.singleShot(1400, app.quit)
    app.exec()

    bridge.shutdown()

    # Qt meldet fehlende Properties und Typfehler als Warnung, nicht als
    # Fehler — deshalb sind sie hier das eigentliche Pruefkriterium.
    real = [w for w in _warnings if w.strip()]
    if real:
        print(f"FEHLER: {len(real)} Qt-Warnung(en) waehrend des Laufs:")
        for w in dict.fromkeys(real):      # Reihenfolge behalten, Dubletten weg
            print("  " + w)
        return 1

    print("OK — Oberflaeche laedt und laeuft warnungsfrei "
          f"({len(engine.rootObjects())} Wurzelobjekt(e)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
