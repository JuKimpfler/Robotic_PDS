"""
bridge/visuals_bridge.py — Tab 3 (Systemansicht) samt Editor
====================================================================
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
DER EDITOR ARBEITET AUF DEM ROHFORMAT
────────────────────────────────────────────────────────────────────────────
`self._raw` ist die Datei, `self._groups` die daraus aufbereitete Anzeige.
Bearbeitet wird ausschließlich `self._raw`; danach wird neu aufbereitet.

Der Rückweg von einem angezeigten Textfeld zum Roheintrag läuft über
`rawIndex`, das beim Aufbereiten mitgeschrieben wird. Zieht man eine der 30
Zellen eines Textrasters, landet die Verschiebung damit an der linken oberen
Ecke des BLOCKS — und der bleibt beim Speichern ein einziger Eintrag. Würde
der Editor stattdessen die aufbereitete Fassung zurückschreiben, wäre das
Raster nach dem ersten Speichern in 30 Einzelpositionen zerfallen.

────────────────────────────────────────────────────────────────────────────
WOHER DIE KONFIGURATION KOMMT
────────────────────────────────────────────────────────────────────────────
Vorrang hat die vom Teensy gemeldete und je Node gespeicherte Fassung
(runtime_config/nodeN/visuals_overlays.json). Erst wenn es die nicht gibt,
gilt visuals_overlays.json aus dem Repository als Vorlage. Ändert sich der
Fingerabdruck der Teensy-Overlays (neue Firmware), wird die gespeicherte
Fassung ersetzt; sonst bleiben lokale Bearbeitungen stehen. Siehe
runtime_config.py, Abschnitt "Wer gewinnt bei einem Konflikt?".

AUSNAHME seit dem Editor: wurde die Anordnung hier von Hand bearbeitet
(`_locally_edited`), wird sie NICHT mehr stillschweigend überschrieben. Die
neue Teensy-Fassung wird zurückgehalten und im Editor als Frage angeboten
("Teensy meldet eine neue Anordnung: übernehmen / verwerfen"). Sonst wäre
eine halbe Stunde Positionierarbeit beim nächsten Flashen weg — und zwar
ohne jeden Hinweis.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot

import overlay_schema
import runtime_config
from bridge.utils import parse_channels, expand_textgrid as _expand_textgrid
from config import MAX_FLOATS, VARIABLE_NAMES
from channel_registry import apply_overlay_defaults, ChannelRegistry

log = logging.getLogger("bridge.visuals")

_BILD_DIR      = Path(__file__).resolve().parent.parent / "bild"
_TEMPLATE_FILE = Path(__file__).resolve().parent.parent / "visuals_overlays.json"

# Beide Schluessel gehoeren zur Konfliktregel und sind dort definiert.
_HASH_KEY   = runtime_config.TEENSY_HASH_KEY
_EDITED_KEY = runtime_config.LOCAL_EDIT_KEY

# Wie viele Bearbeitungsschritte zurückgenommen werden können. Eine
# Momentaufnahme ist die komplette Datei als JSON — bei ~13 kB sind 50
# Schritte unter einem Megabyte und damit auf dem RPi 5 belanglos.
_UNDO_DEPTH = 50

# Anzahl auswählbarer Hintergrundbilder (bild/Bild1.png … Bild4.png).
_MAX_IMAGE_IDX = 8


def _channel_name(chn: int) -> str:
    return VARIABLE_NAMES.get(chn, f"Var_{chn:03d}")


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
    return _expand_textgrid(entry, _channel_name)


def _overlay_to_entry(o: dict, raw_index: int) -> list[dict]:
    """Ein gespeichertes Overlay in die QML-Struktur bringen. Gibt eine LISTE
    zurück, weil ein textgrid zu vielen Einträgen wird.

    `rawIndex` ist der Rückweg für den Editor: jede angezeigte Zelle weiß,
    aus welchem Eintrag der Datei sie stammt.
    """
    if o.get("type") == "textgrid":
        out = expand_textgrid(o)
    else:
        out = [{
            "label": o.get("label", ""),
            "channel": o.get("channel_idx", o.get("channel", 0)),
            "xPct": float(o.get("x_pct", 5.0)),
            "yPct": float(o.get("y_pct", 8.0)),
            "color": o.get("color", "#4ec9b0"),
        }]
    for cell in out:
        cell["rawIndex"] = raw_index
    return out


def _graphic_to_entry(gr: dict, raw_index: int) -> dict:
    gtype = gr.get("type", "")
    entry = {"type": gtype, "label": gr.get("label", gr.get("title", "")),
             "rawIndex": raw_index}
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
            "channelNames": [_channel_name(c) for c in chans],
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
            "goalWidthCm": float(gr.get("goal_width_cm", 45.0)),
            "goalDepthCm": float(gr.get("goal_depth_cm", 10.0)),
            "showImage": bool(gr.get("show_image", False)),
            "body1": _body(gr.get("body1", {})),
            "body2": _body(gr.get("body2", {})),
        })
    return entry


def _groups_from_raw(raw: dict) -> list[dict]:
    """Rohformat -> Anzeigeformat. Getrennt von _load_groups(), damit der
    Editor nach jeder Änderung neu aufbereiten kann, ohne die Datei
    anzufassen."""
    groups: list[dict] = []
    for g in raw.get("groups", []):
        overlays: list[dict] = []
        for i, o in enumerate(g.get("overlays", [])):
            if isinstance(o, dict):
                overlays.extend(_overlay_to_entry(o, i))

        graphics = [_graphic_to_entry(gr, i)
                    for i, gr in enumerate(g.get("graphics", []))
                    if isinstance(gr, dict)]

        groups.append({
            "name": g.get("name", "Gruppe"),
            "imageIdx": int(g.get("image_idx", 1)),
            "imageUrl": _image_url(g.get("image_idx", 1)),
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
    editingChanged     = pyqtSignal()
    selectionChanged   = pyqtSignal()
    pendingChanged     = pyqtSignal()
    notice             = pyqtSignal(str)      # -> AppBridge.statusMessage

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._node_id = 1
        self._path = _config_file(self._node_id)
        self._raw = _load_raw_config(self._path)
        self._groups = _groups_from_raw(self._raw)
        self._active_index = 0

        # ── Editor-Zustand ────────────────────────────────────────────────
        self._editing = False
        self._dirty = False
        self._undo: list[str] = []
        self._sel_list = ""          # "overlays" | "graphics" | ""
        self._sel_idx = -1
        # Vom Teensy gemeldete, aber wegen lokaler Bearbeitung zurück-
        # gehaltene Anordnung (siehe Modul-Docstring).
        self._pending: list[dict] | None = None

    # ── Node-Wechsel ──────────────────────────────────────────────────────
    def set_node(self, node_id: int) -> None:
        if node_id == self._node_id:
            return
        # Ungespeicherte Änderungen gehören zum ALTEN Node und müssen vor dem
        # Wechsel dorthin geschrieben werden. Automatisch statt mit Rückfrage:
        # ein Node-Wechsel passiert oft mitten im Betrieb, und stillschweigend
        # zwanzig Minuten Positionierarbeit wegzuwerfen wäre die schlechtere
        # der beiden Überraschungen.
        if self._dirty:
            self._write(self._node_id)
            self.notice.emit(f"Anordnung von Node {self._node_id} gespeichert.")
        self._node_id = node_id
        self._pending = None
        self._clear_selection()
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
        neu gezeichnet werden.

        Läuft die Bearbeitung gerade, wird NICHT von der Platte gelesen: der
        Poll-Timer ruft das hier im Sekundentakt auf (Kanalnamen), und jedes
        Mal die halbfertige Bearbeitung wegzuwerfen wäre unbenutzbar. Neu
        aufbereitet wird trotzdem, damit geänderte Kanalnamen sofort in den
        Beschriftungen stehen.
        """
        if not self._editing:
            self._path = _config_file(self._node_id)
            self._raw = _load_raw_config(self._path)
            self._dirty = False
            self._undo.clear()
        self._rebuild()
        self.sourceChanged.emit()

    def _rebuild(self) -> None:
        """Anzeigeformat aus self._raw neu erzeugen und QML benachrichtigen."""
        self._groups = _groups_from_raw(self._raw)
        # Gruppenzahl kann beim Neuladen kleiner geworden sein -> Index
        # nachziehen, sonst wirft activeGroup einen IndexError.
        if self._active_index >= len(self._groups):
            self._active_index = max(0, len(self._groups) - 1)
        self.groupsChanged.emit()
        self.activeGroupChanged.emit()
        self.selectionChanged.emit()

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

        stored = _load_raw_config(stored_path) if stored_path.exists() else None
        # Die eigentliche Regel steht in runtime_config.merge_decision() —
        # dort, wo sie dokumentiert ist, und ohne PyQt6 durchspielbar.
        decision = runtime_config.merge_decision(
            stored, digest, editing_unsaved=self._editing and self._dirty)

        if decision == "keep":
            self._set_pending(None)
            return
        if decision == "ask":
            self._set_pending(list(registry.overlays))
            return

        # Erstbefüllung geht von der Vorlage aus, damit Gruppennamen und
        # Bildzuordnung erhalten bleiben.
        raw = stored if stored is not None else _load_raw_config(_TEMPLATE_FILE)

        # overwrite=True auch bei der Erstbefüllung: die Vorlage im Repository
        # ist in aller Regel schon befüllt, und mit overwrite=False käme die
        # Anordnung des Teensy dann NIE an — genau das, was hier gewollt ist.
        # Gruppen ohne passenden Teensy-Eintrag bleiben unangetastet.
        changed = apply_overlay_defaults(raw, registry, overwrite=True)
        raw[_HASH_KEY] = digest
        raw.pop(_EDITED_KEY, None)
        if _save_raw_config(stored_path, raw):
            log.info("Overlays von Node %d übernommen und gespeichert "
                      "(%s, %s).", node_id, stored_path,
                      "Gruppen ersetzt" if changed else "nur Fingerabdruck")
        self._set_pending(None)

    def _set_pending(self, overlays: list[dict] | None) -> None:
        if self._pending == overlays:
            return
        self._pending = overlays
        self.pendingChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Anzeige-Properties
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty("QVariantList", notify=groupsChanged)
    def groupNames(self):
        return [g["name"] for g in self._groups]

    @pyqtProperty(int, notify=activeGroupChanged)
    def activeIndex(self):
        return self._active_index

    @pyqtProperty("QVariantMap", notify=activeGroupChanged)
    def activeGroup(self):
        if not self._groups:
            return {"name": "", "imageUrl": "", "imageIdx": 1,
                    "overlays": [], "graphics": []}
        return self._groups[self._active_index]

    @pyqtSlot(int)
    def setActiveIndex(self, idx: int) -> None:
        if 0 <= idx < len(self._groups) and idx != self._active_index:
            self._active_index = idx
            self._clear_selection()
            self.activeGroupChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Editor: Zustand
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(bool, notify=editingChanged)
    def editing(self):
        return self._editing

    @pyqtProperty(bool, notify=editingChanged)
    def dirty(self):
        return self._dirty

    @pyqtProperty(bool, notify=editingChanged)
    def canUndo(self):
        return bool(self._undo)

    @pyqtProperty(bool, notify=pendingChanged)
    def teensyUpdatePending(self):
        """True, wenn der Teensy eine neue Anordnung meldet, die wegen
        lokaler Bearbeitung zurückgehalten wurde."""
        return self._pending is not None

    @pyqtProperty("QVariantList", constant=True)
    def channelNames(self):
        """Alle Kanalnamen für die Kanalauswahl im Editor. `constant`, weil
        QML die Liste einmal holt und selbst filtert — bei 200 Einträgen ist
        das billiger als ein Signal bei jeder Namensänderung."""
        return [f"{i:3d}  {_channel_name(i)}" for i in range(MAX_FLOATS)]

    @pyqtProperty("QVariantList", constant=True)
    def colorPresets(self):
        return list(overlay_schema.COLOR_PRESETS)

    @pyqtProperty("QVariantList", constant=True)
    def overlayKinds(self):
        return self._kind_list(overlay_schema.OVERLAY_KINDS)

    @pyqtProperty("QVariantList", constant=True)
    def graphicKinds(self):
        return self._kind_list(overlay_schema.GRAPHIC_KINDS)

    @staticmethod
    def _kind_list(kinds) -> list[dict]:
        return [{"kind": k,
                 "label": overlay_schema.KIND_LABELS[k],
                 "hint": overlay_schema.KIND_HINTS.get(k, "")}
                for k in kinds]

    @pyqtProperty("QVariantList", constant=True)
    def imageChoices(self):
        """Auswählbare Hintergrundbilder — nur die, die es wirklich gibt."""
        out = []
        for i in range(1, _MAX_IMAGE_IDX + 1):
            url = _image_url(i)
            if url:
                out.append({"idx": i, "url": url, "label": f"Bild {i}"})
        return out

    @pyqtSlot(bool)
    def setEditing(self, on: bool) -> None:
        on = bool(on)
        if on == self._editing:
            return
        if not on and self._dirty:
            # Der Editor wird nur über "Fertig" verlassen; ungespeichertes
            # ginge sonst beim Tab-Wechsel verloren.
            self.save()
        self._editing = on
        if not on:
            self._clear_selection()
        self.editingChanged.emit()

    # ══════════════════════════════════════════════════════════════════════
    #  Editor: Auswahl
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(str, notify=selectionChanged)
    def selectedList(self):
        return self._sel_list

    @pyqtProperty(int, notify=selectionChanged)
    def selectedIndex(self):
        return self._sel_idx

    @pyqtProperty(str, notify=selectionChanged)
    def selectedKind(self):
        e = self._selected_entry()
        return overlay_schema.entry_kind(e) if e is not None else ""

    @pyqtProperty(str, notify=selectionChanged)
    def selectedKindLabel(self):
        return overlay_schema.KIND_LABELS.get(self.selectedKind, "")

    @pyqtProperty("QVariantList", notify=selectionChanged)
    def selectedFields(self):
        """Feldbeschreibung des ausgewählten Eintrags — QML baut daraus mit
        einem einzigen Repeater das komplette Formular (overlay_schema.py)."""
        e = self._selected_entry()
        return overlay_schema.describe(e) if e is not None else []

    @pyqtProperty("QVariantList", notify=selectionChanged)
    def selectedProblems(self):
        e = self._selected_entry()
        return overlay_schema.problems(e) if e is not None else []

    @pyqtProperty("QVariantList", notify=selectionChanged)
    def entryList(self):
        """Alle Einträge der aktiven Gruppe für die Liste im Editor."""
        g = self._raw_group()
        if g is None:
            return []
        out = []
        for name in ("overlays", "graphics"):
            for i, entry in enumerate(g.get(name, [])):
                if not isinstance(entry, dict):
                    continue
                kind = overlay_schema.entry_kind(entry)
                out.append({
                    "list": name,
                    "index": i,
                    "kind": kind,
                    "kindLabel": overlay_schema.KIND_LABELS.get(kind, kind),
                    "summary": overlay_schema.summary(entry, _channel_name),
                    "problems": len(overlay_schema.problems(entry)),
                    "selected": name == self._sel_list and i == self._sel_idx,
                })
        return out

    @pyqtSlot(str, int)
    def select(self, list_name: str, idx: int) -> None:
        g = self._raw_group()
        if g is None or list_name not in ("overlays", "graphics"):
            return
        if not 0 <= idx < len(g.get(list_name, [])):
            return
        self._sel_list, self._sel_idx = list_name, idx
        self.selectionChanged.emit()

    @pyqtSlot(int)
    def selectOverlayByRawIndex(self, raw_index: int) -> None:
        """Antippen eines Textfeldes im Bild wählt seinen Roheintrag aus."""
        self.select("overlays", raw_index)

    @pyqtSlot()
    def clearSelection(self) -> None:
        self._clear_selection()
        self.selectionChanged.emit()

    def _clear_selection(self) -> None:
        self._sel_list, self._sel_idx = "", -1

    def _raw_group(self) -> dict | None:
        groups = self._raw.get("groups", [])
        if 0 <= self._active_index < len(groups):
            g = groups[self._active_index]
            return g if isinstance(g, dict) else None
        return None

    def _selected_entry(self) -> dict | None:
        g = self._raw_group()
        if g is None or not self._sel_list:
            return None
        items = g.get(self._sel_list, [])
        if 0 <= self._sel_idx < len(items) and isinstance(items[self._sel_idx], dict):
            return items[self._sel_idx]
        return None

    # ══════════════════════════════════════════════════════════════════════
    #  Editor: Änderungen
    # ══════════════════════════════════════════════════════════════════════

    def _snapshot(self) -> None:
        """Zustand vor einer Änderung merken (für Rückgängig)."""
        self._undo.append(json.dumps(self._raw, ensure_ascii=False))
        if len(self._undo) > _UNDO_DEPTH:
            del self._undo[0]

    def _touched(self) -> None:
        self._dirty = True
        self._rebuild()
        self.editingChanged.emit()

    @pyqtSlot(str, "QVariant")
    def setField(self, key: str, value) -> None:
        """Ein Feld des ausgewählten Eintrags setzen. Die Typumwandlung
        (QML liefert alles als Zeichenkette) macht overlay_schema.coerce."""
        entry = self._selected_entry()
        if entry is None:
            return
        self._snapshot()
        if overlay_schema.set_value(entry, key, value):
            self._touched()
        else:
            self._undo.pop()     # nichts geändert -> kein Undo-Schritt

    @pyqtSlot(int, float, float)
    def moveOverlayBy(self, raw_index: int, dx_pct: float, dy_pct: float) -> None:
        """Ein Text-Overlay (oder einen ganzen Raster-Block) verschieben.

        RELATIV und nicht absolut: beim Textraster zieht man irgendeine der
        Zellen, gemeint ist aber immer die linke obere Ecke des Blocks. Eine
        absolute Position müsste erst zurückgerechnet werden und wäre bei
        Zelle 17 eines 2-spaltigen Rasters schlicht falsch.
        """
        g = self._raw_group()
        if g is None:
            return
        items = g.get("overlays", [])
        if not 0 <= raw_index < len(items) or not isinstance(items[raw_index], dict):
            return
        entry = items[raw_index]
        self._snapshot()
        entry["x_pct"], entry["y_pct"] = overlay_schema.move_position(
            entry, dx_pct, dy_pct)
        self._touched()

    @pyqtSlot(str)
    def addEntry(self, kind: str) -> None:
        g = self._raw_group()
        if g is None or kind not in overlay_schema.KIND_LABELS:
            return
        target = "graphics" if overlay_schema.is_graphic(kind) else "overlays"
        self._snapshot()
        g.setdefault(target, []).append(overlay_schema.new_entry(kind))
        self._sel_list, self._sel_idx = target, len(g[target]) - 1
        self._touched()
        self.notice.emit(f"{overlay_schema.KIND_LABELS[kind]} hinzugefügt.")

    @pyqtSlot()
    def duplicateSelected(self) -> None:
        entry = self._selected_entry()
        g = self._raw_group()
        if entry is None or g is None:
            return
        self._snapshot()
        clone = copy.deepcopy(entry)
        # Versetzt einfügen, sonst liegt die Kopie exakt unter dem Original
        # und man hält den Editor für kaputt.
        if "x_pct" in clone:
            clone["x_pct"], clone["y_pct"] = overlay_schema.move_position(
                clone, 4.0, 4.0)
        items = g[self._sel_list]
        items.insert(self._sel_idx + 1, clone)
        self._sel_idx += 1
        self._touched()

    @pyqtSlot()
    def removeSelected(self) -> None:
        entry = self._selected_entry()
        g = self._raw_group()
        if entry is None or g is None:
            return
        self._snapshot()
        kind = overlay_schema.entry_kind(entry)
        del g[self._sel_list][self._sel_idx]
        self._sel_idx = min(self._sel_idx, len(g[self._sel_list]) - 1)
        if self._sel_idx < 0:
            self._clear_selection()
        self._touched()
        self.notice.emit(f"{overlay_schema.KIND_LABELS.get(kind, 'Eintrag')} "
                          "gelöscht — Rückgängig mit ⟲.")

    @pyqtSlot(int)
    def moveSelectedInList(self, delta: int) -> None:
        """Reihenfolge ändern — bestimmt bei den Grafiken die Anordnung
        rechts neben dem Bild."""
        g = self._raw_group()
        if self._selected_entry() is None or g is None:
            return
        items = g[self._sel_list]
        new = self._sel_idx + int(delta)
        if not 0 <= new < len(items):
            return
        self._snapshot()
        items.insert(new, items.pop(self._sel_idx))
        self._sel_idx = new
        self._touched()

    @pyqtSlot()
    def undo(self) -> None:
        if not self._undo:
            return
        self._raw = json.loads(self._undo.pop())
        self._dirty = True
        # Die Auswahl kann auf einen Eintrag zeigen, den es nach dem
        # Zurücknehmen nicht mehr gibt.
        if self._selected_entry() is None:
            self._clear_selection()
        self._rebuild()
        self.editingChanged.emit()

    # ── Gruppen ───────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def renameGroup(self, name: str) -> None:
        g = self._raw_group()
        name = str(name).strip()
        if g is None or not name or g.get("name") == name:
            return
        self._snapshot()
        g["name"] = name
        self._touched()

    @pyqtSlot(int)
    def setGroupImage(self, image_idx: int) -> None:
        g = self._raw_group()
        if g is None or int(image_idx) == int(g.get("image_idx", 1)):
            return
        self._snapshot()
        g["image_idx"] = int(image_idx)
        self._touched()

    @pyqtSlot()
    def addGroup(self) -> None:
        self._snapshot()
        groups = self._raw.setdefault("groups", [])
        groups.append({"name": f"Gruppe {len(groups) + 1}",
                       "image_idx": 1, "overlays": [], "graphics": []})
        self._active_index = len(groups) - 1
        self._clear_selection()
        self._touched()

    @pyqtSlot()
    def removeGroup(self) -> None:
        groups = self._raw.get("groups", [])
        if len(groups) <= 1:
            self.notice.emit("Die letzte Gruppe kann nicht gelöscht werden.")
            return
        self._snapshot()
        del groups[self._active_index]
        self._active_index = min(self._active_index, len(groups) - 1)
        self._clear_selection()
        self._touched()

    # ══════════════════════════════════════════════════════════════════════
    #  Editor: Speichern, Verwerfen, Teensy
    # ══════════════════════════════════════════════════════════════════════

    def _write(self, node_id: int) -> bool:
        path = runtime_config.runtime_config_path(
            node_id, runtime_config.VISUALS_NAME)
        # Von Hand bearbeitet: ab jetzt fragt _merge_and_store nach, statt
        # beim nächsten Firmware-Wechsel stillschweigend zu überschreiben.
        self._raw[_EDITED_KEY] = True
        if not _save_raw_config(path, self._raw):
            return False
        self._dirty = False
        self._path = path
        return True

    @pyqtSlot()
    def save(self) -> None:
        if self._write(self._node_id):
            self.notice.emit(f"Anordnung gespeichert: {self._path.name} "
                              f"(Node {self._node_id}).")
        else:
            self.notice.emit("Speichern fehlgeschlagen — siehe Log.")
        self.editingChanged.emit()
        self.sourceChanged.emit()

    @pyqtSlot()
    def revert(self) -> None:
        """Alles seit dem letzten Speichern verwerfen."""
        self._path = _config_file(self._node_id)
        self._raw = _load_raw_config(self._path)
        self._dirty = False
        self._undo.clear()
        self._clear_selection()
        self._rebuild()
        self.editingChanged.emit()
        self.sourceChanged.emit()
        self.notice.emit("Änderungen verworfen.")

    @pyqtSlot()
    def applyPendingTeensyConfig(self) -> None:
        """Die zurückgehaltene Teensy-Anordnung doch übernehmen."""
        if self._pending is None:
            return
        registry = ChannelRegistry()
        registry.overlays = list(self._pending)
        raw = copy.deepcopy(self._raw)
        apply_overlay_defaults(raw, registry, overwrite=True)
        raw[_HASH_KEY] = runtime_config.teensy_hash(self._pending)
        raw.pop(_EDITED_KEY, None)
        self._snapshot()
        self._raw = raw
        self._set_pending(None)
        if _save_raw_config(runtime_config.runtime_config_path(
                self._node_id, runtime_config.VISUALS_NAME), raw):
            self._dirty = False
        self._clear_selection()
        self._rebuild()
        self.editingChanged.emit()
        self.notice.emit("Anordnung des Teensy übernommen.")

    @pyqtSlot()
    def dismissPendingTeensyConfig(self) -> None:
        """Bei der eigenen Anordnung bleiben. Der Fingerabdruck wird auf den
        des Teensy gesetzt, damit dieselbe Firmware nicht bei jedem Boot
        erneut nachfragt."""
        if self._pending is None:
            return
        self._raw[_HASH_KEY] = runtime_config.teensy_hash(self._pending)
        self._raw[_EDITED_KEY] = True
        _save_raw_config(runtime_config.runtime_config_path(
            self._node_id, runtime_config.VISUALS_NAME), self._raw)
        self._set_pending(None)
        self.notice.emit("Eigene Anordnung behalten.")
