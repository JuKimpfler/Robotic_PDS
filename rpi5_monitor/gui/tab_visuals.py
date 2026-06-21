"""
tab_visuals.py — Tab 3: Grafische Systemansicht mit Gruppen-Dropdown und Custom Graphics
========================================================================================
• Zeigt pro ausgewählter Gruppe ein 1:1-Bild mit frei positionierbaren Overlays.
• Die Overlays passen sich in ihrer Größe dem kleineren Bild adaptiv an.
• Rechts daneben werden konfigurierbare Grafiken (Tachos, Vektoren, Rotationspfeile, Tabellen)
  angezeigt, die aus visuals_overlays.json geladen werden.
• Ein einklappbares Einstellungs-Panel an der rechten Seite erlaubt das Editieren der Overlays.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient,
    QPainter, QPen, QPixmap, QBrush, QPolygonF
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QColorDialog, QDoubleSpinBox,
    QFrame, QHBoxLayout, QHeaderView, QGridLayout,
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

class OverlayStyle:
    ARROW    = "arrow"      # "Label → +1.234"  (kompakt, einzeilig, Pfeil)
    COLON    = "colon"      # "Label: +1.234"   (kompakt, einzeilig, Doppelpunkt)
    TWO_LINE = "two_line"   # Label oben, Wert darunter (klassisch, etwas größer)

IMAGE_STYLES: dict[int, str] = {
    1: OverlayStyle.TWO_LINE,
    2: OverlayStyle.COLON,
    3: OverlayStyle.ARROW,
    4: OverlayStyle.ARROW,
}

OVERLAY_FONT_SIZE     = 8
OVERLAY_FONT_SIZE_VAL = 10

@dataclass
class TextOverlay:
    """Ein positionierbarer Textblock auf einem Bild."""
    image_idx:   int   = 1
    label:       str   = "Label"
    channel_idx: int   = 0
    x_pct:       float = 5.0    # 0–100 % der Bildbreite
    y_pct:       float = 8.0    # 0–100 % der Bildhöhe
    color:       str   = "#4ec9b0"

# ── Helper for parsing channel specs ──────────────────────────────────────────
def parse_channels(channel_spec) -> List[int]:
    if isinstance(channel_spec, int):
        return [channel_spec]
    if isinstance(channel_spec, list):
        result = []
        for item in channel_spec:
            result.extend(parse_channels(item))
        return result
    if isinstance(channel_spec, str):
        result = []
        parts = [p.strip() for p in channel_spec.split(",")]
        for part in parts:
            if "-" in part:
                try:
                    start, end = part.split("-")
                    result.extend(range(int(start), int(end) + 1))
                except ValueError:
                    pass
            else:
                try:
                    result.append(int(part))
                except ValueError:
                    pass
        return result
    return []

# ── Persistence & Migration ───────────────────────────────────────────────────
def load_config() -> dict:
    if not _CONFIG_FILE.exists():
        log.info("Keine Konfigurationsdatei gefunden – erstelle Default.")
        return create_default_config()
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            log.info("Altes JSON-Format erkannt – starte Migration.")
            return migrate_old_config(raw)
        elif isinstance(raw, dict) and "groups" in raw:
            return raw
        else:
            log.warning("Unbekanntes Konfigurationsformat. Erstelle Default.")
            return create_default_config()
    except Exception as exc:
        log.warning("Fehler beim Laden der Konfig (%s) – nutze Default.", exc)
        return create_default_config()

def save_config(config: dict) -> None:
    try:
        _CONFIG_FILE.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.debug("Konfiguration gespeichert: %s", _CONFIG_FILE)
    except Exception as exc:
        log.warning("Konfiguration-Speichern fehlgeschlagen: %s", exc)

def migrate_old_config(old_list: list) -> dict:
    groups = []
    for idx in range(1, 5):
        group_overlays = []
        for item in old_list:
            if int(item.get("image_idx", 1)) == idx:
                group_overlays.append({
                    "label": str(item.get("label", "Label")),
                    "channel_idx": int(item.get("channel_idx", 0)),
                    "x_pct": float(item.get("x_pct", 5.0)),
                    "y_pct": float(item.get("y_pct", 5.0)),
                    "color": str(item.get("color", "#4ec9b0"))
                })
        
        graphics = []
        if idx == 1:
            graphics = [
                {"type": "gauge", "label": "Motor L Speed", "channel": 0, "min": -5.0, "max": 5.0},
                {"type": "gauge", "label": "Motor R Speed", "channel": 1, "min": -5.0, "max": 5.0},
                {"type": "gauge", "label": "Akku-Spannung", "channel": 10, "min": 0.0, "max": 24.0},
                {"type": "gauge", "label": "System-Temp", "channel": 11, "min": 0.0, "max": 100.0},
                {"type": "rotation", "label": "Rad FL", "channel": 2},
                {"type": "rotation", "label": "Rad FR", "channel": 3},
                {"type": "rotation", "label": "Rad RL", "channel": 4},
                {"type": "rotation", "label": "Rad RR", "channel": 5},
                {"type": "vector", "label": "Bewegungsrichtung", "channel_angle": 6, "channel_speed": 7, "max_val": 10.0},
                {"type": "vector", "label": "Windrichtung", "channel_angle": 8, "channel_speed": 9, "max_val": 5.0},
                {"type": "table", "title": "System-Status (0-9)", "channels": "0-9"}
            ]
        elif idx == 2:
            graphics = [
                {"type": "table", "title": "Kanalwerte 50-66", "channels": "50-66"}
            ]
        elif idx == 3:
            graphics = [
                {"type": "table", "title": "Kanalwerte 50-66", "channels": "50-66"}
            ]
        else:
            graphics = [
                {"type": "table", "title": "Statuskanäle", "channels": "0-9"}
            ]

        groups.append({
            "name": f"Gruppe {idx} (Bild {idx})",
            "image_idx": idx,
            "overlays": group_overlays,
            "graphics": graphics
        })
    
    new_config = {"groups": groups}
    save_config(new_config)
    return new_config

def create_default_config() -> dict:
    groups = []
    for idx in range(1, 5):
        groups.append({
            "name": f"Gruppe {idx} (Bild {idx})",
            "image_idx": idx,
            "overlays": [
                {
                    "label": f"Demo {idx}A",
                    "channel_idx": idx * 10,
                    "x_pct": 10.0,
                    "y_pct": 15.0,
                    "color": "#4ec9b0"
                }
            ],
            "graphics": [
                {"type": "gauge", "label": f"Kanal {idx*10} Tacho", "channel": idx * 10, "min": -10.0, "max": 10.0},
                {"type": "rotation", "label": f"Rad {idx}", "channel": idx * 10 + 1},
                {"type": "vector", "label": f"Richtung {idx}", "channel_angle": idx * 10 + 2, "channel_speed": idx * 10 + 3, "max_val": 10.0},
                {"type": "table", "title": f"Kanäle {idx*10}-{idx*10+5}", "channels": f"{idx*10}-{idx*10+5}"}
            ]
        })
    cfg = {"groups": groups}
    save_config(cfg)
    return cfg

# ── Custom Graphics Widgets ───────────────────────────────────────────────────
class GaugeWidget(QWidget):
    def __init__(self, label: str, channel: int, min_val: float = -1.0, max_val: float = 1.0, parent=None):
        super().__init__(parent)
        self.label = label
        self.channel = channel
        self.min_val = min_val
        self.max_val = max_val
        self.value = 0.0
        self.setMinimumSize(130, 105)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_value(self, values: np.ndarray):
        if self.channel < len(values):
            self.value = float(values[self.channel])
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        # Gauge is a half circle. Let diameter fit width or height comfortably.
        # h-42 leaves room for title text at the top and badge at the bottom.
        D = min(w - 16, (h - 55) * 2)
        R = D / 2
        cx = w / 2
        cy = h - 24  # Base line of the half-circle

        # Draw Title (ends at y=18, circular arc starts at top >= 22)
        painter.setPen(QColor("#9cdcfe"))
        f_title = QFont("Segoe UI", 8, QFont.Weight.Medium)
        painter.setFont(f_title)
        painter.drawText(QRectF(0, 2, w, 16), Qt.AlignmentFlag.AlignCenter, self.label)

        # Bounding box for full circle (top half will be used)
        rect = QRectF(cx - R, cy - R, R * 2, R * 2)

        # Draw Dial Background Arc (180 degrees, from left to right)
        pen_bg = QPen(QColor("#252526"), 8)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 180 * 16, -180 * 16)

        # Draw Ticks
        for i in range(9):
            angle = 180.0 - i * 22.5
            rad = math.radians(angle)
            
            # Highlight extremes and center with accent colors
            if i == 0 or i == 8:
                tick_col = QColor("#ff5f5f")  # Red warning at min/max
            elif i == 1 or i == 7:
                tick_col = QColor("#ffb86c")  # Orange warning
            elif i == 4:
                tick_col = QColor("#9cdcfe")  # Cyan center
            else:
                tick_col = QColor("#555555")  # Muted gray for normal ticks
                
            painter.setPen(QPen(tick_col, 1.5))
            x1 = cx + (R - 7) * math.cos(rad)
            y1 = cy - (R - 7) * math.sin(rad)
            x2 = cx + R * math.cos(rad)
            y2 = cy - R * math.sin(rad)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Draw Dial Value Arc
        val_clamped = max(self.min_val, min(self.max_val, self.value))
        range_val = self.max_val - self.min_val
        t = (val_clamped - self.min_val) / range_val if range_val != 0 else 0.0
        
        color = QColor("#19f3ec")
        pen_val = QPen(color, 8)
        pen_val.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_val)
        painter.drawArc(rect, 180 * 16, int(-t * 180 * 16))

        # Draw Needle as a tapered triangle
        angle_deg = 180.0 - t * 180.0
        angle_rad = math.radians(angle_deg)
        
        tip_x = cx + (R - 5) * math.cos(angle_rad)
        tip_y = cy - (R - 5) * math.sin(angle_rad)
        
        base_left_x = cx + 4 * math.cos(angle_rad + math.pi / 2)
        base_left_y = cy - 4 * math.sin(angle_rad + math.pi / 2)
        
        base_right_x = cx + 4 * math.cos(angle_rad - math.pi / 2)
        base_right_y = cy - 4 * math.sin(angle_rad - math.pi / 2)

        painter.setBrush(QBrush(QColor("#f48771")))
        painter.setPen(Qt.PenStyle.NoPen)
        poly = QPolygonF([QPointF(tip_x, tip_y), QPointF(base_left_x, base_left_y), QPointF(base_right_x, base_right_y)])
        painter.drawPolygon(poly)

        # Center pivot cap
        painter.setBrush(QColor("#f48771").darker(120))
        painter.drawEllipse(QPointF(cx, cy), 5, 5)
        painter.setBrush(QColor("#f48771"))
        painter.drawEllipse(QPointF(cx, cy), 3, 3)

        # Draw Digital Value Text inside a clean badge at the bottom
        val_str = f"{self.value:+.2f}"
        f_val = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(f_val)
        fm = QFontMetrics(f_val)
        val_w = fm.horizontalAdvance(val_str) + 12
        val_h = fm.height() + 2
        
        badge_rect = QRectF(cx - val_w / 2, h - val_h - 1, val_w, val_h)
        painter.setBrush(QBrush(QColor("#1e1e1e")))
        painter.setPen(QPen(QColor("#2d2d30"), 1))
        painter.drawRoundedRect(badge_rect, 3, 3)
        
        painter.setPen(QColor("#ffffff"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, val_str)
        
        painter.end()

class VectorWidget(QWidget):
    def __init__(self, label: str, channel_x: int = -1, channel_y: int = -1, 
                 channel_angle: int = -1, channel_speed: int = -1, 
                 scale: float = 1.0, max_val: float = 10.0, parent=None):
        super().__init__(parent)
        self.label = label
        self.channel_x = channel_x
        self.channel_y = channel_y
        self.channel_angle = channel_angle
        self.channel_speed = channel_speed
        self.scale = scale
        self.max_val = max_val
        self.val_x = 0.0
        self.val_y = 0.0
        self.val_angle = 0.0
        self.val_speed = 0.0
        
        self.setMinimumSize(100, 95)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_value(self, values: np.ndarray):
        updated = False
        if self.channel_x >= 0 and self.channel_x < len(values):
            self.val_x = float(values[self.channel_x])
            updated = True
        if self.channel_y >= 0 and self.channel_y < len(values):
            self.val_y = float(values[self.channel_y])
            updated = True
        if self.channel_angle >= 0 and self.channel_angle < len(values):
            self.val_angle = float(values[self.channel_angle])
            updated = True
        if self.channel_speed >= 0 and self.channel_speed < len(values):
            self.val_speed = float(values[self.channel_speed])
            updated = True
        if updated:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        R = min(w, h) / 2 - 14
        cx, cy = w / 2, h / 2 + 6

        # Draw Title
        painter.setPen(QColor("#9cdcfe"))
        f_title = QFont("Segoe UI", 8, QFont.Weight.Medium)
        painter.setFont(f_title)
        painter.drawText(QRectF(0, 2, w, 16), Qt.AlignmentFlag.AlignCenter, self.label)

        # Draw target board (3 concentric circles representing R/3, 2*R/3, R)
        painter.setPen(QPen(QColor("#2d2d30"), 1, Qt.PenStyle.SolidLine))
        painter.drawEllipse(QPointF(cx, cy), R / 3, R / 3)
        painter.drawEllipse(QPointF(cx, cy), 2 * R / 3, 2 * R / 3)
        painter.drawEllipse(QPointF(cx, cy), R, R)

        # Draw thin target crosshairs
        painter.setPen(QPen(QColor("#2d2d30"), 0.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(cx - R, cy), QPointF(cx + R, cy))
        painter.drawLine(QPointF(cx, cy - R), QPointF(cx, cy + R))

        # Calculate angle and speed
        if self.channel_angle >= 0:
            speed = self.val_speed
            angle = self.val_angle
        else:
            # Fallback to Cartesian: X is horizontal/sin, Y is vertical/cos (CW positive)
            speed = math.sqrt(self.val_x**2 + self.val_y**2)
            angle = math.degrees(math.atan2(self.val_x, self.val_y))

        # Convert polar to screen coordinates
        # Angle 0 is top (upward), + angle goes CW, - angle goes CCW
        rad = math.radians(angle)
        length = (speed / self.max_val) * R * self.scale if self.max_val > 0 else 0.0
        
        # Clamp length to maximum radius R
        if length > R:
            length = R

        dx = length * math.sin(rad)
        dy = -length * math.cos(rad) # Y goes down in screen coordinates

        ex, ey = cx + dx, cy + dy

        if length > 2:
            arrow_size = 11
            
            # Unit direction vector of the arrow in screen coordinates
            ux = dx / length
            uy = dy / length
            
            # End of the shaft line stops at the arrowhead base
            bx = ex - arrow_size * ux
            by = ey - arrow_size * uy

            # Draw Vector Arrow shaft
            pen_arrow = QPen(QColor("#4ec9b0"), 3)
            pen_arrow.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen_arrow)
            painter.drawLine(QPointF(cx, cy), QPointF(bx, by))

            # Draw arrowhead wings
            theta = math.atan2(uy, ux)
            w1_x = ex - arrow_size * math.cos(theta - math.pi / 6)
            w1_y = ey - arrow_size * math.sin(theta - math.pi / 6)
            w2_x = ex - arrow_size * math.cos(theta + math.pi / 6)
            w2_y = ey - arrow_size * math.sin(theta + math.pi / 6)

            painter.setBrush(QBrush(QColor("#4ec9b0")))
            painter.setPen(Qt.PenStyle.NoPen)
            poly = QPolygonF([QPointF(ex, ey), QPointF(w1_x, w1_y), QPointF(w2_x, w2_y)])
            painter.drawPolygon(poly)

        # Center dot
        painter.setBrush(QColor("#4ec9b0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 3, 3)
        painter.end()

class RotationWidget(QWidget):
    def __init__(self, label: str, channel: int, parent=None):
        super().__init__(parent)
        self.label = label
        self.channel = channel
        self.value = 0.0
        self.setMinimumSize(100, 95)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_value(self, values: np.ndarray):
        if self.channel < len(values):
            self.value = float(values[self.channel])
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        R = min(w, h) / 2 - 14
        cx, cy = w / 2, h / 2 + 6
        rect = QRectF(cx - R, cy - R, R * 2, R * 2)

        # Draw Title
        painter.setPen(QColor("#9cdcfe"))
        f_title = QFont("Segoe UI", 8, QFont.Weight.Medium)
        painter.setFont(f_title)
        painter.drawText(QRectF(0, 2, w, 16), Qt.AlignmentFlag.AlignCenter, self.label)

        # Draw dashed background circle
        painter.setPen(QPen(QColor("#2d2d30"), 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(QPointF(cx, cy), R, R)

        speed_clamped = max(-100.0, min(100.0, self.value))
        span_deg = (abs(speed_clamped) / 100.0) * 270.0  # Max span 270 degrees to keep it open
        is_cw = speed_clamped >= 0
        start_angle = 90.0

        # Draw active arc, but shorten it slightly to let it connect to the base of the arrowhead
        arrow_size = 9
        angle_offset = (arrow_size / R) * 57.3 if R > 0 else 12.0
        span_deg_shortened = max(0.0, span_deg - angle_offset)
        span_angle_arc = -span_deg_shortened if is_cw else span_deg_shortened

        # Active arc drawing
        color = QColor("#f0c060") if is_cw else QColor("#c586c0")
        pen_arc = QPen(color, 4)
        pen_arc.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen_arc)
        painter.drawArc(rect, int(start_angle * 16), int(span_angle_arc * 16))

        # Tip coordinates (at the full angle, so it represents the true tip)
        tip_angle = start_angle - span_deg if is_cw else start_angle + span_deg
        tip_rad = math.radians(tip_angle)
        tx = cx + R * math.cos(tip_rad)
        ty = cy - R * math.sin(tip_rad)

        if abs(speed_clamped) > 1.0:
            # Unit tangent vector in direction of rotation at full tip
            if is_cw:
                ux = math.sin(tip_rad)
                uy = math.cos(tip_rad)
            else:
                ux = -math.sin(tip_rad)
                uy = -math.cos(tip_rad)

            phi = math.pi / 6
            # Backwards unit vector
            bx_dir = -ux
            by_dir = -uy
            
            w1_x = tx + arrow_size * (bx_dir * math.cos(phi) - by_dir * math.sin(phi))
            w1_y = ty + arrow_size * (bx_dir * math.sin(phi) + by_dir * math.cos(phi))
            
            w2_x = tx + arrow_size * (bx_dir * math.cos(-phi) - by_dir * math.sin(-phi))
            w2_y = ty + arrow_size * (bx_dir * math.sin(-phi) + by_dir * math.cos(-phi))

            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            poly = QPolygonF([QPointF(tx, ty), QPointF(w1_x, w1_y), QPointF(w2_x, w2_y)])
            painter.drawPolygon(poly)
        
        painter.end()

class DataGridWidget(QWidget):
    def __init__(self, title: str, channels: List[int], parent=None):
        super().__init__(parent)
        self.title = title
        self.channels = channels
        self.val_labels = {}
        
        self.setStyleSheet(
            "background: #1e1e1e; border: 1px solid #2d2d30; border-radius: 4px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title_lbl = QLabel(self.title)
        title_lbl.setStyleSheet(
            "color: #9cdcfe; font-weight: bold; font-size: 9pt; border: none; background: none;"
        )
        layout.addWidget(title_lbl)

        grid_widget = QWidget()
        grid_widget.setStyleSheet("border: none; background: none;")
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        n = len(self.channels)
        cols = 2 if n <= 10 else 3

        for i, chan in enumerate(self.channels):
            r = i // cols
            c = i % cols

            var_name = VARIABLE_NAMES.get(chan, f"Var_{chan:03d}")

            item_widget = QWidget()
            item_widget.setStyleSheet("border: none; background: #252526; border-radius: 2px;")
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(4, 2, 4, 2)

            lbl_name = QLabel(f"{var_name}:")
            lbl_name.setStyleSheet("color: #888; font-size: 8pt; font-family: monospace;")
            
            lbl_val = QLabel("+0.00")
            lbl_val.setStyleSheet("color: #4ec9b0; font-size: 8pt; font-weight: bold; font-family: monospace;")
            
            self.val_labels[chan] = lbl_val

            item_layout.addWidget(lbl_name)
            item_layout.addWidget(lbl_val)
            item_layout.addStretch()

            grid.addWidget(item_widget, r, c)

        layout.addWidget(grid_widget)

    def update_value(self, values: np.ndarray):
        for chan, lbl in self.val_labels.items():
            if chan < len(values):
                val = float(values[chan])
                lbl.setText(f"{val:+.3f}")

# ── ImageOverlayWidget ────────────────────────────────────────────────────────
class ImageOverlayWidget(QWidget):
    def __init__(self, image_idx: int, parent=None) -> None:
        super().__init__(parent)
        self._image_idx = image_idx
        self._pixmap: Optional[QPixmap] = None
        self._overlays: List[TextOverlay] = []
        self._values   = np.zeros(MAX_FLOATS, dtype=np.float32)
        self._style = IMAGE_STYLES.get(image_idx, OverlayStyle.ARROW)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 200)
        self._load_image()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return w

    def sizeHint(self) -> QSize:
        return QSize(400, 400)

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

    def set_overlays(self, overlays: List[TextOverlay]) -> None:
        self._overlays = [o for o in overlays if o.image_idx == self._image_idx]
        self.update()

    def update_values(self, values: np.ndarray) -> None:
        self._values = values
        self.update()

    def paintEvent(self, event) -> None:
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
        f = QFont("Segoe UI", 12)
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

    def _draw_overlays_inline(self, painter: QPainter,
                                ox: float, oy: float,
                                iw: float, ih: float) -> None:
        sep = " → " if self._style == OverlayStyle.ARROW else ": "
        
        scale = iw / 500.0
        f_size = max(5, int(OVERLAY_FONT_SIZE * scale))

        font = QFont("Segoe UI", f_size)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        line_h = fm.height()
        pad_x  = max(2, int(6 * scale))
        pad_y  = max(1, int(3 * scale))

        for ov in self._overlays:
            px = ox + (ov.x_pct / 100.0) * iw
            py = oy + (ov.y_pct / 100.0) * ih

            idx = max(0, min(ov.channel_idx, len(self._values) - 1))
            val = float(self._values[idx]) if len(self._values) > 0 else 0.0
            if self._style == OverlayStyle.COLON:
                if val > self._values[Schwelle_ID]: 
                    text = f"⭕"
                    ov.color = "#c90505"
                else :
                    text = f"-"
                    ov.color = "#19f3ec"
            else:
                text = f"{ov.label}{sep}{val:+.1f}"

            box_w = fm.horizontalAdvance(text) + pad_x * 2 + 4
            box_h = line_h + pad_y * 2

            # Schatten
            painter.fillRect(
                QRectF(px + 2, py + 2, box_w, box_h), QColor(0, 0, 0, 80)
            )
            # Hintergrund
            painter.fillRect(
                QRectF(px, py, box_w, box_h), QColor(10, 10, 15, 215)
            )
            # Akzentbalken links
            painter.fillRect(QRectF(px, py, max(1, int(2 * scale)), box_h), QColor(ov.color))
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

    def _draw_overlays_two_line(self, painter: QPainter,
                                 ox: float, oy: float,
                                 iw: float, ih: float) -> None:
        scale = iw / 500.0
        f_size_name = max(5, int(OVERLAY_FONT_SIZE * scale))
        f_size_val  = max(6, int(OVERLAY_FONT_SIZE_VAL * scale))

        name_font = QFont("Segoe UI", f_size_name)
        name_font.setWeight(QFont.Weight.Medium)
        val_font  = QFont("Segoe UI", f_size_val)
        val_font.setWeight(QFont.Weight.Bold)

        nm_fm = QFontMetrics(name_font)
        vl_fm = QFontMetrics(val_font)

        pad_x = max(4, int(8 * scale))
        pad_y = max(2, int(6 * scale))

        for ov in self._overlays:
            px = ox + (ov.x_pct / 100.0) * iw
            py = oy + (ov.y_pct / 100.0) * ih

            idx   = max(0, min(ov.channel_idx, len(self._values) - 1))
            val   = float(self._values[idx]) if len(self._values) > 0 else 0.0
            s_val = f"{val:+.3f}"

            w_name = nm_fm.horizontalAdvance(ov.label)
            w_val  = vl_fm.horizontalAdvance(s_val)
            box_w  = max(w_name, w_val) + pad_x * 2
            lh_n   = nm_fm.height()
            lh_v   = vl_fm.height()
            box_h  = lh_n + lh_v + pad_y * 2

            painter.fillRect(QRectF(px + 2, py + 2, box_w, box_h), QColor(0, 0, 0, 80))
            painter.fillRect(QRectF(px, py, box_w, box_h), QColor(10, 10, 15, 215))
            painter.fillRect(QRectF(px, py, max(1, int(3 * scale)), box_h), QColor(ov.color))
            painter.setPen(QPen(QColor(ov.color).darker(140), 0.8))
            painter.drawRect(QRectF(px, py, box_w, box_h))

            name_col = QColor(ov.color).lighter(130)
            name_col.setAlpha(185)
            painter.setPen(name_col)
            painter.setFont(name_font)
            painter.drawText(
                QRectF(px + pad_x, py + pad_y / 2 + 1, box_w - pad_x, lh_n),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                ov.label,
            )
            painter.setPen(QColor(ov.color))
            painter.setFont(val_font)
            painter.drawText(
                QRectF(px + pad_x, py + pad_y / 2 + lh_n + 1, box_w - pad_x, lh_v),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                s_val,
            )

# ── OverlayConfigTable ────────────────────────────────────────────────────────
COL_LABEL = 0
COL_CHAN  = 1
COL_X     = 2
COL_Y     = 3
COL_COLOR = 4
N_COLS    = 5
HEADERS   = ["Label", "Kanal", "X (%)", "Y (%)", "Farbe"]

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
        self._image_idx = 1
        self._callback: Optional[Callable] = None
        self._building = False
        self._setup_ui()

    def set_callback(self, cb: Callable) -> None:
        self._callback = cb

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

        self._lbl_saved = QLabel("")
        self._lbl_saved.setStyleSheet("color: #4ec9b0; font-size: 8pt;")
        btn_row.addWidget(self._lbl_saved)
        layout.addLayout(btn_row)

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

    def _sync_from_table(self) -> None:
        if self._building:
            return
        overlays: List[TextOverlay] = []
        for row in range(self._table.rowCount()):
            lbl_item = self._table.item(row, COL_LABEL)
            s_chan   = self._table.cellWidget(row, COL_CHAN)
            s_x      = self._table.cellWidget(row, COL_X)
            s_y      = self._table.cellWidget(row, COL_Y)
            col_btn  = self._table.cellWidget(row, COL_COLOR)

            if not all([lbl_item, s_chan, s_x, s_y, col_btn]):
                continue
            overlays.append(TextOverlay(
                image_idx   = self._image_idx,
                label       = lbl_item.text(),
                channel_idx = s_chan.value(),
                x_pct       = s_x.value(),
                y_pct       = s_y.value(),
                color       = col_btn.color,
            ))

        self._overlays = overlays
        self._lbl_saved.setText("● gespeichert")
        QTimer.singleShot(2500, lambda: self._lbl_saved.setText(""))

        if self._callback:
            self._callback(overlays)

    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        if not self._building:
            self._sync_from_table()

    def _add_row(self) -> None:
        color = _PALETTE[len(self._overlays) % len(_PALETTE)]
        ov = TextOverlay(self._image_idx, "Neu", 0, 5.0, 5.0, color)
        self._overlays.append(ov)
        self._append_row_widget(ov)
        if self._callback:
            self._callback(self._overlays)

    def _del_row(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedItems()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self._sync_from_table()

    def get_overlays(self) -> List[TextOverlay]:
        return list(self._overlays)

# ── SystemVisualsWidget ───────────────────────────────────────────────────────
class SystemVisualsWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values = np.zeros(MAX_FLOATS, dtype=np.float32)
        self._graphic_widgets = []
        self._config = load_config()
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Top Bar ───────────────────────────────────────────────────────────
        top_bar = QWidget()
        top_bar.setStyleSheet("background: #1e1e1e; border-radius: 4px;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 1, 8, 1)
        top_layout.setSpacing(5)

        lbl_group = QLabel("Gruppe:")
        lbl_group.setStyleSheet("font-weight: bold; color: #9cdcfe; font-size: 10pt;")
        top_layout.addWidget(lbl_group)

        self._group_combo = QComboBox()
        self._group_combo.setStyleSheet(
            "QComboBox { background: #2d2d30; color: #d4d4d4; border: 1px solid #444;"
            " border-radius: 3px; padding: 4px 8px; font-weight: bold; min-width: 180px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #1e1e1e; selection-background-color: #007acc; }"
        )
        self._populate_group_combo()
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        top_layout.addWidget(self._group_combo)

        # Reload button
        btn_reload = QPushButton("↺ Konfig neu laden")
        btn_reload.setStyleSheet(
            "QPushButton { background: #2d2d30; color: #d4d4d4; border: 1px solid #444;"
            " border-radius: 3px; padding: 4px 10px; font-weight: bold; }"
            "QPushButton:hover { background: #3e3e42; color: #ffffff; }"
        )
        btn_reload.clicked.connect(self._reload_config)
        top_layout.addWidget(btn_reload)

        top_layout.addStretch()

        # Collapse Button
        self._btn_toggle_config = QPushButton("▶  Konfiguration einklappen")
        self._btn_toggle_config.setStyleSheet(
            "QPushButton { background: #264f78; color: white; border: none;"
            " border-radius: 3px; padding: 5px 12px; font-weight: bold; }"
            "QPushButton:hover { background: #3278a8; }"
        )
        self._btn_toggle_config.clicked.connect(self._toggle_config_panel)
        top_layout.addWidget(self._btn_toggle_config)

        root.addWidget(top_bar)

        # ── Splitter ──────────────────────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(7)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #007acc; }"
        )

        # ── Left Side: Main group display area ────────────────────────────────
        self._main_display = QWidget()
        self._main_display.setStyleSheet("background: #141414;")
        main_layout = QHBoxLayout(self._main_display)
        main_layout.setContentsMargins(6, 2, 6, 2)
        main_layout.setSpacing(10)

        # 1:1 Image Overlay Widget
        self._img_frame = QFrame()
        self._img_frame.setStyleSheet(
            "QFrame { border: 1px solid #2d2d30; border-radius: 6px; background: #1a1a1a; }"
        )
        self._img_frame.setMaximumWidth(750)
        self._img_frame.setMaximumHeight(750)
        img_frame_layout = QVBoxLayout(self._img_frame)
        img_frame_layout.setContentsMargins(4, 4, 4, 4)
        img_frame_layout.setSpacing(4)

        self._img_title_bar = QWidget()
        self._img_title_bar.setFixedHeight(24)
        self._img_title_bar.setStyleSheet("background: #252526; border-radius: 3px; border: none;")
        tb_layout = QHBoxLayout(self._img_title_bar)
        tb_layout.setContentsMargins(8, 0, 8, 0)
        
        dot = QLabel("●")
        dot.setStyleSheet("color: #007acc; font-size: 9pt; border: none;")
        self._lbl_img_title = QLabel("Systemansicht")
        self._lbl_img_title.setStyleSheet("color: #9cdcfe; font-size: 8pt; font-weight: bold; border: none;")
        tb_layout.addWidget(dot)
        tb_layout.addWidget(self._lbl_img_title)
        tb_layout.addStretch()

        btn_img_reload = QPushButton("↺ Bild neu laden")
        btn_img_reload.setStyleSheet(
            "QPushButton { background: none; color: #888; border: none; font-size: 8pt; }"
            "QPushButton:hover { color: #9cdcfe; }"
        )
        btn_img_reload.clicked.connect(self._reload_active_image)
        tb_layout.addWidget(btn_img_reload)
        img_frame_layout.addWidget(self._img_title_bar)

        self._img_widget = ImageOverlayWidget(1)
        img_frame_layout.addWidget(self._img_widget, stretch=1)
        main_layout.addWidget(self._img_frame)

        # Graphics Panel
        self._graphics_scroll = QScrollArea()
        self._graphics_scroll.setWidgetResizable(True)
        self._graphics_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._graphics_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._graphics_scroll.setStyleSheet(
            "QScrollArea { background: #141414; border: none; }"
            "QScrollBar:vertical { width: 10px; background: #1e1e1e; }"
            "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 4px; min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: #555; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._graphics_container = QWidget()
        self._graphics_container.setStyleSheet("background: #141414;")
        self._graphics_layout = QGridLayout(self._graphics_container)
        self._graphics_layout.setContentsMargins(6, 6, 6, 6)
        self._graphics_layout.setSpacing(10)
        self._graphics_scroll.setWidget(self._graphics_container)
        main_layout.addWidget(self._graphics_scroll, stretch=1)

        self._splitter.addWidget(self._main_display)

        # ── Right Side: Collapsible Config Panel ──────────────────────────────
        self._right_panel = QWidget()
        self._right_panel.setStyleSheet("background: #1e1e1e;")
        self._right_panel.setMinimumWidth(400)
        self._right_panel.setMaximumWidth(650)
        rp_layout = QVBoxLayout(self._right_panel)
        rp_layout.setContentsMargins(0, 0, 0, 0)

        self._config_table = OverlayConfigTable([])
        self._config_table.set_callback(self._on_overlays_changed)
        rp_layout.addWidget(self._config_table)

        self._splitter.addWidget(self._right_panel)
        
        self._splitter.setSizes([750, 450])
        root.addWidget(self._splitter)

        self._load_active_group()

    def _populate_group_combo(self) -> None:
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        for g in self._config.get("groups", []):
            self._group_combo.addItem(g.get("name", "Unbekannte Gruppe"))
        self._group_combo.blockSignals(False)

    def _load_active_group(self) -> None:
        idx = self._group_combo.currentIndex()
        groups = self._config.get("groups", [])
        if idx < 0 or idx >= len(groups):
            return

        group = groups[idx]
        image_idx = int(group.get("image_idx", 1))

        self._img_widget._image_idx = image_idx
        self._img_widget._style = IMAGE_STYLES.get(image_idx, OverlayStyle.ARROW)
        self._img_widget.reload_image()
        self._lbl_img_title.setText(f"Bild {image_idx}  —  {_BILD_DIR / f'Bild{image_idx}.png'}")

        overlays = []
        for ov_dict in group.get("overlays", []):
            overlays.append(TextOverlay(
                image_idx   = image_idx,
                label       = str(ov_dict.get("label", "Label")),
                channel_idx = int(ov_dict.get("channel_idx", 0)),
                x_pct       = float(ov_dict.get("x_pct", 5.0)),
                y_pct       = float(ov_dict.get("y_pct", 5.0)),
                color       = str(ov_dict.get("color", "#4ec9b0")),
            ))
        
        self._img_widget.set_overlays(overlays)

        self._config_table._image_idx = image_idx
        self._config_table._overlays = overlays
        self._config_table._populate()

        self._build_graphics_widgets(group.get("graphics", []))
        self.update_data(self._values)

    def _build_graphics_widgets(self, graphics_config: list) -> None:
        for w in self._graphic_widgets:
            self._graphics_layout.removeWidget(w)
            w.deleteLater()
        self._graphic_widgets.clear()

        row = 0
        col = 0
        cols_limit = 2

        for g_cfg in graphics_config:
            g_type = g_cfg.get("type", "").lower()
            label = g_cfg.get("label", "")
            
            channels = []
            if "channels" in g_cfg:
                channels = parse_channels(g_cfg["channels"])
            elif "channel" in g_cfg:
                channels = parse_channels(g_cfg["channel"])
            
            if g_type == "gauge":
                min_val = float(g_cfg.get("min", -1.0))
                max_val = float(g_cfg.get("max", 1.0))
                for chan in channels:
                    lbl = label if len(channels) == 1 else f"{label} ({VARIABLE_NAMES.get(chan, f'Var_{chan}')})"
                    if not lbl:
                        lbl = VARIABLE_NAMES.get(chan, f"Var_{chan}")
                    w = GaugeWidget(lbl, chan, min_val, max_val)
                    self._graphics_layout.addWidget(w, row, col)
                    row, col = self._increment_grid(row, col, cols_limit)
                    self._graphic_widgets.append(w)
                    
            elif g_type == "rotation":
                for chan in channels:
                    lbl = label if len(channels) == 1 else f"{label} ({VARIABLE_NAMES.get(chan, f'Var_{chan}')})"
                    if not lbl:
                        lbl = VARIABLE_NAMES.get(chan, f"Var_{chan}")
                    w = RotationWidget(lbl, chan)
                    self._graphics_layout.addWidget(w, row, col)
                    row, col = self._increment_grid(row, col, cols_limit)
                    self._graphic_widgets.append(w)
                    
            elif g_type == "vector":
                channel_x = int(g_cfg.get("channel_x", -1))
                channel_y = int(g_cfg.get("channel_y", -1))
                channel_angle = int(g_cfg.get("channel_angle", -1))
                channel_speed = int(g_cfg.get("channel_speed", -1))
                scale = float(g_cfg.get("scale", 1.0))
                max_val = float(g_cfg.get("max_val", 10.0))
                
                lbl = label
                if not lbl:
                    if channel_x >= 0 and channel_y >= 0:
                        lbl = f"Vektor {VARIABLE_NAMES.get(channel_x, f'Var_{channel_x}')}/{VARIABLE_NAMES.get(channel_y, f'Var_{channel_y}')}"
                    else:
                        lbl = "Vektor"
                w = VectorWidget(lbl, channel_x, channel_y, channel_angle, channel_speed, scale, max_val)
                self._graphics_layout.addWidget(w, row, col)
                row, col = self._increment_grid(row, col, cols_limit)
                self._graphic_widgets.append(w)
                
            elif g_type == "table":
                title = g_cfg.get("title", label if label else "Datentabelle")
                w = DataGridWidget(title, channels)
                if col > 0:
                    col = 0
                    row += 1
                self._graphics_layout.addWidget(w, row, 0, 1, cols_limit)
                row += 1
                self._graphic_widgets.append(w)

        # Add spacer to stretch
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._graphics_layout.addWidget(spacer, row, 0, 1, cols_limit)
        self._graphics_layout.setRowStretch(row, 1)

    def _increment_grid(self, row: int, col: int, limit: int) -> tuple[int, int]:
        col += 1
        if col >= limit:
            col = 0
            row += 1
        return row, col

    def _on_overlays_changed(self, overlays: List[TextOverlay]) -> None:
        self._img_widget.set_overlays(overlays)

        idx = self._group_combo.currentIndex()
        groups = self._config.get("groups", [])
        if idx < 0 or idx >= len(groups):
            return

        group = groups[idx]
        
        ov_dicts = []
        for ov in overlays:
            ov_dicts.append({
                "label": ov.label,
                "channel_idx": ov.channel_idx,
                "x_pct": ov.x_pct,
                "y_pct": ov.y_pct,
                "color": ov.color
            })
        group["overlays"] = ov_dicts
        save_config(self._config)

    def _reload_config(self) -> None:
        self._config = load_config()
        self._populate_group_combo()
        self._load_active_group()

    def _reload_active_image(self) -> None:
        self._img_widget.reload_image()

    def _on_group_changed(self, index: int) -> None:
        if index >= 0:
            self._load_active_group()

    def _toggle_config_panel(self) -> None:
        visible = self._right_panel.isVisible()
        self._right_panel.setVisible(not visible)
        if visible:
            self._btn_toggle_config.setText("◀  Konfiguration ausklappen")
        else:
            self._btn_toggle_config.setText("▶  Konfiguration einklappen")

    def update_data(self, values: np.ndarray) -> None:
        self._values = values
        self._img_widget.update_values(values)
        for w in self._graphic_widgets:
            if hasattr(w, "update_value"):
                w.update_value(values)
