"""
runtime_config.py — vom Teensy uebernommene Konfiguration, dauerhaft gespeichert
================================================================================
Der Teensy ist die Quelle der Wahrheit fuer

    * die Kanalnamen und -einheiten,
    * den kompletten Aufbau des Parameter-Tabs (Widget, Bereich, Gruppe),
    * die Anzeige-Elemente der Systemansicht (Overlays),

alles gepflegt in `teensy_firmware/src/channel_config.h`. Er schickt das beim
Boot als JSON-Deskriptor. Dieses Modul legt das Ergebnis dauerhaft auf dem
Raspberry Pi ab, JE NODE getrennt — nach einem Neustart der GUI (oder des
ganzen Pi) steht damit sofort wieder alles da, auch ohne eingeschalteten
Roboter.

────────────────────────────────────────────────────────────────────────────
WER GEWINNT BEI EINEM KONFLIKT?
────────────────────────────────────────────────────────────────────────────
Die Overlays und Parameter lassen sich auch in der GUI selbst bearbeiten.
Wuerde jeder eintreffende Deskriptor blind ueberschreiben, waere jede
Anpassung nach dem naechsten Einschalten des Roboters wieder weg. Wuerde er
NIE ueberschreiben, kaeme eine neue Firmware nie in der GUI an.

Deshalb ein Fingerabdruck: zu jeder gespeicherten Datei wird gemerkt, aus
welchem Teensy-Inhalt sie entstanden ist (`_teensy_hash`).

    Fingerabdruck unveraendert  ->  lokale Bearbeitung bleibt stehen
    Fingerabdruck geaendert     ->  der Teensy hat eine neue Konfiguration,
                                    sie wird uebernommen

Damit gilt die einfache Regel: **etwas in channel_config.h aendern und neu
flashen setzt sich durch, alles andere nicht.** Die Dateien im Repository
(param_config.json, visuals_overlays.json) bleiben unberuehrte Vorlagen.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import app_settings
from config import RUNTIME_CONFIG_DIR, runtime_config_path

log = logging.getLogger(__name__)

PARAM_CONFIG_NAME  = "param_config.json"
VISUALS_NAME       = "visuals_overlays.json"
DESCRIPTOR_NAME    = "descriptor.json"
GUI_SETTINGS_NAME  = "gui_settings.json"

_HASH_KEY = "_teensy_hash"
TEENSY_HASH_KEY = _HASH_KEY      # oeffentlicher Name fuer andere Module

# Wird gesetzt, sobald die Anordnung im Overlay-Editor der GUI von Hand
# bearbeitet und gespeichert wurde (siehe bridge/visuals_bridge.py).
LOCAL_EDIT_KEY = "_locally_edited"


def merge_decision(stored: dict | None, digest: str,
                   editing_unsaved: bool = False) -> str:
    """Was soll mit einer neu eingetroffenen Teensy-Konfiguration passieren?

        "keep"      -> nichts tun, die gespeicherte Fassung gilt weiter
        "ask"       -> zurueckhalten und den Benutzer fragen
        "overwrite" -> die Teensy-Fassung uebernehmen und speichern

    Ausgelagert aus visuals_bridge.py, weil hier die eigentliche Regel steht
    (siehe "Wer gewinnt bei einem Konflikt?") und weil eine reine Funktion
    ohne PyQt6 in tools/selftest.py durchgespielt werden kann. Die Faelle
    unterscheiden sich nur in Kleinigkeiten und genau da entstehen Fehler:
    einmal falsch herum, und entweder kommt eine neue Firmware nie an oder
    sie loescht bei jedem Einschalten die Handarbeit.
    """
    if editing_unsaved:
        return "ask"                 # nicht unter der offenen Bearbeitung wegziehen
    if not stored:
        return "overwrite"           # noch nichts gespeichert -> Erstbefuellung
    if stored.get(_HASH_KEY) == digest:
        return "keep"                # unveraenderte Firmware
    if stored.get(LOCAL_EDIT_KEY):
        return "ask"                 # neue Firmware, aber Handarbeit vorhanden
    return "overwrite"


# ══════════════════════════════════════════════════════════════════════════
#  Datei-Grundlagen
# ══════════════════════════════════════════════════════════════════════════

def teensy_hash(obj: Any) -> str:
    """Stabiler Fingerabdruck eines JSON-faehigen Objekts.

    sort_keys=True: die Reihenfolge der Schluessel im Teensy-JSON ist zwar
    stabil, aber daran soll sich nichts aufhaengen — es geht um den INHALT.
    """
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_json(node_id: int, name: str) -> dict | None:
    """Gespeicherte Datei lesen. Fehlt oder kaputt -> None (kein Fehler)."""
    path = runtime_config_path(node_id, name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("%s ist unlesbar (%s) — wird ignoriert.", path, exc)
        return None
    return data if isinstance(data, dict) else None


def save_json(node_id: int, name: str, data: dict) -> bool:
    """Atomar schreiben: erst .tmp, dann os.replace().

    Ohne das Zwischen-Temporaerfile hinterlaesst ein Stromausfall mitten im
    Schreiben eine halbe Datei — und die GUI startet beim naechsten Mal ohne
    Konfiguration. os.replace() ist auf einem Dateisystem atomar.
    """
    path = runtime_config_path(node_id, name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.error("%s konnte nicht geschrieben werden: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def clear(node_id: int) -> int:
    """Alle gespeicherten Dateien eines Nodes loeschen (Knopf "Zuruecksetzen").
    Gibt die Anzahl geloeschter Dateien zurueck."""
    folder = RUNTIME_CONFIG_DIR / f"node{int(node_id)}"
    removed = 0
    try:
        for f in folder.glob("*.json"):
            f.unlink()
            removed += 1
    except OSError as exc:
        log.warning("Zuruecksetzen von %s fehlgeschlagen: %s", folder, exc)
    return removed


# ══════════════════════════════════════════════════════════════════════════
#  Teensy-Parameterkonfiguration -> param_config.json-Format
# ══════════════════════════════════════════════════════════════════════════

# Die Kurzschluessel im Deskriptor sparen UART-Bytes (siehe PDS.cpp::putParamDef).
_PARAM_KEY_MAP = {
    "i": "index", "n": "name", "w": "widget", "min": "min", "max": "max",
    "step": "step", "def": "default", "g": "group", "m": "momentary",
}
_JOY_KEY_MAP = {
    "n": "name", "s": "source", "x": "x_index", "y": "y_index",
    "xr": "x_range", "yr": "y_range", "c": "return_to_center",
}

# Muss zu param_io._VALID_WIDGETS passen.
_VALID_WIDGETS = {"number", "slider", "toggle", "button", "joystick_axis", "text"}

# Kennzeichnet einen Wert, der sich nicht in eine Zahl umwandeln laesst.
# Bewusst ein eigenes Objekt und nicht None: `None` ist im Deskriptor ein
# moeglicher (wenn auch unsinniger) Wert, und "fehlt" muss von "steht drin,
# ist aber Unsinn" unterscheidbar bleiben.
_BAD = object()


def _num(value: Any, fallback: float | None = None):
    """Einen Wert aus dem Deskriptor in ein float wandeln.

    Gibt `fallback` zurueck, wenn der Schluessel gar nicht da war (value is
    None und fallback gesetzt), und `_BAD`, wenn etwas drinsteht, das keine
    Zahl ist. Der Aufrufer ueberspringt den Eintrag dann — genau so, wie es
    der Docstring von _convert_entries beschreibt.

    Ohne diese Stelle riss ein einziger unplausibler Eintrag (`"def": null`
    aus einer halb uebertragenen Firmware) die KOMPLETTE Parameter-
    Konfiguration mit: der TypeError lief bis in _persist_registry hoch, und
    dort wurde er nur geloggt — der Roboter stand danach mit der Vorlage aus
    dem Repository da statt mit seiner eigenen Konfiguration.
    """
    if value is None and fallback is not None:
        return fallback
    try:
        out = float(value)
    except (TypeError, ValueError):
        return _BAD
    return _BAD if out != out or out in (float("inf"), float("-inf")) else out


def _convert_entries(raw: Any, bool_like: bool) -> list[dict]:
    """Eine Teensy-Liste in param_config.json-Eintraege wandeln.

    Bewusst defensiv: der Inhalt kam ueber UART und WLAN. Ein einzelner
    unplausibler Eintrag darf nicht die ganze Konfiguration verwerfen —
    er wird uebersprungen.
    """
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry: dict = {}
        for short, long in _PARAM_KEY_MAP.items():
            if short in item:
                entry[long] = item[short]
        try:
            idx = int(entry.get("index", -1))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx in seen:
            continue          # load_param_config() wuerde bei Dubletten werfen
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        widget = entry.get("widget", "toggle" if bool_like else "slider")
        if widget not in _VALID_WIDGETS:
            widget = "toggle" if bool_like else "slider"
        entry["index"] = idx
        entry["widget"] = widget
        if bool_like:
            # Bools kennen keinen Bereich; ein Default != 0 heisst schlicht True.
            entry["default"] = bool(entry.get("default", 0))
            entry.pop("min", None)
            entry.pop("max", None)
            entry.pop("step", None)
            entry["momentary"] = bool(entry.get("momentary", False))
        else:
            entry.pop("momentary", None)
            lo = _num(entry.get("min"), 0.0)
            hi = _num(entry.get("max"), 1.0)
            default = _num(entry.get("default"), 0.0)
            step = _num(entry.get("step"), 0.01)
            if _BAD in (lo, hi, default, step):
                continue
            if hi <= lo:
                # Ein leerer Bereich macht jeden Regler unbedienbar.
                hi = lo + 1.0
            entry["min"], entry["max"] = lo, hi
            entry["default"] = min(max(default, lo), hi)
            entry["step"] = abs(step) or 0.01
        seen.add(idx)
        out.append(entry)
    return out


def _convert_joysticks(raw: Any) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry: dict = {}
        for short, long in _JOY_KEY_MAP.items():
            if short in item:
                entry[long] = item[short]
        if entry.get("source") not in ("slow", "fast"):
            continue
        try:
            entry["x_index"] = int(entry["x_index"])
            entry["y_index"] = int(entry["y_index"])
        except (KeyError, TypeError, ValueError):
            continue
        entry.setdefault("name", "Joystick")
        bad_range = False
        for key in ("x_range", "y_range"):
            rng = entry.get(key)
            if not (isinstance(rng, list) and len(rng) == 2):
                entry[key] = [-100.0, 100.0]
                continue
            lo, hi = _num(rng[0]), _num(rng[1])
            if _BAD in (lo, hi):
                bad_range = True
                break
            entry[key] = [lo, hi]
        if bad_range:
            continue          # ein unlesbarer Bereich verwirft nur DIESEN Joystick
        entry["return_to_center"] = bool(entry.get("return_to_center", True))
        out.append(entry)
    return out


def param_config_from_descriptor(param_cfg: dict) -> dict | None:
    """Baut aus dem `param_cfg`-Abschnitt des Deskriptors eine vollstaendige
    param_config.json-Struktur. None, wenn der Teensy nichts geliefert hat
    (channel_config.h leer) — dann bleibt die lokale Konfiguration gueltig."""
    if not isinstance(param_cfg, dict):
        return None

    floats = _convert_entries(param_cfg.get("slow_floats"), bool_like=False)
    bools = _convert_entries(param_cfg.get("slow_bools"), bool_like=True)
    fast = _convert_entries(param_cfg.get("fast_floats"), bool_like=False)
    joys = _convert_joysticks(param_cfg.get("joysticks"))

    if not (floats or bools or fast or joys):
        return None

    return {
        "version": 2,
        "floats": floats,
        "bools": bools,
        "fast_floats": fast,
        "joysticks": joys,
    }


# ══════════════════════════════════════════════════════════════════════════
#  Zusammenfuehren + speichern
# ══════════════════════════════════════════════════════════════════════════

def sync_param_config(node_id: int, param_cfg: dict) -> tuple[Path | None, bool]:
    """Parameter-Konfiguration des Teensy uebernehmen, falls sie sich geaendert
    hat.

    Rueckgabe: (Pfad der gueltigen Datei oder None, wurde_geschrieben).
    Der Pfad ist auch dann gesetzt, wenn nichts geschrieben wurde — dann
    zeigt er auf die bereits vorhandene gespeicherte Datei.
    """
    path = runtime_config_path(node_id, PARAM_CONFIG_NAME)
    new = param_config_from_descriptor(param_cfg)
    if new is None:
        return (path if path.exists() else None), False

    digest = teensy_hash(new)
    existing = load_json(node_id, PARAM_CONFIG_NAME)
    if existing is not None and existing.get(_HASH_KEY) == digest:
        return path, False          # unveraendert -> lokale Bearbeitung behalten

    new[_HASH_KEY] = digest
    written = save_json(node_id, PARAM_CONFIG_NAME, new)
    if written:
        log.info(
            "Parameter-Konfiguration von Node %d uebernommen und gespeichert "
            "(%d Floats, %d Bools, %d Fast, %d Joysticks).",
            node_id, len(new["floats"]), len(new["bools"]),
            len(new["fast_floats"]), len(new["joysticks"]),
        )
    return (path if written or path.exists() else None), written


def param_config_path_for(node_id: int, fallback: Path) -> Path:
    """Welche param_config.json gilt fuer diesen Node?

    Die gespeicherte Fassung, sobald es sie gibt — sonst die Vorlage aus dem
    Repository. So laeuft ein frisches Projekt sofort, und ein eingerichtetes
    System benutzt den Stand seines eigenen Roboters.
    """
    path = runtime_config_path(node_id, PARAM_CONFIG_NAME)
    return path if path.exists() else fallback


# ══════════════════════════════════════════════════════════════════════════
#  Oberflaechen-Einstellungen des Teensy
# ══════════════════════════════════════════════════════════════════════════
#  Seit PDS 2.2 liegt im Deskriptor ein Abschnitt "settings" (Punktpfad ->
#  Wert). Er wird nach derselben Regel behandelt wie alles andere aus dem
#  Teensy (siehe "Wer gewinnt bei einem Konflikt?" am Anfang der Datei):
#
#      Fingerabdruck unveraendert -> nichts tun. Wer die Schriftgroesse in
#                                    der GUI nachgestellt hat, behaelt sie.
#      Fingerabdruck geaendert    -> uebernehmen. Eine neue Firmware setzt
#                                    sich durch.
#
#  Gemerkt wird der Fingerabdruck in einer eigenen kleinen Datei je Node.
#  Sie enthaelt zusaetzlich, was uebernommen und was verworfen wurde — im
#  Zweifelsfall am Spielfeldrand ist das die einzige Stelle, an der man
#  nachsehen kann, warum eine Einstellung aus der Firmware nicht ankam.

def sync_gui_settings(node_id: int, flat: dict) -> tuple[dict, list[str]]:
    """Einstellungen des Teensy uebernehmen, falls sie sich geaendert haben.

    Rueckgabe: (uebernommen, verworfen). Beide leer, wenn es nichts zu tun
    gab — der Aufrufer meldet dann auch nichts.
    """
    if not isinstance(flat, dict) or not flat:
        return {}, []

    digest = teensy_hash(flat)
    stored = load_json(node_id, GUI_SETTINGS_NAME)
    if stored is not None and stored.get(_HASH_KEY) == digest:
        return {}, []               # unveraendert -> lokale Bearbeitung behalten

    applied, rejected = app_settings.apply_teensy_settings(flat)

    # Den Fingerabdruck AUCH dann merken, wenn nichts uebernommen wurde:
    # sonst wuerde dieselbe unbrauchbare Vorgabe bei jedem Deskriptor erneut
    # durchprobiert und jedes Mal dieselbe Warnung ins Logbuch schreiben.
    save_json(node_id, GUI_SETTINGS_NAME, {
        _HASH_KEY: digest,
        "applied": applied,
        "rejected": rejected,
    })

    if applied:
        app_settings.save(app_settings.SETTINGS)
        log.info("Node %d: %d Oberflaechen-Einstellung(en) vom Teensy uebernommen "
                 "(%d verworfen).", node_id, len(applied), len(rejected))
    return applied, rejected

def save_descriptor(node_id: int, data: dict) -> bool:
    """Den kompletten Roh-Deskriptor mitschreiben.

    Kostet fast nichts und ist bei einem Problem im Feld die einzige
    Moeglichkeit nachzusehen, was der Roboter tatsaechlich gemeldet hat.
    """
    return save_json(node_id, DESCRIPTOR_NAME, data)
