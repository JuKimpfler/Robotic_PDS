"""
tab_params.py — Tab 4: Parameter-Konfiguration
================================================
Phase-2-Platzhalter.
Geplant: QDataWidgetMapper-basierter Editor
         für 100–200 Systemparameter mit TCP-Übertragung.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class ParamEditorWidget(QWidget):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(
            "⚙️  Parameter-Konfiguration  —  Phase 2\n\n"
            "Geplante Funktionen:\n"
            "  • 100–200 Parameter in editierbarer Tabelle (QDataWidgetMapper)\n"
            "  • Konfigurationsdatei (.json / .yaml) als Backing-Store\n"
            "  • Validierung mit Min/Max-Grenzen pro Parameter\n"
            "  • [ Parameter übertragen ]  → TCP-Paket an aktiven Node\n"
            "  • [ Laden ] / [ Speichern ]  → lokale Konfigurationsdatei"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "font-size: 13pt; color: #666; "
            "border: 2px dashed #444; padding: 40px; border-radius: 8px;"
        )
        layout.addWidget(lbl)
