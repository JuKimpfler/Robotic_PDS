"""
overlay_schema.py — was ein Overlay-Eintrag hat und wie man ihn bearbeitet
============================================================================
Die Systemansicht kennt sieben Arten von Anzeige-Elementen (Text, Textraster,
Zeiger, Drehanzeige, Vektor, Tabelle, Feldansicht). Jede hat andere Felder.

Wuerde der Editor fuer jede Art ein eigenes QML-Formular mitbringen, waeren
das sieben fast gleiche Bloecke mit je einem Dutzend Bedienelementen — und
bei jedem neuen Feld muesste man sie alle anfassen. Stattdessen beschreibt
dieses Modul die Felder als DATEN:

    describe(entry) -> [{"key": "channel", "label": "Kanal",
                         "type": "channel", "value": 10, ...}, ...]

QML rendert daraus mit EINEM Repeater das passende Formular. Ein neues Feld
ist hier eine Zeile — in QML gar nichts.

Bewusst ohne PyQt6-Import: so laesst sich die komplette Bearbeitungslogik
(Typumwandlung, Wertebereiche, Pruefungen) in tools/selftest.py ohne
Bildschirm und ohne Qt pruefen.

────────────────────────────────────────────────────────────────────────────
DAS GESPEICHERTE FORMAT BLEIBT UNVERAENDERT
────────────────────────────────────────────────────────────────────────────
Der Editor arbeitet auf dem ROHFORMAT von visuals_overlays.json, nicht auf
der aufbereiteten Fassung, die SystemView.qml anzeigt. Das ist der ganze
Trick beim Textraster: angezeigt werden 30 Textfelder, gespeichert bleibt
EIN Eintrag. Wuerde der Editor die aufbereitete Fassung zurueckschreiben,
waere das Raster nach dem ersten Speichern in 30 Einzeleintraege zerfallen
und der Sinn ("nicht 30 Positionen von Hand pflegen") dahin.
"""
from __future__ import annotations

from typing import Any, Callable, List

from bridge.utils import parse_channels

# Kanalzahl des Wire-Formats — jede Kanalnummer wird darauf begrenzt.
try:
    from config import MAX_FLOATS
except ImportError:                                  # pragma: no cover
    MAX_FLOATS = 200


# ══════════════════════════════════════════════════════════════════════════
#  Arten von Eintraegen
# ══════════════════════════════════════════════════════════════════════════
#  "text" hat in der JSON-Datei KEIN "type"-Feld — das ist historisch so und
#  bleibt so, damit bestehende Dateien unveraendert weiter funktionieren.
#  entry_kind() bildet dieses Fehlen auf "text" ab.

OVERLAY_KINDS = ("text", "textgrid")
GRAPHIC_KINDS = ("gauge", "rotation", "vector", "table", "bodies")

KIND_LABELS = {
    "text":     "Text",
    "textgrid": "Textraster",
    "gauge":    "Zeiger",
    "rotation": "Drehanzeige",
    "vector":   "Vektor",
    "table":    "Tabelle",
    "bodies":   "Feldansicht",
}

# Kurzbeschreibung fuer das Menue "Hinzufuegen".
KIND_HINTS = {
    "text":     "Ein Messwert an einer Stelle des Bildes",
    "textgrid": "Viele Messwerte als Block — eine Position fuer alle",
    "gauge":    "Balken mit Minimum und Maximum",
    "rotation": "Drehrichtung und -geschwindigkeit",
    "vector":   "Pfeil aus Winkel und Betrag",
    "table":    "Wertetabelle neben dem Bild",
    "bodies":   "Spielfeld mit zwei Objekten (ersetzt das Bild)",
}

# Touch-taugliche Farbauswahl: lieber acht gute Farben zum Antippen als ein
# Farbrad, das man mit dem Finger nicht trifft.
COLOR_PRESETS = (
    "#4ec9b0", "#19f3ec", "#9cdcfe", "#f0c060",
    "#f48771", "#c586c0", "#a5dc6e", "#ffffff",
)

_DEFAULT_COLOR = COLOR_PRESETS[0]


def entry_kind(entry: dict) -> str:
    """Art eines Roheintrags. Fehlendes "type" bedeutet "text"."""
    kind = str(entry.get("type") or "text")
    return kind if kind in KIND_LABELS else "text"


def is_graphic(kind: str) -> bool:
    return kind in GRAPHIC_KINDS


# ══════════════════════════════════════════════════════════════════════════
#  Feldbeschreibungen
# ══════════════════════════════════════════════════════════════════════════
#  type:
#    "text"     freier Text
#    "int"      ganze Zahl mit min/max/step
#    "real"     Kommazahl mit min/max/step und Nachkommastellen
#    "bool"     Schalter
#    "color"    eine der COLOR_PRESETS
#    "channel"  Kanalnummer -> QML zeigt zusaetzlich den Kanalnamen und
#               oeffnet auf Wunsch die Kanalauswahl
#    "channels" Kanal-Spezifikation wie "0-11,20" (parse_channels)

def _f(key: str, label: str, ftype: str, **kw) -> dict:
    out = {"key": key, "label": label, "type": ftype}
    out.update(kw)
    return out


def _pos_fields() -> List[dict]:
    """x/y in Prozent der BILDflaeche. Wird auch per Ziehen gesetzt; die
    Felder bleiben trotzdem, weil sich zwei Overlays so exakt untereinander
    ausrichten lassen — mit dem Finger trifft man 41.0 nie genau."""
    return [
        _f("x_pct", "x  (% der Bildbreite)", "real",
           min=-20.0, max=120.0, step=0.5, decimals=1),
        _f("y_pct", "y  (% der Bildhoehe)", "real",
           min=-20.0, max=120.0, step=0.5, decimals=1),
    ]


def _channel_field(key: str, label: str, allow_none: bool = False) -> dict:
    return _f(key, label, "channel",
              min=-1 if allow_none else 0, max=MAX_FLOATS - 1, step=1,
              allowNone=allow_none)


def _body_fields(prefix: str, title: str) -> List[dict]:
    return [
        _f(f"{prefix}.label", f"{title}: Name", "text"),
        _f(f"{prefix}.color", f"{title}: Farbe", "color"),
        _f(f"{prefix}.diameter", f"{title}: Durchmesser (cm)", "real",
           min=0.5, max=100.0, step=0.5, decimals=1),
        _channel_field(f"{prefix}.channel_x", f"{title}: Kanal x (cm, nach rechts)", True),
        _channel_field(f"{prefix}.channel_y", f"{title}: Kanal y (cm, nach oben)", True),
        _channel_field(f"{prefix}.channel_angle",
                       f"{title}: Kanal Winkel (Grad, 0 = rechts)", True),
        _channel_field(f"{prefix}.channel_diameter", f"{title}: Kanal Durchmesser", True),
    ]


_SCHEMAS: dict[str, Callable[[], List[dict]]] = {
    "text": lambda: [
        _f("label", "Beschriftung", "text"),
        _channel_field("channel_idx", "Kanal"),
        *_pos_fields(),
        _f("color", "Farbe", "color"),
    ],
    "textgrid": lambda: [
        _f("label", "Name des Blocks", "text",
           hint="Nur zur Wiedererkennung in der Liste — steht nicht im Bild."),
        _f("channels", "Kanaele", "channels",
           hint='Einzeln, Bereiche und Kommas: "0-11,20,30-33"'),
        _f("cols", "Spalten", "int", min=1, max=12, step=1),
        _f("dx_pct", "Spaltenabstand (%)", "real",
           min=0.5, max=60.0, step=0.5, decimals=1),
        _f("dy_pct", "Zeilenabstand (%)", "real",
           min=0.5, max=40.0, step=0.5, decimals=1),
        *_pos_fields(),
        _f("labels", "Kanalnamen anzeigen", "bool"),
        _f("color", "Farbe", "color"),
    ],
    "gauge": lambda: [
        _f("label", "Beschriftung", "text"),
        _channel_field("channel", "Kanal"),
        _f("min", "Minimum", "real", min=-1e6, max=1e6, step=0.5, decimals=2),
        _f("max", "Maximum", "real", min=-1e6, max=1e6, step=0.5, decimals=2),
    ],
    "rotation": lambda: [
        _f("label", "Beschriftung", "text"),
        _channel_field("channel", "Kanal"),
        _f("max_val", "Groesste erwartete Drehrate", "real",
           min=0.01, max=1e5, step=0.5, decimals=2,
           hint="Nur fuer die Pfeillaenge — begrenzt nichts am Roboter."),
    ],
    "vector": lambda: [
        _f("label", "Beschriftung", "text"),
        _channel_field("channel_angle", "Kanal Winkel (Grad)"),
        _channel_field("channel_speed", "Kanal Betrag"),
        _f("max_val", "Groesster erwarteter Betrag", "real",
           min=0.01, max=1e5, step=0.5, decimals=2),
    ],
    "table": lambda: [
        _f("title", "Ueberschrift", "text"),
        _f("channels", "Kanaele", "channels",
           hint='Einzeln, Bereiche und Kommas: "0-9,15"'),
    ],
    "bodies": lambda: [
        _f("label", "Beschriftung", "text"),
        _f("field_x_cm", "Feld waagerecht, x (cm)", "real",
           min=10.0, max=2000.0, step=10.0, decimals=0),
        _f("field_y_cm", "Feld senkrecht, y (cm)", "real",
           min=10.0, max=2000.0, step=10.0, decimals=0),
        _f("goal_width_cm", "Toroeffnung (cm)", "real",
           min=5.0, max=500.0, step=5.0, decimals=0,
           hint="Quer zur Spielrichtung, also entlang der x-Achse."),
        _f("goal_depth_cm", "Tortiefe (cm)", "real",
           min=2.0, max=200.0, step=2.0, decimals=0),
        _f("show_image", "Bild der Gruppe als Hintergrund", "bool",
           hint="An: das Bild der Gruppe ist eine Aufnahme des Spielfeldes. "
                "Aus: das Feld wird selbst gezeichnet (Tore, Mittelkreis)."),
        *_body_fields("body1", "Objekt 1"),
        *_body_fields("body2", "Objekt 2"),
    ],
}


def fields_for(kind: str) -> List[dict]:
    """Feldbeschreibung einer Art — ohne Werte."""
    builder = _SCHEMAS.get(kind)
    return builder() if builder else []


# ══════════════════════════════════════════════════════════════════════════
#  Werte lesen und schreiben
# ══════════════════════════════════════════════════════════════════════════

def _split(key: str) -> tuple[list[str], str]:
    parts = key.split(".")
    return parts[:-1], parts[-1]


def get_value(entry: dict, key: str) -> Any:
    """Wert zu einem (auch verschachtelten) Schluessel, z. B. "body1.label"."""
    node: Any = entry
    path, last = _split(key)
    for p in path:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node.get(last) if isinstance(node, dict) else None


def _ensure(entry: dict, path: list[str]) -> dict:
    node = entry
    for p in path:
        child = node.get(p)
        if not isinstance(child, dict):
            child = {}
            node[p] = child
        node = child
    return node


def _default_for(field: dict) -> Any:
    ftype = field["type"]
    if ftype == "bool":
        return True
    if ftype == "color":
        return _DEFAULT_COLOR
    if ftype in ("int", "channel"):
        return int(field.get("min", 0))
    if ftype == "real":
        return float(field.get("min", 0.0))
    return ""


def coerce(field: dict, value: Any) -> Any:
    """Einen aus QML kommenden Wert auf den deklarierten Typ bringen.

    QML liefert aus einem Textfeld IMMER eine Zeichenkette — auch fuer eine
    Kanalnummer. Ohne diese Stelle landete "12" als Text in der JSON-Datei,
    und parse_channels/int() waeren beim naechsten Laden darueber gestolpert.
    Ein nicht umwandelbarer Wert laesst das Feld unveraendert (None).
    """
    ftype = field["type"]

    if ftype == "bool":
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "nein", "off")
        return bool(value)

    if ftype in ("int", "channel"):
        try:
            iv = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        lo = int(field.get("min", 0))
        hi = int(field.get("max", MAX_FLOATS - 1))
        return max(lo, min(hi, iv))

    if ftype == "real":
        try:
            fv = float(str(value).replace(",", "."))   # deutsche Tastatur
        except (TypeError, ValueError):
            return None
        if fv != fv or fv in (float("inf"), float("-inf")):
            return None                                # NaN/Inf nie speichern
        lo = float(field.get("min", -1e9))
        hi = float(field.get("max", 1e9))
        return max(lo, min(hi, fv))

    if ftype == "color":
        text = str(value).strip()
        return text if text.startswith("#") and len(text) in (4, 7, 9) else _DEFAULT_COLOR

    if ftype == "channels":
        # Nicht auf die aufgeloeste Liste reduzieren: "0-11" soll "0-11"
        # bleiben und nicht als zwoelf Einzelzahlen in der Datei landen.
        return str(value).strip()

    return str(value)


def set_value(entry: dict, key: str, value: Any) -> bool:
    """Feld setzen, mit Typumwandlung. True, wenn sich etwas geaendert hat."""
    field = next((f for f in fields_for(entry_kind(entry)) if f["key"] == key), None)
    if field is None:
        return False
    new = coerce(field, value)
    if new is None:
        return False
    path, last = _split(key)
    node = _ensure(entry, path)
    if node.get(last) == new and last in node:
        return False
    node[last] = new
    return True


def describe(entry: dict) -> List[dict]:
    """Feldbeschreibung MIT aktuellen Werten — genau das, was QML rendert."""
    out: List[dict] = []
    for field in fields_for(entry_kind(entry)):
        item = dict(field)
        value = get_value(entry, field["key"])
        item["value"] = _default_for(field) if value is None else coerce(field, value)
        out.append(item)
    return out


def new_entry(kind: str, x_pct: float = 40.0, y_pct: float = 40.0) -> dict:
    """Frischer Eintrag mit sinnvollen Startwerten.

    Wichtig fuer die Bedienung: ein neuer Eintrag darf nicht unsichtbar sein.
    Deshalb bekommt er eine Position mitten im Bild und eine gut sichtbare
    Farbe — sonst tippt man auf "Hinzufuegen" und es passiert scheinbar
    nichts.
    """
    entry: dict = {}
    for field in fields_for(kind):
        path, last = _split(field["key"])
        _ensure(entry, path)[last] = _default_for(field)

    if kind != "text":
        entry["type"] = kind          # "text" bleibt ohne type-Feld

    if kind in ("text", "textgrid"):
        entry["x_pct"] = float(x_pct)
        entry["y_pct"] = float(y_pct)
    if kind == "text":
        entry["label"] = "Neu"
    if kind == "textgrid":
        entry.update({"label": "Neuer Block", "channels": "0-3", "cols": 2,
                      "dx_pct": 22.0, "dy_pct": 5.0, "labels": True})
    if kind == "gauge":
        entry.update({"label": "Neuer Zeiger", "min": -1.0, "max": 1.0})
    if kind == "rotation":
        entry.update({"label": "Neue Drehanzeige", "max_val": 5.0})
    if kind == "vector":
        entry.update({"label": "Neuer Vektor", "max_val": 1.0})
    if kind == "table":
        entry.update({"title": "Neue Tabelle", "channels": "0-9"})
    if kind == "bodies":
        entry.update({"label": "Spielfeld", "field_x_cm": 240.0, "field_y_cm": 180.0,
                      "goal_width_cm": 45.0, "goal_depth_cm": 10.0,
                      "show_image": True})
        for i, prefix in enumerate(("body1", "body2"), start=1):
            entry[prefix].update({"label": f"Objekt {i}", "diameter": 18.0,
                                  "color": COLOR_PRESETS[i - 1]})
    return entry


# ══════════════════════════════════════════════════════════════════════════
#  Pruefung
# ══════════════════════════════════════════════════════════════════════════

# Wie weit ein Element ueber den Bildrand hinausgeschoben werden darf.
# Etwas darueber hinaus ist erwuenscht (Beschriftungen am Rand), ganz aus dem
# Bild heraus nicht — dann waere der Eintrag im Bild nicht mehr auffindbar.
POS_MIN, POS_MAX = -15.0, 115.0


def move_position(entry: dict, dx_pct: float, dy_pct: float) -> tuple[float, float]:
    """Neue x/y-Position nach einer Zieh-Geste — RELATIV zur bisherigen.

    Relativ und nicht absolut, weil beim Textraster irgendeine der Zellen
    gezogen wird, gemeint aber immer die linke obere Ecke des Blocks ist.
    Eine absolute Position muesste erst ueber Spaltenzahl und Abstaende
    zurueckgerechnet werden und waere bei Zelle 17 schlicht falsch.
    """
    def _num(v, fallback: float) -> float:
        try:
            out = float(v)
        except (TypeError, ValueError):
            return fallback
        return fallback if out != out else out
    x = _num(entry.get("x_pct"), 5.0) + _num(dx_pct, 0.0)
    y = _num(entry.get("y_pct"), 8.0) + _num(dy_pct, 0.0)
    return (round(max(POS_MIN, min(POS_MAX, x)), 2),
            round(max(POS_MIN, min(POS_MAX, y)), 2))


def problems(entry: dict) -> List[str]:
    """Was an diesem Eintrag nicht stimmt — als Klartext fuer den Editor.

    Absichtlich WARNUNGEN und keine Fehler: ein Eintrag mit einem Kanal, den
    es (noch) nicht gibt, laesst sich weiter bearbeiten und speichern. Er
    zeigt dann eben "—" an. Ein Editor, der das Speichern verweigert, waere
    beim Umbauen der Firmware nur im Weg.
    """
    kind = entry_kind(entry)
    out: List[str] = []

    for field in fields_for(kind):
        if field["type"] != "channel":
            continue
        raw = get_value(entry, field["key"])
        try:
            chn = int(raw)
        except (TypeError, ValueError):
            out.append(f"{field['label']}: keine gueltige Kanalnummer")
            continue
        if chn < 0:
            if not field.get("allowNone"):
                out.append(f"{field['label']}: kein Kanal gewaehlt")
        elif chn >= MAX_FLOATS:
            out.append(f"{field['label']}: Kanal {chn} gibt es nicht "
                       f"(0 bis {MAX_FLOATS - 1})")

    if kind in ("textgrid", "table"):
        chans = parse_channels(get_value(entry, "channels") or "")
        if not chans:
            out.append("Kanaele: leer oder unlesbar")
        else:
            bad = [c for c in chans if not 0 <= c < MAX_FLOATS]
            if bad:
                out.append("Kanaele ausserhalb 0 bis "
                           f"{MAX_FLOATS - 1}: {', '.join(map(str, bad[:5]))}")

    if kind == "gauge":
        try:
            if float(entry.get("min", 0.0)) >= float(entry.get("max", 1.0)):
                out.append("Minimum ist nicht kleiner als Maximum")
        except (TypeError, ValueError):
            out.append("Minimum/Maximum sind keine Zahlen")

    if kind == "bodies":
        for prefix in ("body1", "body2"):
            has_x = int(get_value(entry, f"{prefix}.channel_x") or -1) >= 0
            has_y = int(get_value(entry, f"{prefix}.channel_y") or -1) >= 0
            if has_x != has_y:
                out.append(f"{prefix}: x und y muessen beide gesetzt sein")

    return out


def summary(entry: dict, name_for: Callable[[int], str]) -> str:
    """Eine Zeile fuer die Liste im Editor — sagt, was der Eintrag zeigt."""
    kind = entry_kind(entry)
    label = str(entry.get("label") or entry.get("title") or "").strip()

    if kind == "text":
        chn = int(entry.get("channel_idx", entry.get("channel", 0)) or 0)
        return f"{label or '(ohne Beschriftung)'} — {name_for(chn)}"
    if kind in ("textgrid", "table"):
        chans = parse_channels(entry.get("channels", ""))
        rng = f"{len(chans)} Kanaele" if chans else "keine Kanaele"
        return f"{label or 'Block'} — {rng}"
    if kind in ("gauge", "rotation"):
        return f"{label} — {name_for(int(entry.get('channel', 0) or 0))}"
    if kind == "vector":
        a = name_for(int(entry.get("channel_angle", 0) or 0))
        s = name_for(int(entry.get("channel_speed", 0) or 0))
        return f"{label} — {a} / {s}"
    if kind == "bodies":
        return (f"{label or 'Spielfeld'} — "
                f"{entry.get('field_x_cm', 180):.0f}x{entry.get('field_y_cm', 240):.0f} cm")
    return label
