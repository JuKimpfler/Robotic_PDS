"""
bridge/visuals_bridge.py — Tab 3 (Systemansicht)
====================================================
Migrationsplan Abschnitt 4.5: Das bisherige ~1700-Zeilen QPainter-Overlay-
System wird durch deklarative QML-Bindings ersetzt (Image + Repeater +
Anchors, siehe SystemView.qml). Diese Bridge lädt visuals_overlays.json
unverändert (gleiches Format) und reicht sie nur noch aufbereitet durch:

  - je Gruppe: Bildpfad + Liste der Text-Overlays (x_pct/y_pct/label/channel)
  - je Gruppe: Liste der "Grafiken" (gauge/rotation/vector/table), inkl.
    aufgelöster Kanal-Listen (parse_channels) für den table-Typ

Die eigentliche Positionierung/Skalierung übernimmt QML über Bindings an
`Image.paintedWidth/paintedHeight` — das war im Original mehrere Dutzend
Zeilen manueller Resize-Event-Handling-Code (siehe alte tab_visuals.py),
in QML ist es "kostenlos" durch Anchor-Bindings.

Hinweis: Für den ersten Migrationsschritt werden die Bilder direkt per
`file://`-URL referenziert (einfachster Weg). Ein eigener
QQuickImageProvider (Caching, evtl. Vorskalierung fürs RPi5-Display) ist
als spätere Ausbaustufe im Plan vorgesehen (Abschnitt 4.5), aber für die
Funktionsfähigkeit nicht zwingend erforderlich.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot

from bridge.utils import parse_channels

log = logging.getLogger("bridge.visuals")

_BILD_DIR    = Path(__file__).resolve().parent.parent / "bild"
_CONFIG_FILE = Path(__file__).resolve().parent.parent / "visuals_overlays.json"


def _image_url(image_idx: int) -> str:
    path = _BILD_DIR / f"Bild{image_idx}.png"
    return path.resolve().as_uri() if path.exists() else ""


def _load_groups() -> list[dict]:
    if not _CONFIG_FILE.exists():
        log.warning("visuals_overlays.json nicht gefunden — Systemansicht bleibt leer.")
        return []
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("visuals_overlays.json ist kein gültiges JSON: %s", exc)
        return []

    groups: list[dict] = []
    for g in raw.get("groups", []):
        image_idx = g.get("image_idx", 1)
        overlays = [
            {
                "label": o.get("label", ""),
                "channel": o.get("channel_idx", 0),
                "xPct": float(o.get("x_pct", 5.0)),
                "yPct": float(o.get("y_pct", 8.0)),
                "color": o.get("color", "#4ec9b0"),
            }
            for o in g.get("overlays", [])
        ]

        graphics: list[dict] = []
        for gr in g.get("graphics", []):
            gtype = gr.get("type", "")
            entry = {"type": gtype, "label": gr.get("label", gr.get("title", ""))}
            if gtype == "gauge":
                entry.update({
                    "channel": gr.get("channel", 0),
                    "min": float(gr.get("min", 0.0)),
                    "max": float(gr.get("max", 1.0)),
                })
            elif gtype == "rotation":
                entry.update({
                    "channel": gr.get("channel", 0),
                    # Max erwartete Drehrate für die Pfeillängen-Skalierung.
                    # Kein eigener JSON-Key bisher vorgesehen -> optionaler
                    # "max_val", sonst Fallback auf den gleichen Bereich wie
                    # die Motor-Gauges (-5..5), da "Rad FL/FR/RL/RR" i.d.R.
                    # dieselbe Größenordnung wie die Motor-Speed-Kanäle hat.
                    "maxVal": float(gr.get("max_val", 5.0)),
                })
            elif gtype == "vector":
                entry.update({
                    "channelAngle": gr.get("channel_angle", 0),
                    "channelSpeed": gr.get("channel_speed", 0),
                    "maxVal": float(gr.get("max_val", 1.0)),
                })
            elif gtype == "table":
                entry.update({
                    "title": gr.get("title", ""),
                    "channels": parse_channels(gr.get("channels", [])),
                })
            elif gtype == "bodies":
                def _body(b: dict) -> dict:
                    return {
                        "label": b.get("label", ""),
                        "color": b.get("color", "#4ec9b0"),
                        "diameter": float(b.get("diameter", 0.3)),
                        "channelX": int(b.get("channel_x", -1)),
                        "channelY": int(b.get("channel_y", -1)),
                        "channelAngle": int(b.get("channel_angle", -1)),
                        "channelDiameter": int(b.get("channel_diameter", -1)),
                    }
                entry.update({
                    "fieldWidth": float(gr.get("field_width", 2.0)),
                    "fieldHeight": float(gr.get("field_height", 1.5)),
                    "body1": _body(gr.get("body1", {})),
                    "body2": _body(gr.get("body2", {})),
                })
            graphics.append(entry)

        groups.append({
            "name": g.get("name", "Gruppe"),
            "imageUrl": _image_url(image_idx),
            "overlays": overlays,
            "graphics": graphics,
        })

    return groups


class VisualsBridge(QObject):
    groupsChanged       = pyqtSignal()
    activeGroupChanged  = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._groups = _load_groups()
        self._active_index = 0

    @pyqtProperty("QVariantList", notify=groupsChanged)
    def groupNames(self):
        return [g["name"] for g in self._groups]

    @pyqtProperty(int, notify=activeGroupChanged)
    def activeIndex(self):
        return self._active_index

    @pyqtProperty("QVariantMap", notify=activeGroupChanged)
    def activeGroup(self):
        if not self._groups:
            return {"name": "", "imageUrl": "", "overlays": [], "graphics": []}
        return self._groups[self._active_index]

    @pyqtSlot(int)
    def setActiveIndex(self, idx: int) -> None:
        if 0 <= idx < len(self._groups) and idx != self._active_index:
            self._active_index = idx
            self.activeGroupChanged.emit()
