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

# pyqtgraph ist eine QWidget-Bibliothek: die GUI braucht deshalb zwingend
# QApplication (nicht QGuiApplication), sonst kann kein PlotWidget erzeugt
# werden. QApplication ist ein Superset von QGuiApplication und verträgt sich
# mit Qt Quick / QML.
from PyQt6.QtWidgets import QApplication
from PyQt6.QtQml import QQmlApplicationEngine, qmlRegisterType, qmlRegisterSingletonType
from PyQt6.QtCore import QUrl, QCoreApplication

import app_settings
from network_worker import NetworkManager
from bridge.app_bridge import AppBridge
from bridge.plot_host import PyQtGraphHost

# PDS_LOGLEVEL=DEBUG schaltet u. a. die 1x/s-Ausgabe aller rohen Controller-
# Achsen/Buttons frei (siehe bridge/controller_bridge.py) — der schnellste Weg,
# eine abweichende SDL-Belegung zu ermitteln.
logging.basicConfig(
    level=getattr(logging, os.environ.get("PDS_LOGLEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s  [%(name)-20s]  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main_qml")

_QML_DIR = Path(__file__).resolve().parent / "qml"


def _udp_simulator_process(stop_event) -> None:
    """Synthetische Telemetrie für beide Nodes, damit die GUI ohne Teensy
    getestet werden kann.

    Vollständig vektorisiert: die frühere Fassung berechnete jeden der 200
    Kanäle einzeln in einer Python-Schleife (inkl. np.random.normal pro
    Kanal) — 40 000 Einzelaufrufe pro Sekunde, die auf einem RPi mehr CPU
    gekostet haben als die gesamte übrige GUI.

    Der Zeitstempel läuft in echten Mikrosekunden seit Prozessstart und wird
    modulo 2^32 gerechnet — genau wie micros() auf dem Teensy. Damit lässt
    sich auch die Neustart-Erkennung der GUI mit dem Simulator testen.
    """
    import time, struct, socket, math, random
    import numpy as np
    from config import (
        PACKET_HEADER_MAGIC, MAX_FLOATS,
        UDP_PORT_NODE1, UDP_PORT_NODE2,
        UDP_AUX_PORT_NODE1, UDP_AUX_PORT_NODE2,
        PDS_EVENT_MAGIC, PDS_EVENT_HEADER_BYTES,
        PARAM_ACK_MAGIC, PARAM_ACK_HEADER_BYTES,
        PARAM_SLOW_FLOAT_COUNT, PARAM_SLOW_BOOL_COUNT, PARAM_FAST_FLOAT_COUNT,
        NODE_STATUS_MAGIC, NODE_STATUS_STRUCT,
        NODE_STATUS_FLAG_TEENSY, NODE_STATUS_FLAG_WIFI, NODE_STATUS_FLAG_UNICAST,
    )

    # Die Kopf-Formate hier muessen zu params.h passen. Ein stiller
    # Fehlschlag waere besonders aergerlich: der Simulator saehe funktionsfaehig
    # aus, die GUI wuerde die Pakete aber wortlos verwerfen.
    assert struct.calcsize("<IIfBBBB") == PDS_EVENT_HEADER_BYTES
    assert struct.calcsize("<IIIII") == PARAM_ACK_HEADER_BYTES

    def _event_packet(ts_us, kind, level, text, value=0.0):
        raw = text.encode("utf-8")[:48]
        return (struct.pack("<IIfBBBB", PDS_EVENT_MAGIC, ts_us, value,
                             kind, level, len(raw), 0) + raw)

    def _ack_packet(seq, floats, bools, fast):
        return (struct.pack("<IIIII", PARAM_ACK_MAGIC, seq, seq, 120, 8)
                 + floats.astype("<f4").tobytes()
                 + bools.astype(np.uint8).tobytes()
                 + fast.astype("<f4").tobytes())

    def _status_packet(node_id, uptime, uart_pkts):
        flags = NODE_STATUS_FLAG_TEENSY | NODE_STATUS_FLAG_WIFI | NODE_STATUS_FLAG_UNICAST
        return struct.pack(
            NODE_STATUS_STRUCT, NODE_STATUS_MAGIC, node_id, flags, 0,
            48.0 + 4.0 * math.sin(uptime / 30.0),      # CPU-Temperatur
            0.4 + 0.2 * random.random(),               # Last
            35.0 + 5.0 * random.random(),              # Speicher
            -55.0 - 10.0 * random.random(),            # WLAN-Pegel
            int(uptime), uart_pkts, 0, uart_pkts,
        )

    logging.basicConfig(level=logging.INFO, format="[Simulator] %(asctime)s %(message)s")
    sim_log = logging.getLogger()
    sim_log.info("Simulator gestartet (beide Nodes → localhost)")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rng = np.random.default_rng()

    idx   = np.arange(MAX_FLOATS, dtype=np.float32)
    freqs = 0.5 + idx * 0.002                      # einmalig, nicht pro Paket
    data  = np.empty(MAX_FLOATS, dtype=np.float32)

    t0, pkt, next_send = time.monotonic(), 0, time.monotonic()

    # Der Simulator bedient auch den Aux-Uplink: ohne Ereignisse,
    # Parameter-Rueckmeldung und Node-Status waeren der Diagnose-Tab und
    # die Plotter-Marken ohne echte Hardware gar nicht zu sehen.
    ack_floats = np.zeros(PARAM_SLOW_FLOAT_COUNT, dtype=np.float32)
    ack_bools = np.zeros(PARAM_SLOW_BOOL_COUNT, dtype=bool)
    ack_fast = np.zeros(PARAM_FAST_FLOAT_COUNT, dtype=np.float32)
    aux_ports = {1: UDP_AUX_PORT_NODE1, 2: UDP_AUX_PORT_NODE2}
    next_status = next_ack = next_event = time.monotonic()
    event_seq = 0

    while not stop_event.is_set():
        t  = time.monotonic() - t0
        ts = int(t * 1e6) & 0xFFFF_FFFF
        header = struct.pack("<II", PACKET_HEADER_MAGIC, ts)

        base = np.sin(2 * np.pi * freqs * t, dtype=np.float32) * 3.3
        for node_id, port in ((1, UDP_PORT_NODE1), (2, UDP_PORT_NODE2)):
            np.add(base, (node_id - 1) * 1.0, out=data)
            data += rng.normal(0.0, 0.05, MAX_FLOATS).astype(np.float32)
            data *= 20.0
            sock.sendto(header + data.tobytes(), ("127.0.0.1", port))

        pkt += 2
        if pkt % 2000 == 0:
            sim_log.info(f"{pkt} Pakete gesendet | t={t:.1f}s")

        now = time.monotonic()
        if now >= next_status:
            next_status = now + 1.0
            for node_id, port in aux_ports.items():
                sock.sendto(_status_packet(node_id, t, pkt // 2), ("127.0.0.1", port))
        if now >= next_ack:
            next_ack = now + 0.5
            for node_id, port in aux_ports.items():
                sock.sendto(_ack_packet(pkt, ack_floats, ack_bools, ack_fast),
                             ("127.0.0.1", port))
        if now >= next_event:
            next_event = now + 4.0
            event_seq += 1
            level = event_seq % 3
            sock.sendto(
                _event_packet(ts, event_seq % 2, level,
                               f"Testereignis {event_seq}", float(event_seq)),
                ("127.0.0.1", aux_ports[1]))

        # Feste 100-Hz-Phase statt sleep(0.01): sonst driftet die Rate mit der
        # Rechenzeit nach unten (real waren es eher 70-80 Hz).
        next_send += 0.01
        delay = next_send - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_send = time.monotonic()

    sock.close()
    sim_log.info("Simulator gestoppt.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Power Debug Monitor (QML)")
    parser.add_argument("--simulate", action="store_true",
                         help="Synthetische Testdaten generieren (kein Teensy nötig)")
    args = parser.parse_args()

    mp.freeze_support()

    # settings.json neben DIESER Datei anlegen bzw. die alte
    # runtime_config/ui_settings.json einmalig uebernehmen (siehe
    # app_settings.py). Bewusst hier und nicht beim Import: gleich darunter
    # entstehen die Empfaenger-Prozesse, die config.py — und damit
    # app_settings — ebenfalls importieren; auf Windows als eigenstaendige
    # Prozesse. Beim ersten Start haetten sonst vier Prozesse gleichzeitig
    # dieselbe Datei angelegt.
    app_settings.ensure_file()
    # Bewusst hier und nicht in app_settings: das Modul wird beim IMPORT
    # geladen, und zwar bevor logging.basicConfig() weiter oben gelaufen
    # ist — eine INFO-Zeile von dort saehe niemand. Wo die Einstellungen
    # herkommen, ist aber genau die Frage, die man sich stellt, wenn die
    # Oberflaeche anders aussieht als erwartet.
    log.info("Einstellungen: %s", app_settings.SETTINGS_PATH)

    QCoreApplication.setApplicationName("Power Debug Monitor")
    QCoreApplication.setOrganizationName("RoboCup Debug System")
    app = QApplication(sys.argv)

    # ── Custom QML-Typ registrieren: der pyqtgraph-basierte Live-Plotter
    #  (siehe bridge/plot_host.py). Bettet das PlotWidget je nach Plattform
    #  nativ ein oder fällt auf Image-Darstellung zurück.
    qmlRegisterType(PyQtGraphHost, "App", 1, 0, "PyQtGraphHost")

    # Theme.qml direkt als "App"-Modul-Singleton registrieren statt über
    # Verzeichnis-basierte qmldir-Auflösung — dadurch funktioniert
    # `import App` auch aus Unterordnern wie qml/components/ zuverlässig
    # (die reine Verzeichnis-lokale qmldir-Auflösung würde dort fehlschlagen).
    qmlRegisterSingletonType(
        QUrl.fromLocalFile(str(_QML_DIR / "Theme.qml")), "App", 1, 0, "Theme"
    )

    # UiState.qml genauso registrieren wie Theme.qml (siehe dortiger
    # Kommentar) — wird u.a. vom Joystick benutzt, um während einer
    # Touch-Bedienung das Wischen/Scrollen der umgebenden SwipeView /
    # Flickables zu unterdrücken (Migrationsplan-Nachtrag: Bedienbarkeit).
    qmlRegisterSingletonType(
        QUrl.fromLocalFile(str(_QML_DIR / "UiState.qml")), "App", 1, 0, "UiState"
    )

    # ── Backend wie gehabt starten ────────────────────────────────────────
    nm = NetworkManager()
    nm.start()

    sim_proc = None
    if args.simulate:
        log.info("Simulator-Modus aktiv")
        sim_proc = mp.Process(
            target=_udp_simulator_process,
            args=(nm.stop_event,),
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

    # QML-Ladefehler explizit melden. Ohne diesen Handler steht bei einem
    # Tippfehler in einer .qml-Datei nur "Abbruch" im Log, ohne Datei/Zeile.
    # (objectCreationFailed gibt es erst ab Qt 6.4 — deshalb abgesichert.)
    if hasattr(engine, "objectCreationFailed"):
        engine.objectCreationFailed.connect(
            lambda url: log.error("QML-Objekt konnte nicht erzeugt werden: %s", url.toString())
        )

    # Backend beim Beenden IMMER herunterfahren — auch wenn das Fenster über
    # den Fenstermanager statt über Qt.quit() geschlossen wird.
    app.aboutToQuit.connect(bridge.shutdown)

    engine.load(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        log.error("QML konnte nicht geladen werden — Abbruch.")
        bridge.shutdown()
        if sim_proc and sim_proc.is_alive():
            sim_proc.terminate()
        sys.exit(-1)

    exit_code = app.exec()

    bridge.shutdown()      # idempotent, siehe AppBridge.shutdown()
    if sim_proc and sim_proc.is_alive():
        sim_proc.terminate()
        sim_proc.join(timeout=2)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
