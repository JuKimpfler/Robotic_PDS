"""
main_window.py — Hauptfenster des Power Debug Monitors
========================================================
Layout:
  ┌─────────────────────────────────────────────────────┐
  │  [Node-Selektor]          [Flash-Management-Zone]   │  ← Steuerungsleiste
  ├─────────────────────────────────────────────────────┤
  │  Tab 1: Live-Tabelle                                │
  │  Tab 2: Live-Plotter                                │
  │  Tab 3: Systemansicht (Phase 2)                     │
  │  Tab 4: Parameter     (Phase 2)                     │
  └─────────────────────────────────────────────────────┘
"""

import multiprocessing as mp
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QRadioButton,
    QButtonGroup, QCheckBox, QGroupBox, QFileDialog,
    QStatusBar, QFrame,
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont

from config import GUI_TIMER_MS
from network_worker import NetworkManager, flash_nodes
from gui.tab_table   import TelemetryTableWidget
from gui.tab_plotter import LivePlotterWidget
from gui.tab_visuals import SystemVisualsWidget
from gui.tab_params  import ParamEditorWidget


class _FlashSignalBridge(QObject):
    """
    Brücke zwischen Flash-Threads und GUI-Hauptthread.
    Qt-Signals sind thread-sicher: emit() darf aus jedem Thread gerufen werden,
    der verbundene Slot wird immer im GUI-Thread ausgeführt.
    """
    result = pyqtSignal(int, bool, str)   # node_id, success, message


class MainWindow(QMainWindow):

    def __init__(self, network_manager: NetworkManager) -> None:
        super().__init__()
        self._nm          = network_manager
        self._active_node = 1

        self._flash_bridge = _FlashSignalBridge()
        self._flash_bridge.result.connect(self._on_flash_result)

        # Zähler für Pakete/Sekunde
        self._pkt_count   = 0
        self._node_active = {1: False, 2: False}   # Verbindungsstatus

        self._setup_ui()
        self._setup_timers()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI-Aufbau
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        self.setWindowTitle("Power Debug Monitor  —  RPi 5")
        self.setMinimumSize(1120, 780)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)

        root.addWidget(self._build_control_bar())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        root.addWidget(self._build_tabs(), stretch=1)

        # Statusleiste
        self._sb = QStatusBar()
        self.setStatusBar(self._sb)
        self._lbl_pps = QLabel("0 Pkt/s")
        self._lbl_pps.setStyleSheet("color: #4ec9b0; font-family: monospace;")
        self._sb.addPermanentWidget(self._lbl_pps)

    def _build_control_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Node-Selektor ─────────────────────────────────────────────────────
        node_box = QGroupBox("Aktiver Debug-Knoten")
        nb_layout = QHBoxLayout(node_box)
        nb_layout.setSpacing(16)

        self._node_btn_grp = QButtonGroup()
        for nid, ip in ((1, "192.168.42.11"), (2, "192.168.42.12")):
            rb = QRadioButton(f"  Node {nid}  ({ip})")
            rb.setChecked(nid == 1)
            rb.setFont(QFont("", 10))
            self._node_btn_grp.addButton(rb, nid)
            nb_layout.addWidget(rb)

        self._node_btn_grp.idToggled.connect(self._on_node_toggled)
        layout.addWidget(node_box)

        # ── Flash-Zone ────────────────────────────────────────────────────────
        flash_box = QGroupBox("Flash-Management")
        fl_layout = QHBoxLayout(flash_box)
        fl_layout.setSpacing(12)

        # LEDs
        self._led1 = QLabel("⬤ Node 1")
        self._led2 = QLabel("⬤ Node 2")
        self._set_led(self._led1, connected=False)
        self._set_led(self._led2, connected=False)
        fl_layout.addWidget(self._led1)
        fl_layout.addWidget(self._led2)

        fl_layout.addWidget(_vsep())

        # Ziel-Auswahl
        fl_layout.addWidget(QLabel("Ziel:"))
        self._chk_n1 = QCheckBox("Node 1")
        self._chk_n2 = QCheckBox("Node 2")
        self._chk_n1.setChecked(True)
        fl_layout.addWidget(self._chk_n1)
        fl_layout.addWidget(self._chk_n2)

        fl_layout.addWidget(_vsep())

        # Flash-Button
        self._btn_flash = QPushButton("⚡  Firmware flashen…")
        self._btn_flash.setMinimumWidth(190)
        self._btn_flash.setStyleSheet(
            "QPushButton { background: #264f78; color: white; "
            "border-radius: 4px; padding: 5px 10px; }"
            "QPushButton:hover { background: #3278a8; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self._btn_flash.clicked.connect(self._on_flash_clicked)
        fl_layout.addWidget(self._btn_flash)

        layout.addWidget(flash_box)
        return bar

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        self._tab_table   = TelemetryTableWidget()
        self._tab_plotter = LivePlotterWidget()
        self._tab_visuals = SystemVisualsWidget()
        self._tab_params  = ParamEditorWidget()

        tabs.addTab(self._tab_table,   "📊  Live-Tabelle")
        tabs.addTab(self._tab_plotter, "📈  Live-Plotter")
        tabs.addTab(self._tab_visuals, "🤖  Systemansicht")
        tabs.addTab(self._tab_params,  "⚙️  Parameter")

        return tabs

    # ══════════════════════════════════════════════════════════════════════════
    #  Timer & Daten-Pipeline
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_timers(self) -> None:
        # Daten-Timer (~30 Hz): liest Queue aus und aktualisiert GUI
        self._data_timer = QTimer()
        self._data_timer.setInterval(GUI_TIMER_MS)
        self._data_timer.timeout.connect(self._poll_data)
        self._data_timer.start()

        # Statistik-Timer (1 Hz)
        self._stat_timer = QTimer()
        self._stat_timer.setInterval(1000)
        self._stat_timer.timeout.connect(self._update_statusbar)
        self._stat_timer.start()

    def _poll_data(self) -> None:
        """
        Wird ~30× pro Sekunde aufgerufen.
        Liest ALLE aufgelaufenen Einträge aus der aktiven Queue
        in einem Batch — minimiert Qt-Layout-Berechnungen.
        """
        q = self._nm.get_queue(self._active_node)

        batch: list[np.ndarray] = []
        try:
            while True:
                _nid, _ts, values = q.get_nowait()
                batch.append(values)
        except Exception:
            pass   # Queue leer

        if not batch:
            return

        self._pkt_count += len(batch)
        latest = batch[-1]

        # Tab 1: Tabelle immer aktualisieren
        self._tab_table.update_data(latest)

        # Tab 2: Plotter nur wenn NICHT eingefroren
        if not self._tab_plotter.is_frozen:
            for v in batch:
                self._tab_plotter.append_data(v)

        # LED-Status
        self._node_active[self._active_node] = True
        led = self._led1 if self._active_node == 1 else self._led2
        self._set_led(led, connected=True)

    def _update_statusbar(self) -> None:
        self._lbl_pps.setText(f"{self._pkt_count} Pkt/s")
        self._pkt_count = 0

        # LED-Timeout: nach 3s ohne Daten → rot
        # (vereinfacht: nach 1s ohne Tick grauen wir die LED aus)
        # Wird verbessert in Phase 2 mit explizitem Heartbeat.

    # ══════════════════════════════════════════════════════════════════════════
    #  Slots
    # ══════════════════════════════════════════════════════════════════════════

    def _on_node_toggled(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        self._active_node = btn_id
        self._tab_table.clear_stats()
        self._tab_plotter.clear_buffer()
        self._sb.showMessage(f"Node {btn_id} aktiviert.", 2000)

    def _on_flash_clicked(self) -> None:
        n1 = self._chk_n1.isChecked()
        n2 = self._chk_n2.isChecked()

        if not (n1 or n2):
            self._sb.showMessage("⚠  Kein Flash-Ziel ausgewählt!", 3000)
            return

        hex_path, _ = QFileDialog.getOpenFileName(
            self,
            "Firmware-Datei wählen",
            str(Path.home()),
            "Intel Hex (*.hex);;Alle Dateien (*)",
        )
        if not hex_path:
            return

        self._btn_flash.setEnabled(False)
        self._btn_flash.setText("⏳  Wird geflasht…")

        targets = [f"Node {i}" for i, f in ((1, n1), (2, n2)) if f]
        self._sb.showMessage(f"Flashe {' + '.join(targets)}…")

        flash_nodes(
            hex_path,
            node1=n1,
            node2=n2,
            result_cb=lambda nid, ok, msg: (
                self._flash_bridge.result.emit(nid, ok, msg)
            ),
        )

    def _on_flash_result(self, node_id: int, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._sb.showMessage(
            f"{icon}  Node {node_id} Flash: {message}", 6000
        )
        self._btn_flash.setEnabled(True)
        self._btn_flash.setText("⚡  Firmware flashen…")

    # ══════════════════════════════════════════════════════════════════════════
    #  Hilfsmethoden
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _set_led(lbl: QLabel, connected: bool) -> None:
        color = "#2ecc71" if connected else "#e74c3c"
        lbl.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 11pt;"
        )

    def closeEvent(self, event) -> None:
        self._nm.stop()
        event.accept()


# ── Kleine Hilfsfunktion ──────────────────────────────────────────────────────
def _vsep() -> QFrame:
    """Vertikaler Trenner für Toolbars."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
