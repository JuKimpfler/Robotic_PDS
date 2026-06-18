"""
tab_visuals.py — Tab 3: Grafische Systemansicht
=================================================
• Vier Bilder untereinander in einem scrollbaren Bereich (je 1:1-Format).
• Frei positionierbare Text-Overlays (X/Y in % der Bildgröße).
• Konfiguration wird persistent in visuals_overlays.json gespeichert
  und beim nächsten Start automatisch wiederhergestellt.
• Darstellungs-Stil der Overlays ist pro Bild in IMAGE_STYLES konfigurierbar.

Ordnerstruktur:
    rpi5_monitor/bild/Bild1.png  …  Bild4.png
    rpi5_monitor/visuals_overlays.json   ← auto-generiert

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 KONFIGURATION  (hier anpassen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Darstellungs-Stile für Text-Overlays:
    ARROW    →  "Label → +1.234"   (Pfeil)
    COLON    →  "Label: +1.234"    (Doppelpunkt)
    TWO_LINE →  Label oben, Wert darunter (klassisch, größer)

Welcher Stil für welches Bild gilt: → IMAGE_STYLES (weiter unten)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient,
    QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QColorDialog, QDoubleSpinBox,
    QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QComboBox,
)

from config import MAX_FLOATS, VARIABLE_NAMES

Schwelle_ID = 90

log = logging.getLogger("tab_visuals")

# ── Pfade ─────────────────────────────────────────────────────────────────────
_BILD_DIR    = Path(__file__).resolve().parent.parent / "bild"
_CONFIG_FILE = Path(__file__).resolve().parent.parent / "visuals_overlays.json"

# ── Farb-Palette ──────────────────────────────────────────────────────────────
_PALETTE = [
    "#4ec9b0", "#f0c060", "#f48771", "#9cdcfe",
    "#ce9178", "#dcdcaa", "#c586c0", "#569cd6",
]


# ══════════════════════════════════════════════════════════════════════════════
#  Overlay-Stil-Konfiguration  ← HIER ANPASSEN
# ══════════════════════════════════════════════════════════════════════════════

class OverlayStyle:
    """
    Verfügbare Darstellungs-Stile für Text-Overlays.
    Einen dieser Werte in IMAGE_STYLES eintragen.
    """
    ARROW    = "arrow"      # "Label → +1.234"  (kompakt, einzeilig, Pfeil)
    COLON    = "colon"      # "Label: +1.234"   (kompakt, einzeilig, Doppelpunkt)
    TWO_LINE = "two_line"   # Label oben, Wert darunter (klassisch, etwas größer)


# ── Pro-Bild Stil-Zuweisung ───────────────────────────────────────────────────
# Schlüssel: Bild-Index 1–4   Wert: einer der OverlayStyle-Werte oben
IMAGE_STYLES: dict[int, str] = {
    1: OverlayStyle.TWO_LINE,      # Bild 1 → "Label → +1.234"
    2: OverlayStyle.COLON,      # Bild 2 → "Label: +1.234"
    3: OverlayStyle.ARROW,      # Bild 3 → "Label → +1.234"
    4: OverlayStyle.ARROW,   # Bild 4 → zweizeilig
}

# ── Overlay-Schriftgröße (pt) ─────────────────────────────────────────────────
# Gilt für die einzeiligen Stile (ARROW / COLON). TWO_LINE nutzt eigene Größen.
OVERLAY_FONT_SIZE     = 8    # pt  — Haupt-Font (einzeilig)
OVERLAY_FONT_SIZE_VAL = 10   # pt  — Wert-Font im TWO_LINE-Stil


# ══════════════════════════════════════════════════════════════════════════════
#  Datenklasse
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TextOverlay:
    """Ein positionierbarer Textblock auf einem Bild."""
    image_idx:   int   = 1
    label:       str   = "Label"
    channel_idx: int   = 0
    x_pct:       float = 5.0    # 0–100 % der Bildbreite
    y_pct:       float = 8.0    # 0–100 % der Bildhöhe
    color:       str   = "#4ec9b0"


# ── Standard-Konfiguration ────────────────────────────────────────────────────
DEFAULT_OVERLAYS: List[TextOverlay] = [
    TextOverlay(1, "Motor L",       0,   5.0,  8.0, "#4ec9b0"),
    TextOverlay(1, "Motor R",       1,   5.0, 22.0, "#4ec9b0"),
    TextOverlay(2, "Akku Spannung", 10,  5.0,  8.0, "#f0c060"),
    TextOverlay(2, "Akku Strom",    11,  5.0, 22.0, "#f48771"),
    TextOverlay(3, "Compass",        2,  5.0,  8.0, "#9cdcfe"),
    TextOverlay(3, "Ball X",         3,  5.0, 22.0, "#ce9178"),
    TextOverlay(4, "Ball Y",         4,  5.0,  8.0, "#dcdcaa"),
    TextOverlay(4, "Var_005",        5,  5.0, 22.0, "#c586c0"),
]


# ══════════════════════════════════════════════════════════════════════════════
#  Persistenz-Funktionen
# ══════════════════════════════════════════════════════════════════════════════

def save_overlays(overlays: List[TextOverlay]) -> None:
    """Speichert die Overlay-Konfiguration als JSON."""
    try:
        data = [asdict(ov) for ov in overlays]
        _CONFIG_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.debug("Overlays gespeichert: %s", _CONFIG_FILE)
    except Exception as exc:
        log.warning("Overlay-Speichern fehlgeschlagen: %s", exc)


def load_overlays() -> List[TextOverlay]:
    """
    Lädt die Overlay-Konfiguration aus JSON.
    Gibt DEFAULT_OVERLAYS zurück wenn die Datei fehlt oder fehlerhaft ist.
    """
    if not _CONFIG_FILE.exists():
        log.info("Keine gespeicherte Overlay-Konfiguration gefunden – nutze Defaults.")
        return list(DEFAULT_OVERLAYS)
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        overlays = []
        for d in raw:
            overlays.append(TextOverlay(
                image_idx   = int(d.get("image_idx",   1)),
                label       = str(d.get("label",       "Label")),
                channel_idx = int(d.get("channel_idx", 0)),
                x_pct       = float(d.get("x_pct",     5.0)),
                y_pct       = float(d.get("y_pct",     8.0)),
                color       = str(d.get("color",       "#4ec9b0")),
            ))
        log.info("Overlays geladen: %d Eintraege aus %s", len(overlays), _CONFIG_FILE)
        return overlays
    except Exception as exc:
        log.warning("Overlay-JSON fehlerhaft (%s) – nutze Defaults.", exc)
        return list(DEFAULT_OVERLAYS)


# ══════════════════════════════════════════════════════════════════════════════
#  ImageOverlayWidget
# ══════════════════════════════════════════════════════════════════════════════

class ImageOverlayWidget(QWidget):
    """
    Zeigt ein PNG-Bild (1:1) skaliert + Text-Overlays via QPainter.
    Hält automatisch 1:1-Seitenverhältnis (heightForWidth).
    Der Darstellungs-Stil wird aus IMAGE_STYLES gelesen.
    """

    def __init__(self, image_idx: int, parent=None) -> None:
        super().__init__(parent)
        self._image_idx = image_idx
        self._pixmap: Optional[QPixmap] = None
        self._overlays: List[TextOverlay] = []
        self._values   = np.zeros(MAX_FLOATS, dtype=np.float32)
        # Stil aus globaler Konfig lesen
        self._style = IMAGE_STYLES.get(image_idx, OverlayStyle.ARROW)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 200)
        self._load_image()

    # ── 1:1-Seitenverhältnis ──────────────────────────────────────────────────

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return w

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(500, 500)

    # ── Bild laden ────────────────────────────────────────────────────────────

    def _load_image(self) -> None:
        path = _BILD_DIR / f"Bild{self._image_idx}.png"
        if path.exists():
            px = QPixmap(str(path))
            if not px.isNull():
                self._pixmap = px
                return
        self._pixmap = None

    def reload_image(self) -> None:
        self._load_image()
        self.update()

    # ── Öffentliche Schnittstelle ─────────────────────────────────────────────

    def set_overlays(self, overlays: List[TextOverlay]) -> None:
        self._overlays = [o for o in overlays if o.image_idx == self._image_idx]
        self.update()

    def update_values(self, values: np.ndarray) -> None:
        self._values = values
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self._draw_image(painter)
        self._draw_overlays(painter, rect)
        painter.end()

    def _draw_image(self, painter: QPainter) -> QRectF:
        w, h = self.width(), self.height()
        if self._pixmap and not self._pixmap.isNull():
            side = min(w, h)
            x    = (w - side) / 2
            y    = (h - side) / 2
            dst  = QRectF(x, y, float(side), float(side))
            painter.drawPixmap(dst.toRect(), self._pixmap)
            return dst
        return self._draw_placeholder(painter, w, h)

    def _draw_placeholder(self, painter: QPainter, w: int, h: int) -> QRectF:
        side = min(w, h)
        x    = (w - side) / 2
        y    = (h - side) / 2
        rect = QRectF(x, y, float(side), float(side))

        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        base = [("#1a2a3a","#0d1a26"), ("#1a3a2a","#0d261a"),
                ("#2a1a3a","#1a0d26"), ("#3a2a1a","#261a0d")]
        c1, c2 = base[(self._image_idx - 1) % 4]
        grad.setColorAt(0, QColor(c1))
        grad.setColorAt(1, QColor(c2))
        painter.fillRect(rect, grad)

        painter.setPen(QPen(QColor("#333"), 1))
        painter.drawRect(rect)

        painter.setPen(QPen(QColor("#2a3a4a"), 1))
        cx, cy = rect.center().x(), rect.center().y()
        for r in range(40, int(side // 2), 40):
            painter.drawEllipse(QPointF(cx, cy), float(r), float(r))

        painter.setPen(QColor("#556677"))
        f = QFont("Segoe UI", 13)
        f.setWeight(QFont.Weight.Medium)
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                         f"Bild {self._image_idx}\n(Kein Bild gefunden)")
        return rect

    def _draw_overlays(self, painter: QPainter, img_rect: QRectF) -> None:
        if not self._overlays:
            return

        iw = img_rect.width()
        ih = img_rect.height()
        ox = img_rect.x()
        oy = img_rect.y()

        if self._style == OverlayStyle.TWO_LINE:
            self._draw_overlays_two_line(painter, ox, oy, iw, ih)
        else:
            self._draw_overlays_inline(painter, ox, oy, iw, ih)

    # ── Einzeiliger Stil (ARROW / COLON) ─────────────────────────────────────

    def _draw_overlays_inline(self, painter: QPainter,
                               ox: float, oy: float,
                               iw: float, ih: float) -> None:
        """Kompakter einzeiliger Overlay: 'Label → +1.234' oder 'Label: +1.234'."""
        sep = " → " if self._style == OverlayStyle.ARROW else ": "

        font = QFont("Segoe UI", OVERLAY_FONT_SIZE)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        line_h = fm.height()
        pad_x  = 6
        pad_y  = 3

        for ov in self._overlays:
            px = ox + (ov.x_pct / 100.0) * iw
            py = oy + (ov.y_pct / 100.0) * ih

            idx = max(0, min(ov.channel_idx, len(self._values) - 1))
            val = float(self._values[idx]) if len(self._values) > 0 else 0.0
            if self._style == OverlayStyle.COLON:
                if  val > self._values[Schwelle_ID]: 
                    text = f"{ov.label}{sep}⭕"
                    ov.color = "#c90505"
                else :
                    text = f"{ov.label}{sep}-"
                    ov.color = "#19f3ec"
            else:
                text = f"{ov.label}{sep}{val:+.1f}"

            box_w = fm.horizontalAdvance(text) + pad_x * 2 + 4  # +4 für Akzentbalken
            box_h = line_h + pad_y * 2

            # Schatten
            painter.fillRect(
                QRectF(px + 2, py + 2, box_w, box_h), QColor(0, 0, 0, 80)
            )
            # Hintergrund
            painter.fillRect(
                QRectF(px, py, box_w, box_h), QColor(10, 10, 15, 215)
            )
            # Akzentbalken links (2 px)
            painter.fillRect(QRectF(px, py, 2, box_h), QColor(ov.color))
            # Rahmen
            painter.setPen(QPen(QColor(ov.color).darker(150), 0.7))
            painter.drawRect(QRectF(px, py, box_w, box_h))

            # Text
            painter.setPen(QColor(ov.color))
            painter.setFont(font)
            painter.drawText(
                QRectF(px + pad_x + 2, py + pad_y, box_w - pad_x - 4, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

    # ── Zweizeiliger Stil (TWO_LINE) ──────────────────────────────────────────

    def _draw_overlays_two_line(self, painter: QPainter,
                                 ox: float, oy: float,
                                 iw: float, ih: float) -> None:
        """Klassischer zweizeiliger Overlay: Name oben, Wert darunter."""
        name_font = QFont("Segoe UI", OVERLAY_FONT_SIZE)
        name_font.setWeight(QFont.Weight.Medium)
        val_font  = QFont("Segoe UI", OVERLAY_FONT_SIZE_VAL)
        val_font.setWeight(QFont.Weight.Bold)

        nm_fm = QFontMetrics(name_font)
        vl_fm = QFontMetrics(val_font)

        for ov in self._overlays:
            px = ox + (ov.x_pct / 100.0) * iw
            py = oy + (ov.y_pct / 100.0) * ih

            idx   = max(0, min(ov.channel_idx, len(self._values) - 1))
            val   = float(self._values[idx]) if len(self._values) > 0 else 0.0
            s_val = f"{val:+.3f}"

            w_name = nm_fm.horizontalAdvance(ov.label)
            w_val  = vl_fm.horizontalAdvance(s_val)
            box_w  = max(w_name, w_val) + 16
            lh_n   = nm_fm.height()
            lh_v   = vl_fm.height()
            box_h  = lh_n + lh_v + 12

            painter.fillRect(QRectF(px + 2, py + 2, box_w, box_h), QColor(0, 0, 0, 80))
            painter.fillRect(QRectF(px, py, box_w, box_h), QColor(10, 10, 15, 215))
            painter.fillRect(QRectF(px, py, 3, box_h), QColor(ov.color))
            painter.setPen(QPen(QColor(ov.color).darker(140), 0.8))
            painter.drawRect(QRectF(px, py, box_w, box_h))

            name_col = QColor(ov.color).lighter(130)
            name_col.setAlpha(185)
            painter.setPen(name_col)
            painter.setFont(name_font)
            painter.drawText(
                QRectF(px + 7, py + 4, box_w - 9, lh_n),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                ov.label,
            )
            painter.setPen(QColor(ov.color))
            painter.setFont(val_font)
            painter.drawText(
                QRectF(px + 7, py + 4 + lh_n + 1, box_w - 9, lh_v),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                s_val,
            )


# ══════════════════════════════════════════════════════════════════════════════
#  OverlayConfigTable
# ══════════════════════════════════════════════════════════════════════════════

COL_IMG   = 0
COL_LABEL = 1
COL_CHAN  = 2
COL_X     = 3
COL_Y     = 4
COL_COLOR = 5
N_COLS    = 6
HEADERS   = ["Bild", "Label", "Kanal", "X (%)", "Y (%)", "Farbe"]


class _ColorButton(QPushButton):
    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(44, 22)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color}; border: 1px solid #555;"
            f"  border-radius: 3px; }}"
            f"QPushButton:hover {{ border: 1px solid #aaa; }}"
        )

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Farbe wählen")
        if c.isValid():
            self._color = c.name()
            self._refresh()

    @property
    def color(self) -> str:
        return self._color


class OverlayConfigTable(QWidget):

    def __init__(self, overlays: List[TextOverlay], parent=None) -> None:
        super().__init__(parent)
        self._overlays = list(overlays)
        self._callback: Optional[Callable] = None
        self._building = False
        self._setup_ui()

    def set_callback(self, cb: Callable) -> None:
        self._callback = cb

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        title = QLabel("⚙  Overlay-Konfiguration")
        title.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #9cdcfe; padding: 2px 0;"
        )
        layout.addWidget(title)

        hint = QLabel("X / Y in % der Bildgröße  •  Änderungen werden automatisch gespeichert")
        hint.setStyleSheet("color: #666; font-size: 8pt;")
        layout.addWidget(hint)

        self._table = QTableWidget(0, N_COLS)
        self._table.setHorizontalHeaderLabels(HEADERS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self._table.verticalHeader().hide()
        self._table.setStyleSheet(
            "QTableWidget { background: #1e1e1e; gridline-color: #2d2d30; }"
            "QTableWidget::item { padding: 2px 4px; color: #d4d4d4; }"
            "QTableWidget::item:selected { background: #264f78; }"
            "QHeaderView::section { background: #252526; color: #9cdcfe;"
            "  padding: 5px; border: none; border-bottom: 2px solid #007acc;"
            "  font-weight: bold; }"
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(COL_IMG,   QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_LABEL, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_CHAN,  QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_X,     QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_Y,     QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(COL_COLOR, QHeaderView.ResizeMode.ResizeToContents)

        self._table.itemChanged.connect(self._on_item_changed)
        self._populate()
        layout.addWidget(self._table)

        # Buttons
        btn_row = QHBoxLayout()
        for text, style, slot in [
            ("＋  Hinzufügen",
             "background:#264f78;color:white;border-radius:4px;padding:5px 12px;",
             self._add_row),
            ("－  Entfernen",
             "background:#5a1a1a;color:#f48771;border-radius:4px;padding:5px 12px;",
             self._del_row),
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet(
                f"QPushButton {{ {style} }}"
                f"QPushButton:hover {{ opacity: 0.85; }}"
            )
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)

        btn_row.addStretch()

        # Gespeichert-Label
        self._lbl_saved = QLabel("")
        self._lbl_saved.setStyleSheet("color: #4ec9b0; font-size: 8pt;")
        btn_row.addWidget(self._lbl_saved)
        layout.addLayout(btn_row)

    # ── Befüllen ──────────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._building = True
        self._table.setRowCount(0)
        for ov in self._overlays:
            self._append_row_widget(ov)
        self._building = False

    def _append_row_widget(self, ov: TextOverlay) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._building = True

        # Bild-Combo
        cb = QComboBox()
        cb.addItems(["1", "2", "3", "4"])
        cb.setCurrentIndex(max(0, ov.image_idx - 1))
        cb.setStyleSheet("background:#2d2d30;color:#d4d4d4;border:none;padding:2px;")
        cb.currentIndexChanged.connect(lambda _: self._sync_from_table())
        self._table.setCellWidget(row, COL_IMG, cb)

        # Label
        self._table.setItem(row, COL_LABEL, QTableWidgetItem(ov.label))

        # Kanal-SpinBox
        s_chan = QSpinBox()
        s_chan.setRange(0, MAX_FLOATS - 1)
        s_chan.setValue(ov.channel_idx)
        s_chan.setStyleSheet("QSpinBox{background:#2d2d30;color:#d4d4d4;border:none;padding:1px;}")
        s_chan.valueChanged.connect(lambda _: self._sync_from_table())
        self._table.setCellWidget(row, COL_CHAN, s_chan)

        # X-SpinBox
        s_x = QDoubleSpinBox()
        s_x.setRange(0.0, 100.0)
        s_x.setSingleStep(1.0)
        s_x.setDecimals(1)
        s_x.setValue(ov.x_pct)
        s_x.setStyleSheet("QDoubleSpinBox{background:#2d2d30;color:#d4d4d4;border:none;padding:1px;}")
        s_x.valueChanged.connect(lambda _: self._sync_from_table())
        self._table.setCellWidget(row, COL_X, s_x)

        # Y-SpinBox
        s_y = QDoubleSpinBox()
        s_y.setRange(0.0, 100.0)
        s_y.setSingleStep(1.0)
        s_y.setDecimals(1)
        s_y.setValue(ov.y_pct)
        s_y.setStyleSheet("QDoubleSpinBox{background:#2d2d30;color:#d4d4d4;border:none;padding:1px;}")
        s_y.valueChanged.connect(lambda _: self._sync_from_table())
        self._table.setCellWidget(row, COL_Y, s_y)

        # Farb-Button
        col_btn = _ColorButton(ov.color)
        col_btn.clicked.connect(lambda checked=False: QTimer.singleShot(250, self._sync_from_table))
        self._table.setCellWidget(row, COL_COLOR, col_btn)

        self._table.setRowHeight(row, 28)
        self._building = False

    # ── Sync ──────────────────────────────────────────────────────────────────

    def _sync_from_table(self) -> None:
        if self._building:
            return
        overlays: List[TextOverlay] = []
        for row in range(self._table.rowCount()):
            img_cb   = self._table.cellWidget(row, COL_IMG)
            lbl_item = self._table.item(row, COL_LABEL)
            s_chan   = self._table.cellWidget(row, COL_CHAN)
            s_x      = self._table.cellWidget(row, COL_X)
            s_y      = self._table.cellWidget(row, COL_Y)
            col_btn  = self._table.cellWidget(row, COL_COLOR)

            if not all([img_cb, lbl_item, s_chan, s_x, s_y, col_btn]):
                continue
            overlays.append(TextOverlay(
                image_idx   = img_cb.currentIndex() + 1,
                label       = lbl_item.text(),
                channel_idx = s_chan.value(),
                x_pct       = s_x.value(),
                y_pct       = s_y.value(),
                color       = col_btn.color,
            ))

        self._overlays = overlays

        # Sofort speichern
        save_overlays(overlays)
        self._lbl_saved.setText("● gespeichert")
        QTimer.singleShot(2500, lambda: self._lbl_saved.setText(""))

        if self._callback:
            self._callback(overlays)

    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        if not self._building:
            self._sync_from_table()

    def _add_row(self) -> None:
        color = _PALETTE[len(self._overlays) % len(_PALETTE)]
        ov = TextOverlay(1, "Neu", 0, 5.0, 5.0, color)
        self._overlays.append(ov)
        self._append_row_widget(ov)
        if self._callback:
            self._callback(self._overlays)
        save_overlays(self._overlays)

    def _del_row(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedItems()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self._sync_from_table()

    def get_overlays(self) -> List[TextOverlay]:
        return list(self._overlays)


# ══════════════════════════════════════════════════════════════════════════════
#  SystemVisualsWidget — Haupt-Widget
# ══════════════════════════════════════════════════════════════════════════════

class SystemVisualsWidget(QWidget):
    """
    Links: Scrollbarer Bereich mit 4 Bildern untereinander (je 1:1, groß).
    Rechts: Overlay-Konfigurations-Tabelle (persistent gespeichert).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values = np.zeros(MAX_FLOATS, dtype=np.float32)

        # Overlays aus Datei laden (oder Defaults)
        self._overlays = load_overlays()
        self._setup_ui()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(7)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #007acc; }"
        )

        # ── Linke Seite: Scroll-Bereich mit Bildern ───────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { background: #141414; border: none; }"
            "QScrollBar:vertical { width: 10px; background: #1e1e1e; }"
            "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 4px; min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: #555; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        # Inner container (wird vertikal gestackt)
        inner = QWidget()
        inner.setStyleSheet("background: #141414;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.setSpacing(10)

        self._img_widgets: List[ImageOverlayWidget] = []

        for idx in range(1, 5):
            frame = QFrame()
            frame.setStyleSheet(
                "QFrame { border: 1px solid #2d2d30; border-radius: 6px;"
                " background: #1a1a1a; }"
            )
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(4, 4, 4, 4)
            fl.setSpacing(3)

            # ── Titelleiste ──────────────────────────────────────────────────
            title_bar = QWidget()
            title_bar.setFixedHeight(26)
            title_bar.setStyleSheet(
                "background: #252526; border-radius: 3px;"
                " border: none;"
            )
            tb_layout = QHBoxLayout(title_bar)
            tb_layout.setContentsMargins(10, 0, 6, 0)
            tb_layout.setSpacing(6)

            dot = QLabel("●")
            dot.setStyleSheet("color: #007acc; font-size: 9pt; border: none;")
            lbl_t = QLabel(f"Bild {idx}  —  {_BILD_DIR / f'Bild{idx}.png'}")
            lbl_t.setStyleSheet(
                "color: #9cdcfe; font-size: 9pt; font-weight: bold; border: none;"
            )
            tb_layout.addWidget(dot)
            tb_layout.addWidget(lbl_t)
            tb_layout.addStretch()

            btn_reload = QPushButton("↺ Neu laden")
            btn_reload.setFixedHeight(20)
            btn_reload.setStyleSheet(
                "QPushButton { background: none; color: #555; border: none;"
                "  font-size: 8pt; padding: 0 4px; }"
                "QPushButton:hover { color: #9cdcfe; }"
            )
            tb_layout.addWidget(btn_reload)

            fl.addWidget(title_bar)

            # ── Bild-Widget ──────────────────────────────────────────────────
            iw = ImageOverlayWidget(idx)
            self._img_widgets.append(iw)
            fl.addWidget(iw, stretch=1)

            btn_reload.clicked.connect(iw.reload_image)
            inner_layout.addWidget(frame)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        splitter.addWidget(scroll)

        # ── Rechte Seite: Konfig-Panel ────────────────────────────────────────
        right_panel = QWidget()
        right_panel.setStyleSheet("background: #1e1e1e;")
        right_panel.setMinimumWidth(500)
        right_panel.setMaximumWidth(700)
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(0, 0, 0, 0)

        self._config_table = OverlayConfigTable(self._overlays)
        self._config_table.set_callback(self._on_overlays_changed)
        rp_layout.addWidget(self._config_table)

        splitter.addWidget(right_panel)
        splitter.setSizes([750, 330])

        root.addWidget(splitter)

        # Initiale Overlays setzen
        self._on_overlays_changed(self._overlays)

    # ── Daten-Update ──────────────────────────────────────────────────────────

    def update_data(self, values: np.ndarray) -> None:
        """Wird vom MainWindow ~30×/s aufgerufen."""
        self._values = values
        for iw in self._img_widgets:
            iw.update_values(values)

    # ── Overlay-Callback ──────────────────────────────────────────────────────

    def _on_overlays_changed(self, overlays: List[TextOverlay]) -> None:
        for iw in self._img_widgets:
            iw.set_overlays(overlays)
