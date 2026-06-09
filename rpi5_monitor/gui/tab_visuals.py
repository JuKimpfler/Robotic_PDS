"""
tab_visuals.py — Tab 3: Grafische Systemansicht
=================================================
Phase-2-Platzhalter.
Geplant: Roboter-Schemazeichnung mit dynamischen
         Farb-Overlays basierend auf Live-Telemetrie.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class SystemVisualsWidget(QWidget):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(
            "🚧  Grafische Systemansicht  —  Phase 2\n\n"
            "Geplante Funktionen:\n"
            "  • Roboter-Schema als Bild laden  (QGraphicsView / pg.ImageItem)\n"
            "  • Farbliche Overlay-Regionen per Live-Telemetrie steuern\n"
            "  • Text-Callouts für kritische Sensorwerte\n"
            "  • Alarm-Markierungen bei Grenzwertüberschreitungen"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "font-size: 13pt; color: #666; "
            "border: 2px dashed #444; padding: 40px; border-radius: 8px;"
        )
        layout.addWidget(lbl)
