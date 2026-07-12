"""
param_io.py — Laden/Speichern der Param-Konfiguration und -Defaults
=====================================================================
Zwei unabhängige Aufgaben in einer Datei:

1) param_config.json  →  Widget-Spezifikation (Namen, Widget-Typ, Grenzen)
   Legt fest, WIE die 50 Slow-Floats, 50 Slow-Bools und 5 Fast-Floats in
   der GUI dargestellt werden. Lebt auf dem RPi 5 (dort, wo die GUI läuft).

2) param_defaults.h  ↔  aktuelle Werte (reiner Text, keine echte C-Kompilierung)
   Wird über den "Speichern als Default"-Button in der GUI geschrieben und
   beim nächsten GUI-Start wieder eingelesen, um die zuletzt gespeicherten
   Werte als Startwerte zu verwenden (überschreibt die "default"-Werte aus
   param_config.json, falls die Datei vorhanden und gültig ist).

Beide Funktionen sind bewusst robust gegen fehlende/kaputte Dateien:
- load_param_config() wirft bei WIDERSPRÜCHLICHER Konfiguration (doppelte
  Indizes, ungültiger Widget-Typ) einen klaren ValueError — das darf NICHT
  still verschluckt werden, sonst fährt man mit falscher Zuordnung.
- read_param_defaults_h() gibt dagegen bei fehlender/kaputter Datei None
  zurück (kein Fehler) — die GUI fällt dann einfach auf die JSON-Defaults
  zurück, das ist ein normaler, erwarteter Fall (z. B. beim allerersten
  Start, bevor überhaupt einmal gespeichert wurde).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════
#  Datenklassen
# ══════════════════════════════════════════════════════════════════════════

_VALID_WIDGETS = {"number", "slider", "toggle", "button", "joystick_axis", "text"}


@dataclass
class ParamEntry:
    """Eine einzelne Zeile aus param_config.json (ein Float oder ein Bool)."""
    index: int
    name: str
    widget: str
    default: float | bool = 0.0
    min: float = 0.0
    max: float = 1.0
    step: float = 0.01
    momentary: bool = False
    group: str = ""   # Optionale Gruppe für Sub-Abschnitte im Param-Tab


@dataclass
class JoystickEntry:
    """Ein Eintrag aus dem 'joysticks'-Abschnitt — fasst zwei Float-Indizes
    (x_index/y_index) zu einem 2-Achsen-Widget zusammen."""
    name: str
    source: str        # "slow" oder "fast" — aus welcher Liste stammen x_index/y_index
    x_index: int
    y_index: int
    x_range: tuple[float, float] = (-100.0, 100.0)
    y_range: tuple[float, float] = (-100.0, 100.0)
    return_to_center: bool = True


@dataclass
class ParamConfig:
    floats: list[ParamEntry]
    bools: list[ParamEntry]
    fast_floats: list[ParamEntry]
    joysticks: list[JoystickEntry] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════
#  param_config.json laden + validieren
# ══════════════════════════════════════════════════════════════════════════

def _default_range_for(widget: str) -> tuple[float, float]:
    """Slider und Joystick-Achsen sind standardmäßig ±100 (Konvention für
    dieses Projekt), alle anderen Widget-Typen 0.0..1.0."""
    if widget in ("slider", "joystick_axis"):
        return -100.0, 100.0
    return 0.0, 1.0


def _resolve_entries(
    raw_list: list[dict],
    count: int,
    fallback_widget: str,
    fallback_default: float | bool,
    label: str,
) -> list[ParamEntry]:
    """
    Baut eine vollständige Liste von `count` ParamEntry-Objekten (Index 0..count-1).
    Für jeden in raw_list explizit konfigurierten Index wird der JSON-Eintrag
    übernommen (mit Validierung). Alle NICHT konfigurierten Indizes bekommen
    einen generischen Fallback-Eintrag (analog zu VARIABLE_NAMES in config.py),
    damit param_config.json nicht von Anfang an alle 50/50/5 Einträge enthalten
    muss — sie kann während der Saisonvorbereitung schrittweise wachsen.
    """
    by_index: dict[int, ParamEntry] = {}

    for e in raw_list:
        idx = e.get("index")
        if idx is None:
            raise ValueError(f"[{label}] Eintrag ohne 'index': {e}")
        if not (0 <= idx < count):
            raise ValueError(f"[{label}] Index {idx} außerhalb 0..{count - 1}")
        if idx in by_index:
            raise ValueError(
                f"[{label}] Index {idx} doppelt vergeben "
                f"('{by_index[idx].name}' vs. '{e.get('name')}')"
            )
        widget = e.get("widget", fallback_widget)
        if widget not in _VALID_WIDGETS:
            raise ValueError(
                f"[{label}] Ungültiger widget-Typ '{widget}' bei Index {idx}. "
                f"Gültig sind: {sorted(_VALID_WIDGETS)}"
            )
        if "name" not in e:
            raise ValueError(f"[{label}] Eintrag bei Index {idx} hat kein 'name'-Feld")

        min_default, max_default = _default_range_for(widget)
        by_index[idx] = ParamEntry(
            index=idx,
            name=e["name"],
            widget=widget,
            default=e.get("default", fallback_default),
            min=e.get("min", min_default),
            max=e.get("max", max_default),
            step=e.get("step", 0.01),
            momentary=e.get("momentary", False),
            group=e.get("group", ""),
        )

    # Fallback-Einträge für alle nicht konfigurierten Indizes ergänzen
    prefix = "Bool" if fallback_widget == "toggle" else "Float"
    for idx in range(count):
        if idx not in by_index:
            min_default, max_default = _default_range_for(fallback_widget)
            by_index[idx] = ParamEntry(
                index=idx,
                name=f"{prefix}_{idx:02d}",
                widget=fallback_widget,
                default=fallback_default,
                min=min_default,
                max=max_default,
            )

    return [by_index[i] for i in range(count)]


def load_param_config(
    path: Path,
    float_count: int = 50,
    bool_count: int = 50,
    fast_float_count: int = 5,
) -> ParamConfig:
    """
    Lädt und validiert param_config.json.

    Wirft ValueError mit klarer, auf die konkrete Datei bezogener Meldung,
    wenn die Konfiguration widersprüchlich ist (doppelte Indizes, ungültiger
    Widget-Typ, Joystick referenziert nicht-existenten Index, ...).
    Fehlt die Datei komplett, wird eine reine Fallback-Konfiguration
    zurückgegeben (alle Einträge generisch benannt) — das ist bewusst KEIN
    Fehler, sondern der normale Zustand direkt nach dem Anlegen des Projekts.
    """
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} ist kein gültiges JSON: {exc}") from exc
    else:
        raw = {}

    floats = _resolve_entries(
        raw.get("floats", []), float_count, "number", 0.0, "floats"
    )
    bools = _resolve_entries(
        raw.get("bools", []), bool_count, "toggle", False, "bools"
    )
    fast_floats = _resolve_entries(
        raw.get("fast_floats", []), fast_float_count, "number", 0.0, "fast_floats"
    )

    joysticks: list[JoystickEntry] = []
    for j in raw.get("joysticks", []):
        name = j.get("name", "Joystick")
        source = j.get("source")
        if source not in ("slow", "fast"):
            raise ValueError(
                f"[joysticks] '{name}': 'source' muss 'slow' oder 'fast' sein, "
                f"nicht {source!r}"
            )
        x_index = j.get("x_index")
        y_index = j.get("y_index")
        max_idx = (float_count if source == "slow" else fast_float_count) - 1
        for axis_name, idx in (("x_index", x_index), ("y_index", y_index)):
            if idx is None or not (0 <= idx <= max_idx):
                raise ValueError(
                    f"[joysticks] '{name}': {axis_name}={idx} ist ungültig "
                    f"für source='{source}' (gültig: 0..{max_idx})"
                )
        joysticks.append(JoystickEntry(
            name=name,
            source=source,
            x_index=x_index,
            y_index=y_index,
            x_range=tuple(j.get("x_range", (-100.0, 100.0))),
            y_range=tuple(j.get("y_range", (-100.0, 100.0))),
            return_to_center=j.get("return_to_center", True),
        ))

    return ParamConfig(floats=floats, bools=bools, fast_floats=fast_floats, joysticks=joysticks)


# ══════════════════════════════════════════════════════════════════════════
#  param_defaults.h  ↔  aktuelle Werte (reiner Text, kein echtes C-Parsing)
# ══════════════════════════════════════════════════════════════════════════

_FLOAT_ARR_RE = re.compile(r"PARAM_FLOAT_DEFAULTS\s*\[\d+\]\s*=\s*\{([^}]*)\}")
_BOOL_ARR_RE  = re.compile(r"PARAM_BOOL_DEFAULTS\s*\[\d+\]\s*=\s*\{([^}]*)\}")
_FAST_ARR_RE  = re.compile(r"PARAM_FAST_FLOAT_DEFAULTS\s*\[\d+\]\s*=\s*\{([^}]*)\}")


def write_param_defaults_h(
    path: Path,
    floats,        # Iterable[float], Länge 50
    bools,         # Iterable[bool],  Länge 50
    fast_floats,   # Iterable[float], Länge 5
) -> None:
    """Schreibt die aktuellen Werte als einfache, menschenlesbare C-Array-Syntax.
    Wird von der GUI (Save-Button) aufgerufen, siehe tab_params.py."""

    def _fmt_floats(values) -> str:
        return ", ".join(f"{float(v):.6f}f" for v in values)

    def _fmt_bools(values) -> str:
        return ", ".join("true" if b else "false" for b in values)

    floats = list(floats)
    bools = list(bools)
    fast_floats = list(fast_floats)

    text = (
        "// ============================================================\n"
        "//  param_defaults.h — Auto-generated by Power Debug Monitor\n"
        f"//  Gespeichert am: {datetime.now().isoformat(timespec='seconds')}\n"
        "//  NICHT MANUELL BEARBEITEN (wird von der GUI ueberschrieben)\n"
        "// ============================================================\n"
        "#pragma once\n\n"
        f"static const float PARAM_FLOAT_DEFAULTS[{len(floats)}] = {{\n"
        f"    {_fmt_floats(floats)}\n}};\n\n"
        f"static const bool PARAM_BOOL_DEFAULTS[{len(bools)}] = {{\n"
        f"    {_fmt_bools(bools)}\n}};\n\n"
        f"static const float PARAM_FAST_FLOAT_DEFAULTS[{len(fast_floats)}] = {{\n"
        f"    {_fmt_floats(fast_floats)}\n}};\n"
    )
    path.write_text(text, encoding="utf-8")


def read_param_defaults_h(path: Path) -> dict | None:
    """
    Liest param_defaults.h zurück und gibt ein dict mit den Schlüsseln
    'floats', 'bools', 'fast_floats' (jeweils Liste) zurück.

    Gibt None zurück, wenn die Datei fehlt oder nicht parsebar ist — der
    Aufrufer fällt dann auf die JSON-Defaults zurück (siehe Modul-Docstring).
    Wirft absichtlich NIE eine Exception, damit ein von Hand angefasstes
    oder beschädigtes File die GUI nicht am Start hindert.
    """
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")

        def _parse_floats(body: str) -> list[float]:
            return [float(x.strip().rstrip("fF")) for x in body.split(",") if x.strip()]

        def _parse_bools(body: str) -> list[bool]:
            return [x.strip().lower() == "true" for x in body.split(",") if x.strip()]

        m_f = _FLOAT_ARR_RE.search(text)
        m_b = _BOOL_ARR_RE.search(text)
        m_ff = _FAST_ARR_RE.search(text)

        if not (m_f and m_b):
            return None   # Datei existiert, aber Grundstruktur fehlt/ist kaputt

        return {
            "floats": _parse_floats(m_f.group(1)),
            "bools": _parse_bools(m_b.group(1)),
            "fast_floats": _parse_floats(m_ff.group(1)) if m_ff else None,
        }
    except (ValueError, OSError):
        return None   # z. B. "abc" statt einer Zahl irgendwo in der Datei
