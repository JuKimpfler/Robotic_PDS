"""
bridge/utils.py — kleine, GUI-unabhängige Hilfsfunktionen
=============================================================
"""
from __future__ import annotations

import functools
import logging
from time import monotonic
from typing import List

log = logging.getLogger("bridge.utils")

# Wie oft dieselbe Fehlerstelle höchstens geloggt wird (siehe safe_slot).
_ERROR_LOG_INTERVAL_S = 5.0
_last_error_log: dict[str, float] = {}


def safe_slot(func):
    """Fängt jede Ausnahme in einem Qt-Slot ab und loggt sie ratenbegrenzt.

    WARUM DAS SEIN MUSS: PyQt ruft bei einer unbehandelten Python-Ausnahme in
    einem Slot `qFatal()` auf — der Prozess bricht damit sofort ab, ohne
    Aufräumen und ohne dass am Roboter jemand den Grund sieht. Ein einzelnes
    unerwartetes Paket oder eine kaputte JSON-Datei würde also die komplette
    Oberfläche mitten im Wettkampf beenden.

    Für periodisch aufgerufene Slots (Poll-Timer, 100-Hz-Sendetimer) ist
    "Fehler loggen und beim nächsten Tick weitermachen" fast immer das
    richtige Verhalten: der nächste Aufruf kommt in Millisekunden.

    Ratenbegrenzt, damit ein dauerhaft auftretender Fehler nicht 100 Zeilen
    pro Sekunde ins Log schreibt.
    """
    key = f"{getattr(func, '__module__', '?')}.{getattr(func, '__qualname__', func)}"

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:                       # noqa: BLE001 — bewusst breit
            now = monotonic()
            if now - _last_error_log.get(key, 0.0) >= _ERROR_LOG_INTERVAL_S:
                _last_error_log[key] = now
                log.exception("Unbehandelter Fehler in %s — wird übersprungen.", key)
            return None

    return wrapper


def parse_channels(channel_spec) -> List[int]:
    """
    Wandelt eine Kanal-Spezifikation aus visuals_overlays.json in eine
    Liste von Kanal-Indizes um. Unterstützt:
      - einzelne Ints:            5
      - Listen von Ints/Strings:  [1, 2, "5-8"]
      - Bereichs-Strings:         "0-9", "3,5,7-9"

    1:1 portiert aus gui/tab_visuals.py, damit visuals_overlays.json
    unverändert weiterverwendet werden kann.
    """
    if isinstance(channel_spec, int):
        return [channel_spec]
    if isinstance(channel_spec, list):
        result: List[int] = []
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


# ══════════════════════════════════════════════════════════════════════════
#  Overlay-Typ "textgrid": ein Eintrag -> viele Textfelder
# ══════════════════════════════════════════════════════════════════════════

def _num(value, fallback: float) -> float:
    """Zahl aus einem Roheintrag, mit Rueckfall statt Ausnahme (die Eintraege
    kommen aus einer von Hand editierbaren Datei bzw. vom Teensy)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if out != out or out in (float("inf"), float("-inf")) else out


def text_style(entry: dict, channel: int) -> dict:
    """Darstellung EINER Textbox — gemeinsam fuer "text", "textgrid",
    "textring" und "textpts", damit alle vier dieselben Moeglichkeiten haben
    und SystemView.qml nur EINE Art von Zelle kennen muss.

      color            feste Farbe (Rand/Schrift)
      color_dynamic…   Box faerbt sich nach einem Kanalwert (siehe
                       overlay_schema._color_dynamic_fields)
      decimals         Nachkommastellen des Wertes (Default 2, wie bisher)
      font_px          Schriftgroesse; 0 = die feste Standardgroesse. Ein Wert
                       > 0 gilt bei 800 px Bildbreite und waechst/schrumpft
                       mit dem Bild — 50 Werte auf einem Ring ueberlappen
                       sich sonst auf einem kleinen Fenster.
      centered         True: x/y ist die MITTE der Box statt der linken
                       oberen Ecke. Noetig, wenn die Box genau auf einem
                       Bauteil sitzen soll, egal wie breit der Text wird.
    """
    color_channel = int(_num(entry.get("color_channel"), -1))
    return {
        "color": entry.get("color", "#4ec9b0"),
        "colorDynamic": bool(entry.get("color_dynamic", False)),
        "colorMode": str(entry.get("color_mode", "linear")),
        # kein Kanal gewaehlt (-1) -> jede Zelle faerbt sich nach IHREM Kanal
        "colorChannel": color_channel if color_channel >= 0 else channel,
        "colorMin": _num(entry.get("color_min"), 0.0),
        "colorMax": _num(entry.get("color_max"), 1.0),
        "colorThreshold": _num(entry.get("color_threshold"), 0.5),
        "colorLow": entry.get("color_low", "#a5dc6e"),
        "colorHigh": entry.get("color_high", "#e0524d"),
        "decimals": max(0, min(6, int(_num(entry.get("decimals"), 2)))),
        "fontPx": max(0.0, min(48.0, _num(entry.get("font_px"), 0.0))),
        "centered": bool(entry.get("centered", False)),
    }


def _cell_label(entry: dict, index: int, channel: int, name_for) -> str:
    """Beschriftung einer Zelle in einem Block (textring/textpts).

    "prefix" gesetzt -> Praefix + laufende Nummer ("IR" -> IR1, IR2, …; die
    Zaehlung beginnt bei "first", Default 1). Sonst wie beim Textraster der
    Kanalname, oder gar nichts bei labels = False.
    """
    if not bool(entry.get("labels", True)):
        return ""
    if "prefix" in entry:
        first = int(_num(entry.get("first"), 1))
        return f"{entry.get('prefix') or ''}{first + index}"
    return name_for(channel)


def parse_points(spec) -> List[tuple]:
    """Punktliste "x:y,x:y,…" (Prozent der Bildflaeche) -> [(x, y), …].

    Unlesbare Punkte werden uebersprungen statt die ganze Liste zu verwerfen —
    aber als (None, None) mitgezaehlt, damit die Zuordnung Punkt <-> Kanal
    der folgenden Eintraege nicht verrutscht.
    """
    out: List[tuple] = []
    if not isinstance(spec, str):
        return out
    for part in spec.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            xs, ys = part.split(":")
            out.append((float(xs), float(ys)))
        except ValueError:
            out.append((None, None))
    return out


def expand_textring(entry: dict, name_for) -> List[dict]:
    """Einen "textring"-Eintrag aufloesen: viele Werte gleichmaessig auf einem
    Kreis (oder einer Ellipse) — gedacht fuer ringfoermige Sensorplatinen.

      x_pct / y_pct   MITTELPUNKT des Rings in % der Bildflaeche
      r_pct           Radius in % der BildBREITE
      ry_pct          Radius senkrecht in % der BildHOEHE (0/fehlt = r_pct;
                      bei quadratischem Bild ergibt das einen Kreis)
      start_deg       Winkel des ersten Kanals, 0 = oben, positiv im
                      Uhrzeigersinn
      step_deg        Winkel zwischen zwei Kanaelen (0/fehlt = 360 / Anzahl;
                      negativ = gegen den Uhrzeigersinn)
    """
    import math

    channels = parse_channels(entry.get("channels", ""))
    if not channels:
        return []
    cx = _num(entry.get("x_pct"), 50.0)
    cy = _num(entry.get("y_pct"), 50.0)
    rx = _num(entry.get("r_pct"), 40.0)
    ry = _num(entry.get("ry_pct"), 0.0) or rx
    start = _num(entry.get("start_deg"), 0.0)
    step = _num(entry.get("step_deg"), 0.0) or 360.0 / len(channels)

    out: List[dict] = []
    for i, ch in enumerate(channels):
        ang = math.radians(start + i * step)
        cell = {
            "label": _cell_label(entry, i, ch, name_for),
            "channel": ch,
            "xPct": cx + rx * math.sin(ang),
            "yPct": cy - ry * math.cos(ang),
        }
        cell.update(text_style(entry, ch))
        # Auf einem Ring ist nur die Mitte der Box sinnvoll — linksbuendig
        # stuenden die Werte rechts weiter aussen als links.
        cell["centered"] = bool(entry.get("centered", True))
        out.append(cell)
    return out


def expand_textpts(entry: dict, name_for) -> List[dict]:
    """Einen "textpts"-Eintrag aufloesen: viele Werte an FREI vorgegebenen
    Punkten, aber als EIN Eintrag. Fuer Sensoren, die nicht auf einem Raster
    oder Kreis liegen (z. B. ein Ring mit geradem Stueck).

      channels   Kanalliste; der i-te Kanal gehoert zum i-ten Punkt
      points     "x:y,x:y,…" in % der Bildflaeche
      x_pct/y_pct  VERSATZ des ganzen Blocks (Default 0/0) — damit laesst
                 sich der Block im Editor als Ganzes verschieben.

    Kanaele ohne Punkt (Liste zu kurz oder Punkt unlesbar) entfallen.
    """
    channels = parse_channels(entry.get("channels", ""))
    points = parse_points(entry.get("points", ""))
    ox = _num(entry.get("x_pct"), 0.0)
    oy = _num(entry.get("y_pct"), 0.0)

    out: List[dict] = []
    for i, ch in enumerate(channels):
        if i >= len(points) or points[i][0] is None:
            continue
        cell = {
            "label": _cell_label(entry, i, ch, name_for),
            "channel": ch,
            "xPct": ox + points[i][0],
            "yPct": oy + points[i][1],
        }
        cell.update(text_style(entry, ch))
        cell["centered"] = bool(entry.get("centered", True))
        out.append(cell)
    return out


def expand_textgrid(entry: dict, name_for) -> List[dict]:
    """Einen "textgrid"-Eintrag in einzelne Text-Overlays aufloesen.

    Genau dafuer gedacht, dass man bei 30 Messwerten nicht 30 Overlays mit je
    eigener x/y-Position pflegen muss: angegeben wird nur die linke obere Ecke
    plus Spaltenzahl und Abstaende, den Rest rechnet diese Funktion aus.

    Bewusst hier und nicht in visuals_bridge.py: dort haengt alles an PyQt6,
    und diese reine Rechenfunktion soll in tools/selftest.py ohne GUI
    pruefbar bleiben.

    name_for: Callable[[int], str] — liefert den Anzeigenamen eines Kanals.
    """
    channels = parse_channels(entry.get("channels", ""))
    if not channels:
        return []
    cols = max(1, int(entry.get("cols", 1)))
    dx = float(entry.get("dx_pct", 20.0))
    dy = float(entry.get("dy_pct", 4.5))
    x0 = float(entry.get("x_pct", 4.0))
    y0 = float(entry.get("y_pct", 6.0))
    with_labels = bool(entry.get("labels", True))

    # Farbe, dynamische Farbe und Schrift gelten fuer den GANZEN Block gleich
    # — ein Eintrag, eine Einstellung (siehe text_style). Fehlt
    # "color_channel" (kein Kanal gewaehlt, -1), faerbt sich jede Zelle nach
    # IHREM EIGENEN angezeigten Kanal.
    out: List[dict] = []
    for i, ch in enumerate(channels):
        col, row = i % cols, i // cols
        cell = {
            "label": name_for(ch) if with_labels else "",
            "channel": ch,
            "xPct": x0 + col * dx,
            "yPct": y0 + row * dy,
        }
        cell.update(text_style(entry, ch))
        out.append(cell)
    return out
