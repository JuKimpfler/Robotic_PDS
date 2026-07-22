"""
bridge/utils.py — kleine, GUI-unabhängige Hilfsfunktionen
=============================================================
"""
from __future__ import annotations

from typing import List


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
