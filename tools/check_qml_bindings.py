#!/usr/bin/env python3
"""
tools/check_qml_bindings.py — QML-Zugriffe gegen die Python-Bruecken pruefen
==============================================================================
Greift eine .qml-Datei auf `appBridge.pakcetsPerSecond` zu, meldet Qt das
NICHT als Fehler: der Ausdruck ist einfach `undefined`, die Anzeige bleibt
leer und niemand merkt etwas. Genau diese Tippfehler-Klasse faengt dieses
Skript ab — statisch, ohne PyQt6 und ohne laufende Oberflaeche.

Vorgehen:
  1. Die bridge/-Module und telemetry_bridge werden per `ast` gelesen und je
     Klasse die von QML erreichbaren Namen gesammelt:
       * @pyqtProperty(...)  -> Property-Name = Funktionsname
       * @pyqtSlot(...)      -> aufrufbare Methode
       * X = pyqtSignal(...) -> Signal (in QML als onXChanged nutzbar)
  2. Die .qml-Dateien werden nach `<objekt>.<name>` durchsucht. Aliase wie
     `property var params: appBridge.params` werden dabei aufgeloest.
  3. Jeder Zugriff auf ein bekanntes Bruecken-Objekt mit unbekanntem Namen
     wird gemeldet.

Aufruf:
    python tools/check_qml_bindings.py
Exit-Code 0 = keine unbekannten Zugriffe.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = ROOT / "rpi5_monitor" / "64Bit_Version"
QML_DIR = GUI_DIR / "qml"

# QML-Objektname -> (Python-Datei, Klassenname)
BRIDGE_CLASSES = {
    "AppBridge":            (GUI_DIR / "bridge" / "app_bridge.py", "AppBridge"),
    "TelemetryBridge":      (GUI_DIR / "bridge" / "telemetry_bridge.py", "TelemetryBridge"),
    "TelemetryTableModel":  (GUI_DIR / "bridge" / "telemetry_bridge.py", "TelemetryTableModel"),
    "PlotBridge":           (GUI_DIR / "bridge" / "plot_bridge.py", "PlotBridge"),
    "PlotCanvas":           (GUI_DIR / "bridge" / "plot_bridge.py", "PlotCanvas"),
    "VisualsBridge":        (GUI_DIR / "bridge" / "visuals_bridge.py", "VisualsBridge"),
    "ParamBridge":          (GUI_DIR / "bridge" / "param_bridge.py", "ParamBridge"),
    "ControllerBridge":     (GUI_DIR / "bridge" / "controller_bridge.py", "ControllerBridge"),
    "DiagBridge":           (GUI_DIR / "bridge" / "diag_bridge.py", "DiagBridge"),
    "SettingsBridge":       (GUI_DIR / "bridge" / "settings_bridge.py", "SettingsBridge"),
}

# Von main_qml.py als Kontext-Property gesetzte Wurzelobjekte
ROOT_OBJECTS = {
    "appBridge":      "AppBridge",
    "telemetryModel": "TelemetryTableModel",
}

# Welche Property welcher Bruecke welchen Typ liefert (fuer die Aufloesung
# von `appBridge.params.controller.connected`).
PROPERTY_TYPES = {
    ("AppBridge", "telemetry"): "TelemetryBridge",
    ("AppBridge", "plotter"):   "PlotBridge",
    ("AppBridge", "visuals"):   "VisualsBridge",
    ("AppBridge", "params"):    "ParamBridge",
    ("ParamBridge", "controller"): "ControllerBridge",
    ("AppBridge", "diag"):      "DiagBridge",
    ("AppBridge", "settings"):  "SettingsBridge",
}

# Von QAbstractTableModel/QObject geerbt bzw. in QML immer verfuegbar.
INHERITED = {
    "rowCount", "columnCount", "index", "data", "roleNames", "objectName",
    "destroyed", "toString", "parent",
}


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def members_of(path: Path, class_name: str) -> set[str]:
    """Alle von QML erreichbaren Namen einer Bruecken-Klasse."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set(INHERITED)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decos = {_decorator_name(d) for d in item.decorator_list}
                if decos & {"pyqtProperty", "pyqtSlot"}:
                    names.add(item.name)
            elif isinstance(item, ast.Assign):
                # X = pyqtSignal(...)  bzw.  X = pyqtProperty(...)
                value = item.value
                if isinstance(value, ast.Call) and _decorator_name(value.func) in (
                        "pyqtSignal", "pyqtProperty"):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
                            if _decorator_name(value.func) == "pyqtSignal":
                                # QML-Handler heissen onXyz
                                names.add("on" + target.id[0].upper() + target.id[1:])
    return names


_ALIAS_RE = re.compile(r"property\s+var\s+(\w+)\s*:\s*([\w.]+)")
# Ganze Punkt-Ketten, nicht nur Paare: re.findall liefert keine
# ueberlappenden Treffer, "root.telemetry.setFilter" haette sonst nur
# (root, telemetry) ergeben und der eigentliche Aufruf waere ungeprueft
# durchgerutscht.
_CHAIN_RE = re.compile(r"\b(\w+(?:\.\w+)+)\b")


def resolve(chain: str, aliases: dict[str, str]) -> str | None:
    """'appBridge.params' -> 'ParamBridge'"""
    parts = chain.split(".")
    head = parts[0]
    current = aliases.get(head) or ROOT_OBJECTS.get(head)
    if current is None:
        return None
    for attr in parts[1:]:
        current = PROPERTY_TYPES.get((current, attr))
        if current is None:
            return None
    return current


def check_file(path: Path, members: dict[str, set[str]]) -> list[str]:
    text = path.read_text(encoding="utf-8")

    # 1) Aliase aufloesen (auch mehrstufig: root.telemetry -> appBridge.telemetry)
    aliases: dict[str, str] = {}
    for _ in range(3):                      # bis zu drei Aufloesungsrunden
        for name, chain in _ALIAS_RE.findall(text):
            cls = resolve(chain, aliases)
            if cls:
                aliases[name] = cls

    problems: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("//"):
            continue
        for chain in _CHAIN_RE.findall(line):
            parts = chain.split(".")

            # Einstiegspunkt suchen: das erste Glied, das ein bekanntes
            # Bruecken-Objekt ist (z. B. `telemetry` in `root.telemetry.x`).
            start = None
            for i, part in enumerate(parts):
                cls = aliases.get(part) or ROOT_OBJECTS.get(part)
                if cls is not None:
                    start = (i, cls)
                    break
            if start is None:
                continue

            i, current = start
            for attr in parts[i + 1:]:
                if current is None or current not in members:
                    break     # Kette hat das Bruecken-Objekt verlassen
                if attr not in members[current]:
                    problems.append(
                        f"{path.relative_to(ROOT)}:{lineno}: {chain} "
                        f"— {current} kennt '{attr}' nicht"
                    )
                    break
                current = PROPERTY_TYPES.get((current, attr))
    return problems


def check_balance(path: Path) -> list[str]:
    """Grobe Strukturpruefung: ausgeglichene Klammern ausserhalb von
    Strings/Kommentaren. Faengt abgeschnittene oder halb eingefuegte Bloecke
    ab, bevor Qt sie zur Laufzeit als "failed to load component" meldet."""
    text = path.read_text(encoding="utf-8")
    depth = {"{": 0, "(": 0, "[": 0}
    close_to_open = {"}": "{", ")": "(", "]": "["}
    i, n = 0, len(text)
    in_str: str | None = None
    problems: list[str] = []
    line = 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end < 0:
                problems.append(f"{path.relative_to(ROOT)}: Blockkommentar nicht geschlossen")
                break
            line += text.count("\n", i, end)
            i = end + 2
            continue
        elif ch in depth:
            depth[ch] += 1
        elif ch in close_to_open:
            opener = close_to_open[ch]
            depth[opener] -= 1
            if depth[opener] < 0:
                problems.append(f"{path.relative_to(ROOT)}:{line}: '{ch}' ohne passende Öffnung")
                depth[opener] = 0
        i += 1
    for opener, count in depth.items():
        if count:
            problems.append(f"{path.relative_to(ROOT)}: {count}x '{opener}' nicht geschlossen")
    return problems


def main() -> int:
    members = {name: members_of(path, cls) for name, (path, cls) in BRIDGE_CLASSES.items()}

    qml_files = sorted(QML_DIR.rglob("*.qml"))
    if not qml_files:
        print(f"[FEHLER] Keine .qml-Dateien unter {QML_DIR}")
        return 1

    problems: list[str] = []
    for qml in qml_files:
        problems += check_balance(qml)
        problems += check_file(qml, members)

    print(f"{len(qml_files)} QML-Dateien gegen {len(members)} Bruecken-Klassen geprueft.")
    if problems:
        print("\nUnbekannte Zugriffe:")
        for p in problems:
            print(f"  * {p}")
        return 1
    print("OK — alle QML-Zugriffe auf die Python-Bruecken existieren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
