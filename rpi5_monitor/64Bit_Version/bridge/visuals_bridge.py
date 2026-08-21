"""
bridge/visuals_bridge.py — Tab 3 (Systemansicht)
====================================================
Lädt die Overlay-Konfiguration und reicht sie aufbereitet an SystemView.qml:

  - je Gruppe: Bildpfad + Liste der Text-Overlays (x_pct/y_pct/label/channel)
  - je Gruppe: Liste der "Grafiken" (gauge/rotation/vector/table/bodies),
    inkl. aufgelöster Kanal-Listen (parse_channels) für den table-Typ

Die eigentliche Positionierung/Skalierung übernimmt QML über Bindings an
`Image.paintedWidth/paintedHeight`.

────────────────────────────────────────────────────────────────────────────
"textgrid" — VIELE WERTE MIT EINER ZEILE AUFS BILD
────────────────────────────────────────────────────────────────────────────
Ein Text-Overlay je Messwert bedeutete: 30 Einträge mit je eigener x/y-
Position von Hand pflegen, und bei jeder Verschiebung alle nachziehen. Der
Typ "textgrid" beschreibt stattdessen einen ganzen BLOCK:

    channels=0-11,20;cols=2;dx=24;dy=5

Angegeben wird nur die linke obere Ecke; die Aufteilung in Zeilen und
Spalten rechnet expand_textgrid() aus. In der gespeicherten Konfiguration
bleibt es EIN Eintrag — die Auflösung passiert erst beim Laden, damit die
Datei kompakt und von Hand editierbar bleibt.

────────────────────────────────────────────────────────────────────────────
WOHER DIE KONFIGURATION KOMMT
────────────────────────────────────────────────────────────────────────────
Vorrang hat die vom Teensy gemeldete und je Node gespeicherte Fassung
(runtime_config/nodeN/visuals_overlays.json). Erst wenn es die nicht gibt,
gilt visuals_overlays.json aus dem Repository als Vorlage. Ändert sich der
Fingerabdruck der Teensy-Overlays (neue Firmware), wird die gespeicherte
Fassung ersetzt; sonst bleiben lokale Bearbeitungen stehen. Siehe
runtime_config.py, Abschnitt "Wer gewinnt bei einem Konflikt?".
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot

import runtime_config
from bridge.utils import parse_channels, expand_textgrid as _expand_textgrid
from config import VARIABLE_NAMES
from channel_registry import apply_overlay_defaults, ChannelRegistry

log = logging.getLogger("bridge.visuals")

_BILD_DIR      = Path(__file__).resolve().parent.parent / "bild"
_TEMPLATE_FILE = Path(__file__).resolve().parent.parent / "visuals_overlays.json"

_HASH_KEY = "_teensy_hash"


def _image_url(image_idx: int) -> str:
    path = _BILD_DIR / f"Bild{image_idx}.png"
    return path.resolve().as_uri() if path.exists() else ""


def _config_file(node_id: int) -> Path:
    """Gespeicherte Fassung dieses Nodes, sonst die Vorlage im Repository."""
    stored = runtime_config.runtime_config_path(node_id, runtime_config.VISUALS_NAME)
    return stored if stored.exists() else _TEMPLATE_FILE


def expand_textgrid(entry: dict) -> list[dict]:
    """Duenne Huelle um bridge.utils.expand_textgrid — die eigentliche
    Rechnung liegt dort, damit sie ohne PyQt6 pruefbar ist (siehe
    tools/selftest.py)."""
    return _expand_textgrid(entry, lambda ch: VARIABLE_NAMES.get(ch, f"Var_{ch:03d}"))


def _overlay_to_entry(o: dict) -> list[dict]:
    """Ein gespeichertes Overlay in die QML-Struktur bringen. Gibt eine LISTE
    zurück, weil ein textgrid zu vielen Einträgen wird."""
    if o.get("type") == "textgrid":
        return expand_textgrid(o)
    return [{
        "label": o.get("label", ""),
        "channel": o.get("channel_idx", o.get("channel", 0)),
        "xPct": float(o.get("x_pct", 5.0)),
        "yPct": float(o.get("y_pct", 8.0)),
        "color": o.get("color", "#4ec9b0"),
    }]


def _load_groups(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("%s nicht gefunden — Systemansicht bleibt leer.", path.name)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("%s ist nicht lesbar: %s", path.name, exc)
        return []

    groups: list[dict] = []
    for g in raw.get("groups", []):
        image_idx = g.get("image_idx", 1)

        overlays: list[dict] = []
        for o in g.get("overlays", []):
            if isinstance(o, dict):
                overlays.extend(_overlay_to_entry(o))

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
                    "maxVal": float(gr.get("max_val", 5.0)),
                })
            elif gtype == "vector":
                entry.update({
                    "channelAngle": gr.get("channel_angle", 0),
                    "channelSpeed": gr.get("channel_speed", 0),
                    "maxVal": float(gr.get("max_val", 1.0)),
                })
            elif gtype == "table":
                chans = parse_channels(gr.get("channels", []))
                entry.update({
                    "title": gr.get("title", ""),
                    "channels": chans,
                    "channelNames": [VARIABLE_NAMES.get(c, f"Var_{c:03d}") for c in chans],
                })
            elif gtype == "bodies":
                def _body(b: dict) -> dict:
                    return {
                        "label": b.get("label", ""),
                        "color": b.get("color", "#4ec9b0"),
                        "diameter": float(b.get("diameter", 18.0)),
                        "channelX": int(b.get("channel_x", -1)),
                        "channelY": int(b.get("channel_y", -1)),
                        "channelAngle": int(b.get("channel_angle", -1)),
                        "channelDiameter": int(b.get("channel_diameter", -1)),
                    }
                # Feldmaße in ZENTIMETERN im Feldkoordinatensystem:
                #   x = 0..fieldXCm nach Osten, y = 0..fieldYCm nach Norden.
                # field_width/field_height (Meter) sind das Altformat und
                # werden weiterhin angenommen.
                if "field_x_cm" in gr or "field_y_cm" in gr:
                    fx = float(gr.get("field_x_cm", 180.0))
                    fy = float(gr.get("field_y_cm", 240.0))
                else:
                    fx = float(gr.get("field_width", 1.8)) * 100.0
                    fy = float(gr.get("field_height", 2.4)) * 100.0
                entry.update({
                    "fieldXCm": fx,
                    "fieldYCm": fy,
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


def _load_raw_config(path: Path) -> dict:
    """Liest die Overlay-Konfiguration im Rohformat (unaufbereitet)."""
    if not path.exists():
        return {"groups": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("%s ist nicht lesbar: %s", path.name, exc)
        return {"groups": []}
    return data if isinstance(data, dict) else {"groups": []}


def _save_raw_config(path: Path, config: dict) -> bool:
    """Atomar schreiben: erst in eine Temp-Datei daneben, dann umbenennen.

    Beim direkten write_text() hätte ein Absturz (oder ein Strom-Aus am
    RPi 5) mitten im Schreiben eine halb geschriebene, unlesbare Datei
    hinterlassen — und damit die komplette Systemansicht dauerhaft leer.

    Gibt False zurück, wenn nicht geschrieben werden konnte. Das darf die
    GUI NICHT abbrechen: die Overlays sind dann eben nur bis zum nächsten
    Start da.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.warning("%s konnte nicht geschrieben werden: %s", path.name, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


class VisualsBridge(QObject):
    groupsChanged      = pyqtSignal()
    activeGroupChanged = pyqtSignal()
    sourceChanged      = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._node_id = 1
        self._path = _config_file(self._node_id)
        self._groups = _load_groups(self._path)
        self._active_index = 0

    # ── Node-Wechsel ──────────────────────────────────────────────────────
    def set_node(self, node_id: int) -> None:
        if node_id == self._node_id:
            return
        self._node_id = node_id
        self.refresh()

    @pyqtProperty(str, notify=sourceChanged)
    def configSource(self):
        """Woher die angezeigte Konfiguration stammt (Einstellungs-Tab)."""
        if self._path == _TEMPLATE_FILE:
            return f"Vorlage: {_TEMPLATE_FILE.name}"
        return f"vom Teensy: {self._path}"

    # ── Neu einlesen ──────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Liest die Konfiguration neu ein (z. B. nachdem Namen/Overlays
        aktualisiert wurden). Anders als bei ParamBridge unproblematisch,
        da SystemView.qml keine editierbaren Regler-Zustände hält — nur
        reine Anzeige-Widgets, die ohnehin aus telemetry.latestValues
        neu gezeichnet werden."""
        self._path = _config_file(self._node_id)
        self._groups = _load_groups(self._path)
        # Gruppenzahl kann beim Neuladen kleiner geworden sein -> Index
        # nachziehen, sonst wirft activeGroup einen IndexError.
        if self._active_index >= len(self._groups):
            self._active_index = max(0, len(self._groups) - 1)
        self.groupsChanged.emit()
        self.activeGroupChanged.emit()
        self.sourceChanged.emit()

    def apply_overlay_defaults_from_registry(
        self, registry: ChannelRegistry, node_id: int = 1
    ) -> None:
        """Overlay-Mapping des Teensy übernehmen und dauerhaft speichern.

        Läuft im GUI-Poll-Timer — hier darf nichts durchschlagen, sonst
        reißt ein kaputtes JSON oder ein schreibgeschütztes Verzeichnis die
        gesamte Datenpipeline mit.
        """
        self._node_id = node_id
        try:
            self._merge_and_store(registry, node_id)
        except Exception as exc:            # noqa: BLE001 — bewusst breit
            log.warning("Overlay-Defaults konnten nicht übernommen werden: %s", exc)
        self.refresh()   # Namens-Änderungen (VARIABLE_NAMES) sollen so oder so durch

    def _merge_and_store(self, registry: ChannelRegistry, node_id: int) -> None:
        if not registry.overlays:
            return
        stored_path = runtime_config.runtime_config_path(
            node_id, runtime_config.VISUALS_NAME)
        digest = runtime_config.teensy_hash(registry.overlays)

        if stored_path.exists():
            raw = _load_raw_config(stored_path)
            if raw.get(_HASH_KEY) == digest:
                return          # unverändert -> lokale Bearbeitung behalten
        else:
            # Erstbefüllung: von der Vorlage ausgehen, damit Gruppennamen und
            # Bildzuordnung erhalten bleiben.
            raw = _load_raw_config(_TEMPLATE_FILE)

        # overwrite=True auch bei der Erstbefüllung: die Vorlage im Repository
        # ist in aller Regel schon befüllt, und mit overwrite=False käme die
        # Anordnung des Teensy dann NIE an — genau das, was hier gewollt ist.
        # Gruppen ohne passenden Teensy-Eintrag bleiben unangetastet.
        changed = apply_overlay_defaults(raw, registry, overwrite=True)
        raw[_HASH_KEY] = digest
        if _save_raw_config(stored_path, raw):
            log.info("Overlays von Node %d übernommen und gespeichert "
                      "(%s, %s).", node_id, stored_path,
                      "Gruppen ersetzt" if changed else "nur Fingerabdruck")

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
