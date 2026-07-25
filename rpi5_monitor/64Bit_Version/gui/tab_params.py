"""
tab_params.py — Parameter-Editor-Tab
=======================================
Sendet zwei unabhängige, zyklische Downlink-Streams an den aktuell in der
GUI gewählten Node (nicht an beide gleichzeitig — siehe Param-Feature-Plan
v2, Architekturentscheidung "nur an aktiven Node"):

  Slow-Kanal:  50 Floats + 50 Bools, alle 500 ms  (UDP_PARAM_SLOW_PORT_NODE{1,2})
  Fast-Kanal:  5 Floats,             alle 10 ms   (UDP_PARAM_FAST_PORT_NODE{1,2})

Fire-and-Forget: es gibt kein ACK vom Teensy, die GUI zeigt daher nur den
eigenen Sendezustand an (Paketzähler), nicht ob der Teensy tatsächlich
empfängt.

Widget-Zuordnung kommt aus param_config.json (siehe param_io.py), Werte
werden aus param_defaults.h vorbelegt, falls vorhanden (siehe Save-Button).
"""
from __future__ import annotations

import math
import socket
import struct
import logging
from typing import Callable

import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QLineEdit, QGroupBox, QSizePolicy, QDoubleSpinBox,
    QScrollArea, QCheckBox, QFrame, QComboBox, QStackedWidget,
)
from PyQt6.QtGui import QPainter, QPen, QColor, QDoubleValidator, QFont
from PyQt6.QtCore import Qt, QTimer, QPointF

from config import (
    PARAM_SLOW_MAGIC, PARAM_FAST_MAGIC,
    UDP_PARAM_SLOW_PORT_NODE1, UDP_PARAM_SLOW_PORT_NODE2,
    UDP_PARAM_FAST_PORT_NODE1, UDP_PARAM_FAST_PORT_NODE2,
    PARAM_SLOW_SEND_INTERVAL_MS, PARAM_FAST_SEND_INTERVAL_MS,
    PARAM_SLOW_SEND_HZ, PARAM_FAST_SEND_HZ,
    PARAM_CONFIG_PATH, PARAM_DEFAULTS_H_PATH,
)
from param_io import (
    ParamConfig, ParamEntry, JoystickEntry,
    load_param_config, write_param_defaults_h, read_param_defaults_h,
)

log = logging.getLogger("tab_params")


# ══════════════════════════════════════════════════════════════════════════
#  ParamStore — zentraler Zustand aller 50+50+5 Werte
# ══════════════════════════════════════════════════════════════════════════

class ParamStore:
    """Hält den aktuellen Soll-Zustand aller Parameter im GUI-Thread und
    packt sie bei Bedarf in die beiden Wire-Formate (Slow/Fast)."""

    def __init__(self, config: ParamConfig) -> None:
        self.floats = np.array([e.default for e in config.floats], dtype=np.float32)
        self.bools = np.array([e.default for e in config.bools], dtype=bool)
        self.fast_floats = np.array([e.default for e in config.fast_floats], dtype=np.float32)
        self._slow_seq = 0
        self._fast_seq = 0

    # ── Setter (von den Widgets aufgerufen) ─────────────────────────────────
    def set_float(self, i: int, v: float) -> None:
        self.floats[i] = v

    def set_bool(self, i: int, v: bool) -> None:
        self.bools[i] = v

    def set_fast_float(self, i: int, v: float) -> None:
        self.fast_floats[i] = v

    # ── Packen fürs Senden ───────────────────────────────────────────────────
    def pack_slow(self) -> bytes:
        self._slow_seq = (self._slow_seq + 1) & 0xFFFFFFFF
        header = struct.pack("<II", PARAM_SLOW_MAGIC, self._slow_seq)
        return (
            header
            + self.floats.astype("<f4").tobytes()
            + bytes(1 if b else 0 for b in self.bools)
        )

    def pack_fast(self) -> bytes:
        self._fast_seq = (self._fast_seq + 1) & 0xFFFFFFFF
        header = struct.pack("<II", PARAM_FAST_MAGIC, self._fast_seq)
        return header + self.fast_floats.astype("<f4").tobytes()

    # ── Defaults aus param_defaults.h überlagern ─────────────────────────────
    def apply_defaults_h(self, defaults: dict) -> bool:
        """Überschreibt aktuelle Werte mit denen aus param_defaults.h, nur
        wenn die Länge exakt passt (Robustheit gegen alte/kaputte Dateien).
        Gibt True zurück, wenn mindestens etwas übernommen wurde."""
        applied = False
        if defaults.get("floats") and len(defaults["floats"]) == len(self.floats):
            self.floats[:] = defaults["floats"]
            applied = True
        if defaults.get("bools") and len(defaults["bools"]) == len(self.bools):
            self.bools[:] = defaults["bools"]
            applied = True
        ff = defaults.get("fast_floats")
        if ff and len(ff) == len(self.fast_floats):
            self.fast_floats[:] = ff
            applied = True
        return applied


# ══════════════════════════════════════════════════════════════════════════
#  2-Achsen-Analog-Joystick (Custom-Widget)
# ══════════════════════════════════════════════════════════════════════════

class JoystickWidget(QWidget):
    """
    Digitaler 2-Achsen-Joystick (Maus-/Touch-gesteuert).
    Gibt normierte Werte im konfigurierten Bereich zurück (Standard ±100).
    Bewusst groß dimensioniert (min. 200x200 px) für gute Bedienbarkeit
    auf einem Touchscreen.
    """

    def __init__(
        self,
        x_range: tuple[float, float] = (-100.0, 100.0),
        y_range: tuple[float, float] = (-100.0, 100.0),
        return_to_center: bool = True,
        size_px: int = 200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._x_range = x_range
        self._y_range = y_range
        self._return_to_center = return_to_center
        self._knob = QPointF(0.0, 0.0)   # normiert -1..1, unabhängig vom Zielbereich
        self._dragging = False
        self.setMinimumSize(size_px, size_px)
        self.on_change: Callable[[float, float], None] | None = None

    # ── Geometrie-Helfer ──────────────────────────────────────────────────
    def _center_radius(self) -> tuple[QPointF, float]:
        r = min(self.width(), self.height()) / 2 - 14
        return QPointF(self.width() / 2, self.height() / 2), max(r, 1.0)

    def _pos_to_norm(self, pos: QPointF) -> QPointF:
        center, r = self._center_radius()
        dx = (pos.x() - center.x()) / r
        dy = (pos.y() - center.y()) / r
        mag = math.hypot(dx, dy)
        if mag > 1.0:
            dx, dy = dx / mag, dy / mag
        return QPointF(dx, dy)

    # ── Maus-/Touch-Events ────────────────────────────────────────────────
    def mousePressEvent(self, ev) -> None:
        self._dragging = True
        self._update_from(ev.position())

    def mouseMoveEvent(self, ev) -> None:
        if self._dragging:
            self._update_from(ev.position())

    def mouseReleaseEvent(self, ev) -> None:
        self._dragging = False
        if self._return_to_center:
            self._knob = QPointF(0.0, 0.0)
            self._emit()
            self.update()

    def _update_from(self, pos: QPointF) -> None:
        self._knob = self._pos_to_norm(pos)
        self._emit()
        self.update()

    def _emit(self) -> None:
        if self.on_change is None:
            return
        x = self._knob.x() * (self._x_range[1] if self._knob.x() >= 0 else -self._x_range[0])
        # Bildschirm-Y zeigt nach unten -> Vorzeichen umdrehen, damit "nach
        # oben ziehen" intuitiv einem positiven Y entspricht (wie bei
        # Fahr-Joysticks ueblich)
        y = -self._knob.y() * (self._y_range[1] if -self._knob.y() >= 0 else -self._y_range[0])
        self.on_change(x, y)

    # ── Zeichnen ──────────────────────────────────────────────────────────
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center, r = self._center_radius()

        p.setPen(QPen(QColor("#555"), 2))
        p.setBrush(QColor("#2a2a2a"))
        p.drawEllipse(center, r, r)

        p.setPen(QPen(QColor("#444"), 1))
        p.drawLine(QPointF(center.x() - r, center.y()), QPointF(center.x() + r, center.y()))
        p.drawLine(QPointF(center.x(), center.y() - r), QPointF(center.x(), center.y() + r))

        knob_pos = QPointF(center.x() + self._knob.x() * r, center.y() + self._knob.y() * r)
        p.setPen(QPen(QColor("#2ecc71"), 2))
        p.setBrush(QColor("#2ecc71") if self._dragging else QColor("#3a9c63"))
        p.drawEllipse(knob_pos, 16, 16)   # grosser Griff-Punkt, gut mit dem Finger zu treffen


# ══════════════════════════════════════════════════════════════════════════
#  Widget-Factory: Slider, Toggle/Switch, Button (momentary), Text, Number
# ══════════════════════════════════════════════════════════════════════════

_SWITCH_STYLE = """
QPushButton {
    min-width: 140px; min-height: 56px;
    font-size: 13pt; font-weight: 600;
    border-radius: 10px; border: 2px solid #444;
    background: #3a3a3a; color: #ccc;
}
QPushButton:checked {
    background: #2ecc71; color: #10331d; border-color: #2ecc71;
}
QPushButton:!checked:hover { background: #4a4a4a; }
"""

_MOMENTARY_STYLE = """
QPushButton {
    min-width: 140px; min-height: 56px;
    font-size: 13pt; font-weight: 700;
    border-radius: 10px; border: 2px solid #7a2e2e;
    background: #a33; color: white;
}
QPushButton:pressed { background: #ff4444; border-color: #ff4444; }
QPushButton:checked  { background: #2ecc71; border-color: #2ecc71; }
"""


def make_slider_widget(entry: ParamEntry, on_change: Callable[[float], None]) -> QWidget:
    SCALE = 100   # 1 Nachkommastelle Aufloesung (QSlider arbeitet nur mit int)

    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(4, 2, 4, 2)

    name_lbl = QLabel(entry.name)
    name_lbl.setMinimumWidth(160)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setMinimumHeight(32)
    slider.setMinimum(int(entry.min * SCALE))
    slider.setMaximum(int(entry.max * SCALE))
    slider.setValue(int(entry.default * SCALE))

    value_lbl = QLabel(f"{entry.default:+.2f}")
    value_lbl.setMinimumWidth(86)
    value_lbl.setStyleSheet("font-family: monospace;")

    def _on_changed(raw_int: int) -> None:
        val = raw_int / SCALE
        value_lbl.setText(f"{val:+.2f}")
        on_change(val)

    slider.valueChanged.connect(_on_changed)

    layout.addWidget(name_lbl)
    layout.addWidget(slider, stretch=1)
    layout.addWidget(value_lbl)
    return box


def make_number_widget(entry: ParamEntry, on_change: Callable[[float], None]) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(4, 2, 4, 2)

    name_lbl = QLabel(entry.name)
    name_lbl.setMinimumWidth(160)

    spin = QDoubleSpinBox()
    spin.setMinimumHeight(32)
    spin.setRange(entry.min, entry.max)
    spin.setSingleStep(entry.step)
    spin.setDecimals(3)
    spin.setValue(entry.default)
    spin.valueChanged.connect(on_change)

    layout.addWidget(name_lbl)
    layout.addWidget(spin, stretch=1)
    return box


def make_toggle_widget(entry: ParamEntry, on_change: Callable[[bool], None]) -> QWidget:
    btn = QPushButton()
    btn.setCheckable(True)
    btn.setChecked(bool(entry.default))
    btn.setStyleSheet(_SWITCH_STYLE)
    btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _refresh_text(checked: bool) -> None:
        btn.setText(f"{entry.name}\n{'● AN' if checked else '○ AUS'}")

    btn.toggled.connect(lambda checked: (_refresh_text(checked), on_change(checked)))
    _refresh_text(bool(entry.default))
    return btn


def make_button_widget(entry: ParamEntry, on_change: Callable[[bool], None]) -> QWidget:
    btn = QPushButton(entry.name)
    btn.setStyleSheet(_MOMENTARY_STYLE)
    btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    if entry.momentary:
        # Bool ist True NUR solange die Taste gedrueckt gehalten wird
        btn.pressed.connect(lambda: on_change(True))
        btn.released.connect(lambda: on_change(False))
    else:
        # Klick schaltet um, bleibt bis zum naechsten Klick — als Button gerendert
        btn.setCheckable(True)
        btn.setChecked(bool(entry.default))
        btn.toggled.connect(on_change)

    return btn


def make_text_widget(entry: ParamEntry, on_change: Callable[[float], None]) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(4, 2, 4, 2)

    name_lbl = QLabel(entry.name)
    name_lbl.setMinimumWidth(160)

    edit = QLineEdit(f"{entry.default:.3f}")
    edit.setMinimumHeight(32)
    edit.setMaximumWidth(100)
    validator = QDoubleValidator(entry.min, entry.max, 4)
    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    edit.setValidator(validator)

    def _commit() -> None:
        try:
            val = float(edit.text().replace(",", "."))
        except ValueError:
            edit.setText(f"{entry.default:.3f}")
            return
        val = max(entry.min, min(entry.max, val))
        edit.setText(f"{val:.3f}")
        on_change(val)

    edit.editingFinished.connect(_commit)

    layout.addWidget(name_lbl)
    layout.addWidget(edit)
    return box


def make_joystick_widget(
    js: JoystickEntry,
    on_change_x: Callable[[float], None],
    on_change_y: Callable[[float], None],
) -> QWidget:
    box = QGroupBox(js.name)
    layout = QVBoxLayout(box)
    jw = JoystickWidget(
        x_range=js.x_range, y_range=js.y_range,
        return_to_center=js.return_to_center, size_px=200,
    )
    jw.on_change = lambda x, y: (on_change_x(x), on_change_y(y))
    layout.addWidget(jw, alignment=Qt.AlignmentFlag.AlignCenter)
    return box


_WIDGET_FACTORIES: dict[str, Callable] = {
    "slider": make_slider_widget,
    "number": make_number_widget,
    "toggle": make_toggle_widget,
    "button": make_button_widget,
    "text":   make_text_widget,
}


# ── Helfer: abschnitt-Trennlinie mit farbiger Markierung ─────────────────

def _section_header(title: str, color: str = "#9cdcfe") -> QWidget:
    """Gibt einen stilisierten Abschnitts-Header zurück, der an die
    farbigen Gruppen-Überschriften im Systemansicht-Tab angelehnt ist."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 10, 0, 4)
    row.setSpacing(8)

    accent = QFrame()
    accent.setFixedSize(4, 22)
    accent.setStyleSheet(f"background: {color}; border-radius: 2px;")

    lbl = QLabel(title)
    font = QFont()
    font.setBold(True)
    font.setPointSize(10)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color};")

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet("color: #3a3a3d;")

    row.addWidget(accent)
    row.addWidget(lbl)
    row.addWidget(line, stretch=1)
    return w


def _build_flat_entries(
    entries: list[ParamEntry],
    joystick_indices: set[int],
    on_change_float: Callable[[int, float], None] | None,
    on_change_bool: Callable[[int, bool], None] | None,
    layout: QVBoxLayout,
) -> None:
    """Rendert alle entries (ohne Joystick-Indizes) als flache Widget-Liste."""
    for e in entries:
        if e.index in joystick_indices:
            continue
        is_bool = e.widget in ("toggle", "button")
        factory = _WIDGET_FACTORIES[e.widget]
        if is_bool:
            cb = (lambda v, i=e.index: on_change_bool(i, v))  # type: ignore[arg-type]
        else:
            cb = (lambda v, i=e.index: on_change_float(i, v))  # type: ignore[arg-type]
        layout.addWidget(factory(e, cb))


def _build_fast_section(
    entries: list[ParamEntry],
    joysticks: list[JoystickEntry],
    on_change_float: Callable[[int, float], None],
) -> QWidget:
    """Baut den ⚡ Fast-Param-Bereich.

    Layout: LINKS die Schieberegler/Zahlen-/Texteingaben (alle
    Nicht-Joystick-Einträge), RECHTS der/die Joystick(s) — nebeneinander
    statt übereinander, analog zur Bild+Grafik-Aufteilung im
    Systemansicht-Tab (tab_visuals.py)."""
    joystick_indices = {
        idx for js in joysticks if js.source == "fast"
        for idx in (js.x_index, js.y_index)
    }

    container = QWidget()
    h_layout = QHBoxLayout(container)
    h_layout.setContentsMargins(0, 0, 0, 0)
    h_layout.setSpacing(12)

    # ── Links: Slider / Zahlen / Text / Schalter ────────────────────────
    left = QWidget()
    left_layout = QVBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(6)
    _build_flat_entries(entries, joystick_indices, on_change_float, None, left_layout)
    left_layout.addStretch(1)

    # ── Rechts: Joystick(s) ──────────────────────────────────────────────
    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(6)
    for js in joysticks:
        if js.source != "fast":
            continue
        right_layout.addWidget(make_joystick_widget(
            js,
            on_change_x=lambda v, i=js.x_index: on_change_float(i, v),
            on_change_y=lambda v, i=js.y_index: on_change_float(i, v),
        ))
    right_layout.addStretch(1)

    h_layout.addWidget(left, stretch=2)
    h_layout.addWidget(right, stretch=1)
    return container


def _wrap_group_frame(inner: QWidget, border_color: str, bg_color: str) -> QWidget:
    """Einheitlicher Rahmen für eine Gruppen-Seite (gleiche Optik wie zuvor
    die Fast-/Slow-Blöcke)."""
    frame = QGroupBox()
    frame.setStyleSheet(
        f"QGroupBox {{ border: 1px solid {border_color}; border-radius: 6px; "
        f"background: {bg_color}; padding: 6px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.addWidget(inner)
    return frame


def _build_group_pages(
    config: "ParamConfig",
    on_change_fast_float: Callable[[int, float], None],
    on_change_slow_float: Callable[[int, float], None],
    on_change_bool: Callable[[int, bool], None],
) -> list[tuple[str, QWidget]]:
    """Baut EINE Seite pro auswählbarer Gruppe (analog zum Gruppen-Dropdown
    im Systemansicht-Tab, tab_visuals.py) statt alle Bereiche gleichzeitig
    untereinander anzuzeigen.

    Reihenfolge der Seiten:
      1. ⚡ Fast Params        (links Slider/Text, rechts Joystick)
      2. 🎮 Joysticks (Slow)   (falls vorhanden)
      3. 🐢 <Gruppenname>      (je 'group'-Feld aus param_config.json,
                                 Floats + zugehörige Bools zusammen)

    WICHTIG: Fast- und Slow-Floats liegen in getrennten Arrays im
    ParamStore (siehe ParamStore.set_float vs. set_fast_float) — daher
    zwei separate Float-Callbacks, nicht einen gemeinsamen.
    """
    from collections import OrderedDict

    pages: list[tuple[str, QWidget]] = []

    # ── 1) Fast Params ───────────────────────────────────────────────────
    fast_widget = _build_fast_section(config.fast_floats, config.joysticks, on_change_fast_float)
    pages.append((
        "⚡ Fast Params · 100 Hz",
        _wrap_group_frame(fast_widget, "#4a4010", "#1e1c10"),
    ))

    # ── 2) Slow-Joysticks (haben kein group-Feld) ───────────────────────
    slow_joysticks = [js for js in config.joysticks if js.source == "slow"]
    joystick_indices = {
        idx for js in slow_joysticks for idx in (js.x_index, js.y_index)
    }
    if slow_joysticks:
        jbox = QWidget()
        jlayout = QVBoxLayout(jbox)
        jlayout.setSpacing(6)
        for js in slow_joysticks:
            jlayout.addWidget(make_joystick_widget(
                js,
                on_change_x=lambda v, i=js.x_index: on_change_slow_float(i, v),
                on_change_y=lambda v, i=js.y_index: on_change_slow_float(i, v),
            ))
        jlayout.addStretch(1)
        pages.append((
            "🎮 Joysticks · 2 Hz",
            _wrap_group_frame(jbox, "#3a1a40", "#160c1a"),
        ))

    # ── 3) Floats + Bools nach 'group'-Feld zusammenfassen ──────────────
    combined: "OrderedDict[str, dict[str, list[ParamEntry]]]" = OrderedDict()
    for e in config.floats:
        if e.index in joystick_indices:
            continue
        grp = e.group or "Allgemein"
        combined.setdefault(grp, {"floats": [], "bools": []})["floats"].append(e)
    for e in config.bools:
        grp = e.group or "Schalter"
        combined.setdefault(grp, {"floats": [], "bools": []})["bools"].append(e)

    for grp_name, parts in combined.items():
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(6)

        if parts["floats"]:
            f_box = QGroupBox(grp_name)
            f_layout = QVBoxLayout(f_box)
            f_layout.setSpacing(4)
            for e in parts["floats"]:
                factory = _WIDGET_FACTORIES[e.widget]
                cb = (lambda v, i=e.index: on_change_slow_float(i, v))
                f_layout.addWidget(factory(e, cb))
            page_layout.addWidget(f_box)

        if parts["bools"]:
            b_box = QGroupBox(f"{grp_name} — Schalter" if parts["floats"] else grp_name)
            b_layout = QVBoxLayout(b_box)
            b_layout.setSpacing(4)
            for e in parts["bools"]:
                factory = _WIDGET_FACTORIES[e.widget]
                cb = (lambda v, i=e.index: on_change_bool(i, v))
                b_layout.addWidget(factory(e, cb))
            page_layout.addWidget(b_box)

        page_layout.addStretch(1)
        pages.append((
            f"🐢 {grp_name}",
            _wrap_group_frame(page, "#10403a", "#0e1e1c"),
        ))

    return pages


# ══════════════════════════════════════════════════════════════════════════
#  ParamEditorWidget — der eigentliche Tab
# ══════════════════════════════════════════════════════════════════════════

class ParamEditorWidget(QWidget):

    def __init__(
        self,
        get_node_ip: Callable[[int], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """
        get_node_ip: Callable[[int], str] — liefert die AKTUELL bekannte IP
                     des angegebenen Node (dynamisch von main_window.py aus
                     der Telemetrie gelernt). Wird von MainWindow injiziert.
                     Falls None (z. B. bei isoliertem Testen dieses Tabs),
                     wird ersatzweise 127.0.0.1 verwendet.
        """
        super().__init__(parent)
        self._get_node_ip = get_node_ip or (lambda node_id: "127.0.0.1")
        self._active_node = 1
        self._enabled = True

        self._pkt_sent_slow = 0
        self._pkt_sent_fast = 0

        self._config_error: str | None = None
        try:
            self._config = load_param_config(PARAM_CONFIG_PATH)
        except ValueError as exc:
            # Konfiguration ist WIDERSPRÜCHLICH (nicht bloss fehlend) —
            # das darf nicht still verschluckt werden, siehe param_io.py.
            log.error(f"param_config.json ungueltig: {exc}")
            self._config_error = str(exc)
            self._config = ParamConfig(floats=[], bools=[], fast_floats=[], joysticks=[])

        self._store = ParamStore(self._config)

        # Defaults aus param_defaults.h überlagern, falls vorhanden & gültig
        self._defaults_loaded_from_file = False
        if self._config_error is None:
            defaults = read_param_defaults_h(PARAM_DEFAULTS_H_PATH)
            if defaults:
                self._defaults_loaded_from_file = self._store.apply_defaults_h(defaults)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._build_ui()

        if self._config_error is None:
            self._slow_timer = QTimer(self)
            self._slow_timer.setInterval(PARAM_SLOW_SEND_INTERVAL_MS)
            self._slow_timer.timeout.connect(self._send_slow_tick)
            self._slow_timer.start()

            self._fast_timer = QTimer(self)
            self._fast_timer.setInterval(PARAM_FAST_SEND_INTERVAL_MS)
            self._fast_timer.timeout.connect(self._send_fast_tick)
            self._fast_timer.start()

            self._status_timer = QTimer(self)
            self._status_timer.setInterval(500)
            self._status_timer.timeout.connect(self._refresh_status_label)
            self._status_timer.start()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        if self._config_error is not None:
            err_lbl = QLabel(
                "⚠ param_config.json ist ungültig — Parameter-Tab deaktiviert.\n\n"
                f"Fehler: {self._config_error}\n\n"
                "Bitte param_config.json korrigieren und die GUI neu starten."
            )
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet(
                "color: #e74c3c; background: #3a1f1f; padding: 16px; "
                "border-radius: 6px; font-family: monospace;"
            )
            root.addWidget(err_lbl)
            return

        root.addWidget(self._build_toolbar())

        # ── Gruppen-Auswahl (analog zum Dropdown im Systemansicht-Tab) ────
        root.addWidget(self._build_group_selector())

        self._pages_stack = QStackedWidget()
        for _name, page_widget in self._group_pages:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page_widget)
            self._pages_stack.addWidget(scroll)
        root.addWidget(self._pages_stack, stretch=1)

    def _build_group_selector(self) -> QWidget:
        """Leiste mit Gruppen-Dropdown — optisch an tab_visuals.py angelehnt,
        damit stets nur EINE Gruppe (Fast/Joysticks/Slow-Gruppe) sichtbar ist."""
        bar = QWidget()
        bar.setStyleSheet("background: #1e1e1e; border-radius: 4px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        lbl = QLabel("Gruppe:")
        lbl.setStyleSheet("font-weight: bold; color: #9cdcfe; font-size: 10pt;")
        layout.addWidget(lbl)

        self._group_pages = _build_group_pages(
            self._config,
            on_change_fast_float=self._on_fast_float_changed,
            on_change_slow_float=self._on_slow_float_changed,
            on_change_bool=self._on_slow_bool_changed,
        )

        self._group_combo = QComboBox()
        self._group_combo.setStyleSheet(
            "QComboBox { background: #2d2d30; color: #d4d4d4; border: 1px solid #444;"
            " border-radius: 3px; padding: 4px 8px; font-weight: bold; min-width: 220px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #1e1e1e; selection-background-color: #007acc; }"
        )
        for name, _widget in self._group_pages:
            self._group_combo.addItem(name)
        self._group_combo.currentIndexChanged.connect(self._on_group_selected)
        layout.addWidget(self._group_combo, stretch=1)
        return bar

    def _on_group_selected(self, index: int) -> None:
        if hasattr(self, "_pages_stack") and index >= 0:
            self._pages_stack.setCurrentIndex(index)

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        bar.setStyleSheet(
            "QFrame { background: #252527; border-radius: 5px; "
            "border: 1px solid #3a3a3d; }"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)

        self._status_label = QLabel()
        self._status_label.setStyleSheet(
            "font-family: monospace; color: #4ec9b0; "
            "background: transparent; border: none;"
        )
        self._refresh_status_label()
        layout.addWidget(self._status_label, stretch=1)

        self._chk_enabled = QCheckBox("Übertragung aktiv")
        self._chk_enabled.setChecked(True)
        self._chk_enabled.toggled.connect(self._on_enabled_toggled)
        layout.addWidget(self._chk_enabled)

        self._btn_save = QPushButton("💾 Als Default speichern")
        self._btn_save.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._btn_save)

        if self._defaults_loaded_from_file:
            hint = QLabel(f"✓ {PARAM_DEFAULTS_H_PATH.name} geladen")
            hint.setStyleSheet(
                "color: #4ec9b0; font-style: italic; "
                "background: transparent; border: none;"
            )
            layout.addWidget(hint)

        return bar

    # ── Setter-Callbacks (an die Widget-Factory durchgereicht) ──────────────
    def _on_slow_float_changed(self, index: int, value: float) -> None:
        self._store.set_float(index, value)

    def _on_slow_bool_changed(self, index: int, value: bool) -> None:
        self._store.set_bool(index, value)

    def _on_fast_float_changed(self, index: int, value: float) -> None:
        self._store.set_fast_float(index, value)

    # ── Senden ────────────────────────────────────────────────────────────
    def _current_target(self, fast: bool) -> tuple[str, int]:
        ip = self._get_node_ip(self._active_node)
        if fast:
            port = UDP_PARAM_FAST_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_FAST_PORT_NODE2
        else:
            port = UDP_PARAM_SLOW_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_SLOW_PORT_NODE2
        return ip, port

    def _send_slow_tick(self) -> None:
        if not self._enabled:
            return
        ip, port = self._current_target(fast=False)
        try:
            self._sock.sendto(self._store.pack_slow(), (ip, port))
            self._pkt_sent_slow += 1
        except OSError as exc:
            log.warning(f"Slow-Param-Sendefehler: {exc}")

    def _send_fast_tick(self) -> None:
        if not self._enabled:
            return
        ip, port = self._current_target(fast=True)
        try:
            self._sock.sendto(self._store.pack_fast(), (ip, port))
            self._pkt_sent_fast += 1
        except OSError as exc:
            log.warning(f"Fast-Param-Sendefehler: {exc}")

    def _refresh_status_label(self) -> None:
        ip = self._get_node_ip(self._active_node)
        state = "▶" if self._enabled else "⏸"
        self._status_label.setText(
            f"{state} → Node {self._active_node} ({ip}) · "
            f"Slow: {PARAM_SLOW_SEND_HZ:.1f} Hz ({self._pkt_sent_slow} Pkt) · "
            f"Fast: {PARAM_FAST_SEND_HZ:.0f} Hz ({self._pkt_sent_fast} Pkt)"
        )

    # ── Von MainWindow aufgerufen ────────────────────────────────────────
    def set_active_node(self, node_id: int) -> None:
        self._active_node = node_id
        self._refresh_status_label()

    # ── Toolbar-Slots ─────────────────────────────────────────────────────
    def _on_enabled_toggled(self, checked: bool) -> None:
        self._enabled = checked
        self._refresh_status_label()

    def _on_save_clicked(self) -> None:
        try:
            write_param_defaults_h(
                PARAM_DEFAULTS_H_PATH,
                self._store.floats, self._store.bools, self._store.fast_floats,
            )
            self._status_label.setText(f"💾 Gespeichert: {PARAM_DEFAULTS_H_PATH.name}")
            log.info(f"Param-Defaults gespeichert nach {PARAM_DEFAULTS_H_PATH}")
        except OSError as exc:
            log.error(f"Konnte param_defaults.h nicht schreiben: {exc}")
            self._status_label.setText(f"⚠ Speichern fehlgeschlagen: {exc}")