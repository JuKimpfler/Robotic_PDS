"""
main.py — Power Debug Monitor  (RPi 5)
=======================================
Startet:
  1. NetworkManager  → 2× UDP-Empfänger-Prozesse
  2. PyQt6-GUI       → MainWindow mit allen Tabs

Aufruf:
    python rpi5_monitor/main.py

Optional:
    python rpi5_monitor/main.py --simulate
        Startet einen eingebauten UDP-Simulator (kein Teensy nötig),
        der synthetische Pakete an localhost schickt.
"""

import sys
import logging
import argparse
import multiprocessing as mp
import platform
from platform_utils import setup_hotspot

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

from network_worker import NetworkManager
from gui.main_window import MainWindow


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)-20s]  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


# ══════════════════════════════════════════════════════════════════════════════
#  Dark Theme
# ══════════════════════════════════════════════════════════════════════════════

def _apply_dark_theme(app: QApplication) -> None:
    """Modernes dunkles Farbschema (VS-Code-ähnlich)."""
    p = QPalette()
    c = {
        "bg":        QColor(30,  30,  30),
        "bg_mid":    QColor(45,  45,  48),
        "bg_alt":    QColor(55,  55,  58),
        "text":      QColor(212, 212, 212),
        "text_dim":  QColor(150, 150, 150),
        "highlight": QColor(0,   120, 215),
        "hl_text":   QColor(255, 255, 255),
        "border":    QColor(68,  68,  68),
    }

    p.setColor(QPalette.ColorRole.Window,          c["bg"])
    p.setColor(QPalette.ColorRole.WindowText,      c["text"])
    p.setColor(QPalette.ColorRole.Base,            c["bg"])
    p.setColor(QPalette.ColorRole.AlternateBase,   c["bg_alt"])
    p.setColor(QPalette.ColorRole.Text,            c["text"])
    p.setColor(QPalette.ColorRole.BrightText,      c["hl_text"])
    p.setColor(QPalette.ColorRole.Button,          c["bg_mid"])
    p.setColor(QPalette.ColorRole.ButtonText,      c["text"])
    p.setColor(QPalette.ColorRole.PlaceholderText, c["text_dim"])
    p.setColor(QPalette.ColorRole.Highlight,       c["highlight"])
    p.setColor(QPalette.ColorRole.HighlightedText, c["hl_text"])
    p.setColor(QPalette.ColorRole.ToolTipBase,     c["bg_mid"])
    p.setColor(QPalette.ColorRole.ToolTipText,     c["text"])
    p.setColor(QPalette.ColorRole.Mid,             c["border"])

    app.setPalette(p)
    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid #555;
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 4px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            color: #9cdcfe;
        }
        QTabBar::tab {
            padding: 6px 14px;
            background: #2d2d30;
            border: 1px solid #444;
            border-bottom: none;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background: #1e1e1e;
            border-top: 2px solid #007acc;
        }
        QScrollBar:vertical {
            width: 10px; background: #2d2d30;
        }
        QScrollBar::handle:vertical {
            background: #555; border-radius: 4px; min-height: 20px;
        }

        /* ── Input Widgets: heller Hintergrund für guten Kontrast ── */
        QLineEdit {
            background: #3c3f41;
            color: #e8e8e8;
            border: 1px solid #5a5a5c;
            border-radius: 3px;
            padding: 3px 6px;
            selection-background-color: #0078d4;
            selection-color: #ffffff;
        }
        QLineEdit:focus {
            border: 1px solid #007acc;
            background: #424548;
        }
        QLineEdit:disabled {
            background: #2a2a2d;
            color: #666;
            border-color: #444;
        }

        QDoubleSpinBox, QSpinBox {
            background: #3c3f41;
            color: #e8e8e8;
            border: 1px solid #5a5a5c;
            border-radius: 3px;
            padding: 3px 6px;
        }
        QDoubleSpinBox:focus, QSpinBox:focus {
            border: 1px solid #007acc;
            background: #424548;
        }
        QDoubleSpinBox::up-button, QSpinBox::up-button,
        QDoubleSpinBox::down-button, QSpinBox::down-button {
            background: #505355;
            border: none;
            width: 16px;
        }
        QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
        QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {
            background: #0078d4;
        }

        QComboBox {
            background: #3c3f41;
            color: #e8e8e8;
            border: 1px solid #5a5a5c;
            border-radius: 3px;
            padding: 3px 8px;
        }
        QComboBox:focus {
            border: 1px solid #007acc;
        }
        QComboBox::drop-down {
            border: none;
            background: #505355;
            width: 20px;
        }
        QComboBox QAbstractItemView {
            background: #3c3f41;
            color: #e8e8e8;
            selection-background-color: #0078d4;
            selection-color: #ffffff;
            border: 1px solid #5a5a5c;
        }

        QSlider::groove:horizontal {
            height: 6px;
            background: #3c3f41;
            border: 1px solid #5a5a5c;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #007acc;
            border: 1px solid #005f9e;
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
        }
        QSlider::handle:horizontal:hover {
            background: #1a8fe0;
        }
        QSlider::sub-page:horizontal {
            background: #0078d4;
            border-radius: 3px;
        }
        QSlider::groove:horizontal:disabled {
            background: #2a2a2d;
        }

        QPushButton {
            background: #3a3d40;
            color: #e0e0e0;
            border: 1px solid #5a5a5c;
            border-radius: 4px;
            padding: 4px 12px;
        }
        QPushButton:hover {
            background: #4a4d50;
            border-color: #007acc;
        }
        QPushButton:pressed {
            background: #0078d4;
            color: #ffffff;
        }
        QPushButton:disabled {
            background: #2a2a2d;
            color: #555;
            border-color: #444;
        }

        QCheckBox {
            color: #e0e0e0;
            spacing: 6px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #5a5a5c;
            border-radius: 3px;
            background: #3c3f41;
        }
        QCheckBox::indicator:checked {
            background: #0078d4;
            border-color: #0078d4;
        }
        QCheckBox::indicator:hover {
            border-color: #007acc;
        }
    """)


# ══════════════════════════════════════════════════════════════════════════════
#  UDP-Simulator  (--simulate Modus, kein Teensy benötigt)
# ══════════════════════════════════════════════════════════════════════════════

def _udp_simulator_process(stop_event: mp.Event) -> None:
    """
    Sendet synthetische Telemetriepakete an localhost.
    Beide Nodes werden simuliert (Ports 5001 + 5002).
    """
    import time, struct, socket
    import numpy as np
    from config import (PACKET_HEADER_MAGIC, MAX_FLOATS, HEADER_SIZE,
                        UDP_PORT_NODE1, UDP_PORT_NODE2)

    logging.basicConfig(level=logging.INFO,
                        format="[Simulator] %(asctime)s %(message)s")
    sim_log = logging.getLogger()
    sim_log.info("Simulator gestartet (beide Nodes → localhost)")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t = 0.0
    pkt = 0

    while not stop_event.is_set():
        for node_id, port in ((1, UDP_PORT_NODE1), (2, UDP_PORT_NODE2)):
            ts     = int(t * 1e6) & 0xFFFF_FFFF
            header = struct.pack("<II", PACKET_HEADER_MAGIC, ts)

            data = np.zeros(MAX_FLOATS, dtype=np.float32)
            for i in range(min(500, MAX_FLOATS)):
                freq = 0.5 + i * 0.002
                data[i] = (np.sin(2 * np.pi * freq * t) * 3.3
                           + (node_id - 1) * 1.0       # Offset pro Node
                           + np.random.normal(0, 0.05))*20
            data[min(500, MAX_FLOATS):] = 9898.0   # Dummy-Füllung

            raw = header + data.tobytes()
            sock.sendto(raw, ("127.0.0.1", port))

        t   += 0.01      # 10 ms Schritt = 100 Hz
        pkt += 2
        if pkt % 1000 == 0:
            sim_log.info(f"{pkt} Pakete gesendet | t={t:.1f}s")

        time.sleep(0.01)

    sock.close()
    sim_log.info("Simulator gestoppt.")


# ══════════════════════════════════════════════════════════════════════════════
#  Einstiegspunkt
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Power Debug Monitor")
    parser.add_argument(
        "--simulate", action="store_true",
        help="Synthetische Testdaten generieren (kein Teensy nötig)"
    )
    args = parser.parse_args()

    # Multiprocessing: freeze_support() für PyInstaller-Kompatibilität
    mp.freeze_support()

    app = QApplication(sys.argv)
    app.setApplicationName("Power Debug Monitor")
    app.setOrganizationName("RoboCup Debug System")
    ##app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    _apply_dark_theme(app)
    # Netzwerk-Backend starten
    nm = NetworkManager()
    nm.start()

    # Optional: Simulator-Prozess starten
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

    # GUI starten
    window = MainWindow(nm)
    window.show()

    exit_code = app.exec()

    # Aufräumen
    nm.stop()
    if sim_proc and sim_proc.is_alive():
        sim_proc.terminate()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
