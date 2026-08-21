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
