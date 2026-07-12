"""
main_qml.py — Power Debug Monitor (RPi 5) — Qt Quick / QML Edition
======================================================================
Neuer Einstiegspunkt der QML-Migration (siehe QML_Migrationsplan_RPi5_
Monitor.md). Startet exakt dasselbe Backend wie main.py (NetworkManager,
optionaler UDP-Simulator), lädt aber statt der Widgets-`MainWindow` das
QML-Frontend aus qml/Main.qml.

main.py mit der alten Widgets-GUI bleibt unverändert erhalten (Phase 6
des Migrationsplans sieht das Entfernen von gui/ erst ganz am Ende vor,
nachdem die QML-Version vollständig validiert ist).

Aufruf:
    python rpi5_monitor/main_qml.py
    python rpi5_monitor/main_qml.py --simulate
"""
from __future__ import annotations

import os
import sys
import logging
import argparse
import multiprocessing as mp
from pathlib import Path

# ── WICHTIG: muss VOR dem Import von QGuiApplication/QQmlApplicationEngine
# gesetzt werden. Ohne diese Zeile lädt Qt Quick Controls 2 auf Windows
# standardmäßig den NATIVEN "Windows"-Style (qtquickcontrols2windowsstyle-
# implplugin.dll). Dieses Plugin hat eigene native Abhängigkeiten, die in
# manchen PyQt6-Installationen nicht vollständig aufgelöst werden können
# ("Das angegebene Modul wurde nicht gefunden" — QQmlApplicationEngine
# failed to load component). Wir erzwingen stattdessen den reinen
# QML/Software-Style "Material" (den wir in Main.qml ohnehin verwenden) —
# der hat keine nativen Windows-Abhängigkeiten und funktioniert auf allen
# Plattformen (Windows/Linux/RPi5) identisch.
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine, qmlRegisterType, qmlRegisterSingletonType
from PyQt6.QtCore import QUrl, QCoreApplication

from network_worker import NetworkManager
from bridge.app_bridge import AppBridge
from bridge.plot_bridge import PlotCanvas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)-20s]  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main_qml")

_QML_DIR = Path(__file__).resolve().parent / "qml"


def _udp_simulator_process(stop_event) -> None:
    """Unverändert aus main.py übernommen — synthetische Telemetrie für
    beide Nodes, damit die QML-GUI ohne Teensy getestet werden kann."""
    import time, struct, socket
    import numpy as np
    from config import (PACKET_HEADER_MAGIC, MAX_FLOATS,
                         UDP_PORT_NODE1, UDP_PORT_NODE2)

    logging.basicConfig(level=logging.INFO, format="[Simulator] %(asctime)s %(message)s")
    sim_log = logging.getLogger()
    sim_log.info("Simulator gestartet (beide Nodes → localhost)")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t, pkt = 0.0, 0

    while not stop_event.is_set():
        for node_id, port in ((1, UDP_PORT_NODE1), (2, UDP_PORT_NODE2)):
            ts = int(t * 1e6) & 0xFFFF_FFFF
            header = struct.pack("<II", PACKET_HEADER_MAGIC, ts)

            data = np.zeros(MAX_FLOATS, dtype=np.float32)
            for i in range(min(500, MAX_FLOATS)):
                freq = 0.5 + i * 0.002
                data[i] = (np.sin(2 * np.pi * freq * t) * 3.3
                           + (node_id - 1) * 1.0
                           + np.random.normal(0, 0.05)) * 20
            data[min(500, MAX_FLOATS):] = 9898.0

            sock.sendto(header + data.tobytes(), ("127.0.0.1", port))

        t += 0.01
        pkt += 2
        if pkt % 1000 == 0:
            sim_log.info(f"{pkt} Pakete gesendet | t={t:.1f}s")
        time.sleep(0.01)

    sock.close()
    sim_log.info("Simulator gestoppt.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Power Debug Monitor (QML)")
    parser.add_argument("--simulate", action="store_true",
                         help="Synthetische Testdaten generieren (kein Teensy nötig)")
    args = parser.parse_args()

    mp.freeze_support()

    QCoreApplication.setApplicationName("Power Debug Monitor")
    QCoreApplication.setOrganizationName("RoboCup Debug System")
    app = QGuiApplication(sys.argv)

    # ── Custom QML-Typ registrieren (Migrationsplan Abschnitt 4.4, Option C)
    qmlRegisterType(PlotCanvas, "App", 1, 0, "PlotCanvas")

    # Theme.qml direkt als "App"-Modul-Singleton registrieren statt über
    # Verzeichnis-basierte qmldir-Auflösung — dadurch funktioniert
    # `import App` auch aus Unterordnern wie qml/components/ zuverlässig
    # (die reine Verzeichnis-lokale qmldir-Auflösung würde dort fehlschlagen).
    qmlRegisterSingletonType(
        QUrl.fromLocalFile(str(_QML_DIR / "Theme.qml")), "App", 1, 0, "Theme"
    )

    # ── Backend wie gehabt starten ────────────────────────────────────────
    nm = NetworkManager()
    nm.start()

    sim_proc = None
    if args.simulate:
        log.info("⚡ Simulator-Modus aktiv")
        sim_proc = mp.Process(
            target=_udp_simulator_process,
            args=(nm._stop_event,),
            daemon=True,
            name="UDP-Simulator",
        )
        sim_proc.start()

    bridge = AppBridge(nm)

    # ── QML-Engine ────────────────────────────────────────────────────────
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(_QML_DIR))
    ctx = engine.rootContext()
    ctx.setContextProperty("appBridge", bridge)
    ctx.setContextProperty("telemetryModel", bridge.telemetry.table_model)

    engine.load(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        log.error("QML konnte nicht geladen werden — Abbruch.")
        nm.stop()
        sys.exit(-1)

    exit_code = app.exec()

    bridge.shutdown()
    if sim_proc and sim_proc.is_alive():
        sim_proc.terminate()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
