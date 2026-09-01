"""
app_settings.py — alle Einstellungen der Oberflaeche in EINER Datei
====================================================================
Bis hierher standen die einstellbaren Werte an drei verschiedenen Stellen:
die Bedienereinstellungen in `runtime_config/ui_settings.json`, die Farben,
Abstaende und Schriftgroessen fest verdrahtet in `qml/Theme.qml`, und die
Grenzen der Schieberegler/Drehfelder als Zahlenliteral direkt an dem
Bedienelement, zu dem sie gehoerten (`from: 0.8; to: 1.6`). Wer die
Schriftgroesse auch auf 2.0 stellen koennen wollte, musste QML anfassen.

Jetzt steht alles davon in EINER Datei:

    <Verzeichnis von main_qml.py>/settings.json

Gesucht wird sie ausdruecklich neben dem Python-Skript und nicht im
Home-Verzeichnis des Benutzers — der Ordner ist damit vollstaendig: Skripte,
Konfiguration und die vom Teensy uebernommenen Dateien liegen beieinander
und lassen sich als Ganzes kopieren oder sichern.

────────────────────────────────────────────────────────────────────────────
MEHRERE EINSTELLUNGSSAETZE (PROFILE)
────────────────────────────────────────────────────────────────────────────
Jede Datei `settings.<Name>.json` im selben Ordner ist ein Profil, z. B.

    settings.Spiel.json        (Kiosk an, grosse Schrift, dunkel)
    settings.Werkstatt.json    (Kiosk aus, helles Schema, Tastatur an)

Im Tab "Diagnose" laesst sich der aktuelle Stand unter einem Namen ablegen
und ein Profil wieder laden. Von Hand geht dasselbe mit einem simplen
Kopieren der Datei — genau das war die Absicht: ein Einstellungssatz ist
eine Datei, kein verstecktes Datenbankformat.

────────────────────────────────────────────────────────────────────────────
FEHLENDE, ZUSAETZLICHE UND UNSINNIGE WERTE
────────────────────────────────────────────────────────────────────────────
Die Datei ist ausdruecklich zum Bearbeiten von Hand gedacht. Deshalb gilt
dasselbe Prinzip wie bei controller_config.json (siehe
bridge/controller_bridge.py): ein Tippfehler darf hoechstens dieses eine
Feld kosten und niemals den Start verhindern.

    Schluessel fehlt       -> Standardwert aus DEFAULTS
    Wert hat falschen Typ  -> Warnung im Log, Standardwert bleibt
    Datei fehlt/kaputt     -> komplette Standardwerte, GUI startet normal
    unbekannter Schluessel -> bleibt erhalten (nichts geht verloren),
                              wird aber einmal im Log genannt

`DEFAULTS` unten ist damit gleichzeitig die vollstaendige Dokumentation:
jeder Schluessel, den die Anwendung kennt, steht dort mit seinem
Standardwert.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("app_settings")

# Ausdruecklich das Verzeichnis DIESER Datei (= das von main_qml.py) und
# nicht das aktuelle Arbeitsverzeichnis: der Starter (starter.bat, systemd)
# ruft das Skript mit ganz unterschiedlichen Arbeitsverzeichnissen auf.
BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "settings.json"

# Vorgaenger-Datei; ihre Werte werden beim ersten Start einmalig uebernommen
# (siehe _take_over_legacy / ensure_file). Danach ist sie bedeutungslos.
LEGACY_UI_SETTINGS_PATH = BASE_DIR / "runtime_config" / "ui_settings.json"

PROFILE_PREFIX = "settings."
PROFILE_SUFFIX = ".json"

# Profilnamen werden zu Dateinamen. Punkte und Pfadtrenner sind deshalb
# verboten: ein Name wie "../config" oder "a.b" wuerde sonst entweder aus dem
# Ordner ausbrechen oder beim Auflisten nicht mehr wiedererkannt werden.
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_ -]{1,40}$")

# #rgb, #rrggbb, #aarrggbb — genau das, was QColor/QML versteht.
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


# ══════════════════════════════════════════════════════════════════════════
#  DEFAULTS — die vollstaendige Liste aller bekannten Einstellungen
# ══════════════════════════════════════════════════════════════════════════
DEFAULTS: dict[str, Any] = {
    "_hinweis": (
        "Alle Einstellungen der Oberflaeche. Fehlende Schluessel und "
        "unsinnige Werte werden durch den Standardwert ersetzt, die GUI "
        "startet also immer. Eine Kopie unter dem Namen settings.<Name>.json "
        "ist ein Profil und laesst sich im Tab Diagnose laden."
    ),
    "version": 1,

    # ── Was der Bediener umschaltet (frueher runtime_config/ui_settings.json)
    "ui": {
        "dark": True,
        "fontScale": 1.0,
        "kiosk": False,
        "keyboardControl": True,
        "startTab": 0,           # 0=Tabelle 1=Plotter 2=System 3=Param 4=Diagnose
        "autoApplyTeensyConfig": True,
    },

    # ── Akku-Warnung (rein optisch, siehe bridge/diag_bridge.py) ──────────
    #  Die Schluessel heissen bewusst wie in diag_bridge und QML
    #  (snake_case) — sie werden 1:1 als QVariantMap durchgereicht.
    "battery": {
        "enabled": False,
        "channel": -1,                  # -1 = aus
        "warn_below": 11.5,
        "critical_below": 10.8,
        # So lange muss der Wert am Stueck darunter liegen, bevor gewarnt
        # wird. Ohne das loest jeder Anlaufstrom-Einbruch Alarm aus.
        "hold_seconds": 2.0,
    },

    # ── Grenzen der Schieberegler und Drehfelder ──────────────────────────
    #  Frueher als Zahlenliteral am jeweiligen Bedienelement. Wer die
    #  Schrift groesser braucht als vorgesehen, aendert jetzt hier eine Zahl
    #  statt einer .qml-Datei. Die Python-Seite begrenzt auf dieselben Werte
    #  (siehe SettingsBridge/PlotBridge) — die Grenze gilt also auch fuer
    #  eine von Hand editierte settings.json.
    "ranges": {
        "fontScale":          {"min": 0.8,  "max": 1.6,  "step": 0.05},
        "batteryChannel":     {"min": -1,   "max": 199,  "step": 1},
        "batteryHoldSeconds": {"min": 0.0,  "max": 10.0, "step": 0.1},
        "plotPoints":         {"min": 50,   "max": 600,  "step": 50},
        "plotTriggerPost":    {"min": 0.05, "max": 0.95, "step": 0.05},
        "controllerDeadzone": {"min": 0.0,  "max": 0.9,  "step": 0.01},
    },

    # ── Farben, Abstaende, Schriftgroessen (frueher qml/Theme.qml) ────────
    #  Die Helligkeitsvariante ist bewusst kein blosses Invertieren: auf
    #  einem 13"-Display in der Sonne braucht man kraeftigere Kontraste und
    #  dunklere Akzentfarben, damit die Kurvenfarben auf Weiss lesbar
    #  bleiben.
    "theme": {
        "fontMono": "monospace",
        # Kleinste Kantenlaenge einer Schaltflaeche in Pixeln, bevor
        # fontScale daraufkommt. 48 px ist die uebliche Untergrenze fuer
        # eine Fingerkuppe.
        "touchTargetMin": 48,
        "spacing": {"xs": 4, "s": 8, "m": 16, "l": 24},
        "radius": {"s": 4, "m": 8, "l": 14},
        "fontSize": {"small": 13, "table": 16, "base": 15,
                     "large": 20, "xlarge": 24},
        "colors": {
            "dark": {
                "bg": "#1e1e1e", "bgMid": "#2d2d30", "bgAlt": "#37393a",
                "bgInput": "#3c3f41", "text": "#d4d4d4",
                "textjulius": "#a5dc6e", "textDim": "#969696",
                "highlight": "#0078d7", "accentBlue": "#9cdcfe",
                "accentGreen": "#4ec9b0", "accentRed": "#f48771",
                "accentAmber": "#f0c060", "border": "#444444",
                "ledOn": "#2ecc71", "ledOff": "#e74c3c",
                "warnBg": "#3a2f00", "errorBg": "#3a1f1f", "okBg": "#1f3a2a",
            },
            "light": {
                "bg": "#f2f3f5", "bgMid": "#e2e5e9", "bgAlt": "#d6dae0",
                "bgInput": "#ffffff", "text": "#1c1f23",
                "textjulius": "#2f6b12", "textDim": "#5a6169",
                "highlight": "#0a5ca8", "accentBlue": "#12608f",
                "accentGreen": "#0d7a63", "accentRed": "#b3271a",
                "accentAmber": "#9a6b00", "border": "#b6bcc4",
                "ledOn": "#1e8a4c", "ledOff": "#c0392b",
                "warnBg": "#fff2cc", "errorBg": "#ffe0dd", "okBg": "#dff3e6",
            },
        },
    },

    # ── Fenster (wirkt erst beim naechsten Start) ─────────────────────────
    "window": {
        "width": 1280,
        "height": 800,
        "fullscreen": True,             # 13-Zoll-Touchscreen im Kioskbetrieb
        "headerHeight": 72,             # vor fontScale
        "nodeSelectorWidth": 360,
        "namesButtonWidth": 150,
        "statusMessageSeconds": 6.0,    # so lange steht eine Meldung in der Fusszeile
        "alarmBlinkMs": 500,            # Blinktakt des Akku-Alarmrahmens
    },

    # ── Plotter ───────────────────────────────────────────────────────────
    "plotter": {
        # Ringpuffer = historySeconds * sampleRate Spalten je Kurve.
        "historySeconds": 10,
        "sampleRate": 100,              # erwartete Pakete/s vom Teensy
        "defaultPoints": 500,           # sichtbare Breite beim Start
        # Mehr Kurven werden unlesbar, und der Ringpuffer ist mit dieser
        # Zahl fest dimensioniert (8 x 1000 x 4 B = 32 kB).
        "maxCurves": 8,
        # Gut unterscheidbar auch auf hellem Hintergrund im Freien.
        "curveColors": [
            "#00d4ff", "#f0a500", "#4ec9b0", "#f48771",
            "#c586c0", "#9cdcfe", "#b5cea8", "#ffd700",
        ],
        # Senkrechte Marken (Ereignisse/Trigger) nach Stufe 0/1/2.
        # Schreibweise #aarrggbb — die Marken sind bewusst halbdurchsichtig.
        "markerColors": ["#a078c8ff", "#c8ffbe3c", "#dcff5a46"],

        # ── Performance / Überlastung ──────────────────────────────────────
        # Redraw ist auf maxFps gedeckelt (unabhängig von Daten-Bursts).
        # Bei anhaltender Überlastung (Event-Loop-Staulast) schaltet der
        # Plotter ab und zeigt einen Hinweis, statt die GUI einzufrieren.
        #
        # Das Rastern der Kurven (pyqtgraph zeichnet Gitter, Achsen und alle
        # Polylinien neu) macht rund 95 % der Plotter-Last aus — nicht die
        # Datenaufbereitung. Der Bildtakt ist damit der wirksamste Hebel
        # ueberhaupt: 12 statt 20 fps sind gut 40 % weniger Rechenlast, und
        # ein Trendverlauf laeuft damit immer noch fluessig. Wer die
        # Leistung hat, stellt hier wieder 20 (oder mehr) ein.
        "maxFps": 12,
        # Takt, wenn der Plotter nichts zu tun hat (anderer Tab, abgeschaltet).
        # Er sieht dann nur nach, ob er wieder zeichnen darf.
        "idleFps": 4,
        # Wie oft Statistikzeile und Legende neu gerechnet werden. Das
        # Signal baut den Legenden-Repeater in QML komplett neu auf — im
        # vollen Datentakt (20 Hz) der teuerste Posten des Plotters, und
        # lesbar ist das ohnehin nicht. 0 = bei jedem Paket (wie früher).
        "statsIntervalMs": 200,
        # pyqtgraph: Downsampling (auto) und Antialiasing — beide primär
        # für die Zeichen-Performance auf dem RPi 4 (2 GB).
        "downsample": True,
        "antialias": False,
        # Wächter-Schwellen (siehe bridge/perf_watchdog.py):
        #   measureMs       Takt des Wächter-Timers
        #   warnStallMs    Staulast ab der gewarnt wird (Plotter läuft noch)
        #   disableStallMs Staulast ab der die Abschaltung gezählt wird
        #   perfStreak      wie oft disableStallMs hintereinander nötig ist
        #   renderDisableMs einzelner Plot-Durchlauf, der das Budget sprengt
        "perfMeasureMs": 250,
        "perfWarnStallMs": 35.0,
        "perfDisableStallMs": 80.0,
        "perfStreak": 5,
        "renderDisableMs": 80.0,
    },

    # ── Parameter-Tab ─────────────────────────────────────────────────────
    "params": {
        "undoDepth": 50,
        # Aenderungen am selben Parameter innerhalb dieser Zeit werden zu
        # EINEM Undo-Schritt zusammengefasst — sonst braucht ein einziger
        # Reglerzug 40 Mal Strg+Z.
        "undoCoalesceSeconds": 1.5,
        # Die QML-SpinBox rechnet nur in ganzen Zahlen; der Parameterwert
        # wird deshalb mit diesem Faktor multipliziert dargestellt.
        "spinBoxFactor": 1000,
    },

    # ── Netzwerk und Zeitverhalten (wirkt erst beim naechsten Start) ──────
    #  Nicht dabei: Ports, Magic-Zahlen und Paketgroessen. Die sind kein
    #  Geschmack, sondern muessen zur Firmware passen (siehe config.py) —
    #  eine falsche Zahl dort macht die GUI wortlos taub.
    "network": {
        "rpi5Ip": "127.0.0.1",
        "node1Ip": "192.168.42.11",
        "node2Ip": "192.168.42.12",
        # Auf Windows (Entwicklungsrechner) statt der Node-Adressen
        # 127.0.0.1 benutzen, damit --simulate ohne Umkonfigurieren laeuft.
        "loopbackOnWindows": True,
        "guiFps": 20,                   # Poll-Takt der Oberflaeche
        "nodeTimeoutSeconds": 1.5,      # danach gilt ein Node als getrennt
        "recvBufferBytes": 1048576,     # Kernel-Empfangspuffer je Socket
        "queueMaxSize": 300,            # dann wird das aelteste Paket verworfen
    },

    # ── Diagnose ──────────────────────────────────────────────────────────
    "diagnostics": {
        "eventLogMax": 500,             # so viele Zeilen haelt das Logbuch vor
    },

    # ── PS4-Controller (siehe bridge/controller_bridge.py) ────────────────
    #  Die Achsen-/Buttonnummern sind die von SDL gemeldeten Indizes.
    "controller": {
        "axis_left_x": 0,    # linker Stick links/rechts  -> fast_floats[0]
        "axis_left_y": 1,    # linker Stick hoch/runter   -> fast_floats[1]
        "axis_right_x": 2,   # rechter Stick links/rechts -> fast_floats[2]
        "axis_r2": 5,        # R2 (ruhend -1, voll +1)    -> fast_floats[3]
        "button_r1": 10,     # -> fast_floats[4] = Maximum solange gehalten
        "button_l1": 9,      # -> fast_floats[4] = Minimum solange gehalten
        "deadzone": 0.08,
        "uiNotifyMs": 40,    # 25 Hz Anzeige-Auffrischung (nicht der Sendetakt)
    },
}


# ══════════════════════════════════════════════════════════════════════════
#  Zusammenfuehren mit Typpruefung
# ══════════════════════════════════════════════════════════════════════════

def defaults() -> dict:
    """Eine unabhaengige Kopie der Standardwerte."""
    return copy.deepcopy(DEFAULTS)


def _merge_value(default: Any, value: Any, where: str) -> Any:
    """Einen einzelnen Wert uebernehmen, wenn er zum Standardwert passt.

    Der Typ des STANDARDWERTS bestimmt, was erlaubt ist — nicht der Typ in
    der Datei. JSON kennt nur Zahl/Text/Wahrheitswert/Liste/Objekt, und aus
    einer 1 wuerde sonst schnell ein bool oder aus einer 0.5 ein int.
    """
    if isinstance(default, dict):
        if not isinstance(value, dict):
            log.warning("settings: %s erwartet ein Objekt — Standardwert bleibt.", where)
            return copy.deepcopy(default)
        return _merge_dict(default, value, where)

    if isinstance(default, list):
        if not isinstance(value, list) or not value:
            log.warning("settings: %s erwartet eine nicht-leere Liste — "
                        "Standardwert bleibt.", where)
            return copy.deepcopy(default)
        proto = default[0]
        return [_merge_value(proto, item, f"{where}[{i}]")
                for i, item in enumerate(value)]

    # bool VOR int pruefen: bool ist in Python eine Unterklasse von int.
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        log.warning("settings: %s = %r ist kein Wahrheitswert — %r bleibt.",
                    where, value, default)
        return default

    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            log.warning("settings: %s = %r ist keine Zahl — %r bleibt.",
                        where, value, default)
            return default
        try:
            out = float(value)
        except (TypeError, ValueError):
            log.warning("settings: %s = %r ist keine Zahl — %r bleibt.",
                        where, value, default)
            return default
        if out != out or out in (float("inf"), float("-inf")):
            log.warning("settings: %s = %r ist keine endliche Zahl — %r bleibt.",
                        where, value, default)
            return default
        return int(out) if isinstance(default, int) else out

    if isinstance(default, str):
        if not isinstance(value, str):
            log.warning("settings: %s = %r ist kein Text — %r bleibt.",
                        where, value, default)
            return default
        # Farben sehen dem Auge aehnlich ("#ff0" vs "ff0"), Qt macht daraus
        # aber stillschweigend Schwarz. Lieber den Standardwert behalten.
        if _COLOR_RE.match(default) and not _COLOR_RE.match(value):
            log.warning("settings: %s = %r ist keine Farbe (#rgb/#rrggbb/"
                        "#aarrggbb) — %r bleibt.", where, value, default)
            return default
        return value

    return value


def _merge_dict(default: dict, user: dict, where: str = "") -> dict:
    out: dict[str, Any] = {}
    for key, dflt in default.items():
        sub = f"{where}.{key}" if where else key
        if key in user:
            out[key] = _merge_value(dflt, user[key], sub)
        else:
            out[key] = copy.deepcopy(dflt)
    # Unbekannte Schluessel bleiben erhalten: sie koennen aus einer neueren
    # Fassung stammen, und beim Speichern still zu verlieren, was jemand
    # eingetragen hat, waere die unangenehmere Ueberraschung.
    for key, value in user.items():
        if key not in default:
            log.warning("settings: unbekannter Schluessel %s — bleibt "
                        "unbenutzt erhalten.", f"{where}.{key}" if where else key)
            out[key] = value
    return out


def _fix_ranges(data: dict) -> None:
    """Unbrauchbare Bereiche auf den Standardwert zuruecksetzen.

    Ein Bereich mit max <= min macht jeden Regler unbedienbar, und step <= 0
    bringt die QML-SpinBox zum Stillstand (sie rechnet dann durch 0). Das
    faellt erst am Spielfeldrand auf — also hier abfangen.
    """
    ranges = data.get("ranges")
    if not isinstance(ranges, dict):
        data["ranges"] = copy.deepcopy(DEFAULTS["ranges"])
        return
    for name, dflt in DEFAULTS["ranges"].items():
        rng = ranges.get(name)
        if not isinstance(rng, dict):
            ranges[name] = copy.deepcopy(dflt)
            continue
        if rng.get("max", 0) <= rng.get("min", 0) or rng.get("step", 0) <= 0:
            log.warning("settings: ranges.%s ist unbrauchbar (%r) — "
                        "Standardwerte bleiben.", name, rng)
            ranges[name] = copy.deepcopy(dflt)


def _clamp_into_ranges(data: dict) -> None:
    """Werte, fuer die es einen Bereich gibt, auch wirklich hineinlegen.

    Sonst steht nach einer Handkorrektur "fontScale": 12 in der Datei, die
    Oberflaeche startet mit unbedienbar grosser Schrift, und der
    Schieberegler kann nicht mehr dorthin zurueck, wo er hergekommen ist.
    """
    ranges = data["ranges"]
    for value_path, range_name in (
        ("ui.fontScale", "fontScale"),
        ("battery.channel", "batteryChannel"),
        ("battery.hold_seconds", "batteryHoldSeconds"),
        ("controller.deadzone", "controllerDeadzone"),
    ):
        section, key = value_path.split(".")
        rng = ranges[range_name]
        current = data[section][key]
        fixed = min(rng["max"], max(rng["min"], current))
        if fixed != current:
            log.warning("settings: %s = %r liegt ausserhalb %s — auf %r begrenzt.",
                        value_path, current, [rng["min"], rng["max"]], fixed)
            data[section][key] = type(current)(fixed)


# ══════════════════════════════════════════════════════════════════════════
#  Lesen / Schreiben
# ══════════════════════════════════════════════════════════════════════════

def read_file(path: Path) -> dict | None:
    """Rohen Dateiinhalt lesen. Fehlt sie oder ist sie kaputt -> None."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("%s ist unlesbar (%s) — Standardwerte gelten.", path, exc)
        return None
    if not isinstance(raw, dict):
        log.warning("%s enthaelt kein Objekt — Standardwerte gelten.", path)
        return None
    return raw


def normalize(raw: dict | None) -> dict:
    """Rohdaten mit den Standardwerten zusammenfuehren und pruefen."""
    data = _merge_dict(DEFAULTS, raw or {})
    _fix_ranges(data)
    _clamp_into_ranges(data)
    return data


def load(path: Path | None = None) -> dict:
    """Einstellungen aus einer Datei laden (fehlertolerant, siehe Modulkopf)."""
    path = path or SETTINGS_PATH
    raw = read_file(path)
    data = normalize(raw)
    if raw is not None:
        log.info("Einstellungen aus %s geladen.", path)
    return data


def ensure_file() -> None:
    """Alles, was beim Start EINMAL passieren muss — und dabei schreibt.

    Bewusst eine eigene Funktion und nicht Teil von load(): config.py
    importiert app_settings, und config.py wird auch in den Empfaenger-
    Prozessen importiert (network_worker.py startet sie als eigene
    Prozesse). Wuerde schon der Import schreiben, taeten das beim ersten
    Start vier Prozesse gleichzeitig. Deshalb ruft nur main_qml.py das hier
    auf, und zwar bevor der erste Unterprozess entsteht.
    """
    # Beim allerersten Start (oder nach dem Loeschen) die Datei mit den
    # vollstaendigen Standardwerten anlegen. Sie steht bewusst NICHT im
    # Repository: sie wird zur Laufzeit beschrieben, und ein `git pull` soll
    # auf dem Pi nicht an lokal geaenderten Einstellungen scheitern (gleiche
    # Ueberlegung wie bei runtime_config/, siehe config.py). Dass sie hier
    # angelegt wird, macht sie trotzdem sofort von Hand editierbar — mit
    # jedem bekannten Schluessel darin.
    if not SETTINGS_PATH.exists() and save(SETTINGS):
        log.info("%s neu angelegt (Standardwerte).", SETTINGS_PATH)
    data = _take_over_legacy(SETTINGS)
    if data is not SETTINGS:
        replace(data)


def save(data: dict, path: Path | None = None) -> bool:
    """Atomar schreiben: erst .tmp, dann os.replace().

    Ohne das Zwischenfile hinterlaesst ein Stromausfall mitten im Schreiben
    eine halbe Datei — und die GUI startet beim naechsten Mal ohne
    Einstellungen (siehe runtime_config.save_json, gleiches Vorgehen).
    """
    path = path or SETTINGS_PATH
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.error("%s konnte nicht geschrieben werden: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _take_over_legacy(data: dict) -> dict:
    """Einmalige Uebernahme aus runtime_config/ui_settings.json.

    Auf einem eingerichteten Pi steckt dort der Stand des Bedieners
    (Schriftgroesse, Akku-Schwellen, Kiosk-Modus). Ohne diesen Schritt
    staende nach dem Update alles wieder auf Standard — und die
    Akku-Warnung eines Roboters ist nichts, was man beim ersten Spiel nach
    dem Update neu suchen moechte.

    Ausgeloest wird die Uebernahme davon, dass die ALTE Datei noch da ist,
    und nicht davon, dass settings.json fehlt: settings.json liegt mit den
    Standardwerten im Repository und ist nach einem `git pull` immer
    vorhanden — die Bedingung "settings.json fehlt" waere auf einem echten
    Geraet also nie erfuellt gewesen.

    Erst schreiben, dann umbenennen: schlaegt das Schreiben fehl, bleibt die
    alte Datei unangetastet liegen und der naechste Start versucht es
    erneut. Umbenannt statt geloescht, damit der alte Stand im Zweifel noch
    nachlesbar ist.
    """
    raw = read_file(LEGACY_UI_SETTINGS_PATH)
    if raw is None:
        return data

    legacy: dict[str, Any] = {"ui": {}, "battery": {}}
    for key in ("dark", "fontScale", "kiosk", "keyboardControl",
                "startTab", "autoApplyTeensyConfig"):
        if key in raw:
            legacy["ui"][key] = raw[key]
    if isinstance(raw.get("battery"), dict):
        legacy["battery"] = raw["battery"]

    # data ist bereits vollstaendig, taugt hier also als "Standardwert" —
    # damit gilt fuer die alten Werte dieselbe Typpruefung wie fuer alles
    # andere auch.
    merged = _merge_dict(data, legacy)
    _fix_ranges(merged)
    _clamp_into_ranges(merged)

    if not save(merged):
        return merged                # naechster Start versucht es erneut
    log.info("Einstellungen aus %s nach %s uebernommen (einmalige Umstellung).",
             LEGACY_UI_SETTINGS_PATH, SETTINGS_PATH)
    try:
        LEGACY_UI_SETTINGS_PATH.rename(
            LEGACY_UI_SETTINGS_PATH.with_suffix(".json.uebernommen"))
    except OSError as exc:
        log.warning("%s konnte nicht umbenannt werden (%s) — bleibt liegen.",
                    LEGACY_UI_SETTINGS_PATH, exc)
    return merged


# ══════════════════════════════════════════════════════════════════════════
#  Profile (settings.<Name>.json)
# ══════════════════════════════════════════════════════════════════════════

def valid_profile_name(name: str) -> bool:
    return bool(_PROFILE_NAME_RE.match(str(name).strip()))


def profile_path(name: str) -> Path | None:
    """Dateipfad eines Profils. None, wenn der Name kein Dateiname sein darf.

    Die Pruefung ist kein Zierrat: der Name kommt aus einem Textfeld der
    Oberflaeche und wuerde als "../../etwas" sonst ausserhalb des Ordners
    landen.
    """
    name = str(name).strip()
    if not valid_profile_name(name):
        return None
    return BASE_DIR / f"{PROFILE_PREFIX}{name}{PROFILE_SUFFIX}"


def list_profiles() -> list[str]:
    """Alle Profilnamen im Ordner, alphabetisch."""
    names = []
    for path in BASE_DIR.glob(f"{PROFILE_PREFIX}*{PROFILE_SUFFIX}"):
        name = path.name[len(PROFILE_PREFIX):-len(PROFILE_SUFFIX)]
        if valid_profile_name(name):
            names.append(name)
    return sorted(names, key=str.lower)


def save_profile(name: str, data: dict) -> bool:
    path = profile_path(name)
    if path is None:
        log.warning("Profilname %r ist nicht erlaubt (nur Buchstaben, Ziffern, "
                    "Leerzeichen, - und _).", name)
        return False
    return save(data, path)


def load_profile(name: str) -> dict | None:
    path = profile_path(name)
    if path is None:
        return None
    raw = read_file(path)
    if raw is None:
        return None
    return normalize(raw)


def delete_profile(name: str) -> bool:
    path = profile_path(name)
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        log.warning("%s konnte nicht geloescht werden: %s", path, exc)
        return False


# ══════════════════════════════════════════════════════════════════════════
#  Der aktive Stand
# ══════════════════════════════════════════════════════════════════════════
#  SETTINGS wird beim Wechsel des Profils AN ORT UND STELLE geaendert
#  (clear + update) statt neu gebunden. Wer sich das Objekt einmal geholt
#  hat (`from app_settings import SETTINGS`), saehe sonst weiter den alten
#  Stand.
SETTINGS: dict[str, Any] = load()


def replace(data: dict) -> None:
    """Den aktiven Stand ersetzen, ohne die Objekt-Identitaet zu verlieren."""
    SETTINGS.clear()
    SETTINGS.update(copy.deepcopy(data))


def get(dotted: str, default: Any = None) -> Any:
    """Wert ueber einen Pfad lesen: get("theme.spacing.m") -> 16.

    Fuer die Modulebene gedacht (config.py), wo ein fehlender Schluessel
    keinen Absturz beim IMPORT ausloesen darf.
    """
    node: Any = SETTINGS
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
