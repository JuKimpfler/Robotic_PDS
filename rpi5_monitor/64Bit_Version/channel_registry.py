"""
channel_registry.py — Kanal-/Param-Namen + Overlay-Zuordnung vom Teensy
==========================================================================
Der Teensy ist die Quelle für Anzeigenamen (200 Debug-Kanäle + 50 Slow-
Floats + 50 Slow-Bools + 5 Fast-Floats) und für die Overlay-Zuordnung
(welche Kanäle auf welchem Bild/Body-Objekt/Widget erscheinen) — gepflegt
in channel_config.h auf dem Teensy, siehe teensy_firmware/src/PDS.cpp für
den Sende-Mechanismus.

Wire-Format (siehe rpi_zero_node/uart_receiver.py::ChunkFrameAssembler):
  [0..3] magic (CHANNEL_DESC_MAGIC) | [4] chunk_idx | [5] chunk_count |
  [6] payload_len | [7..] UTF-8-JSON-Fragment

Dieses Modul bündelt:
  1. descriptor_receiver_process() — UDP-Empfänger (eigener Prozess, wie
     network_worker.py::udp_receiver_process), setzt Chunks zu vollständigem
     JSON zusammen und legt das geparste dict in eine Queue.
  2. ChannelRegistry — Laufzeit-Zustand im GUI-Prozess (Namen + Overlays).
  3. send_descriptor_request() — 4-Byte-Anforderungspaket an den Teensy
     (über den Pi-Zero-Relay), für den "Kanalnamen anfordern"-Button.
  4. apply_overlay_defaults() — befüllt visuals_overlays.json-Gruppen, die
     noch leer sind, aus registry.overlays (überschreibt NIE bereits lokal
     editierte Gruppen).
"""
from __future__ import annotations

import json
import queue
import socket
import struct
import logging
import multiprocessing as mp
from dataclasses import dataclass, field
from time import monotonic

from config import (
    CHANNEL_DESC_MAGIC, CHANNEL_DESC_HEADER_BYTES,
    CHANNEL_DESC_REQUEST_MAGIC,
)

log = logging.getLogger(__name__)

_MAGIC_BYTES   = struct.pack("<I", CHANNEL_DESC_MAGIC)
_REQUEST_BYTES = struct.pack("<I", CHANNEL_DESC_REQUEST_MAGIC)


# ══════════════════════════════════════════════════════════════════════════
#  ChannelRegistry — Laufzeit-Zustand im GUI-Prozess
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ChannelRegistry:
    channel_names:          dict[int, str] = field(default_factory=dict)
    channel_units:          dict[int, str] = field(default_factory=dict)
    param_slow_float_names: dict[int, str] = field(default_factory=dict)
    param_slow_bool_names:  dict[int, str] = field(default_factory=dict)
    param_fast_float_names: dict[int, str] = field(default_factory=dict)
    overlays:               list[dict]     = field(default_factory=list)
    # Vollstaendige Widget-Konfiguration des Parameter-Tabs, so wie sie in
    # channel_config.h steht (siehe runtime_config.param_config_from_descriptor).
    param_cfg:              dict           = field(default_factory=dict)
    # {"pds": "2.1", "fw": "...", "build": "...", "wire": 2, "channels": 200}
    meta:                   dict           = field(default_factory=dict)
    received:               bool           = False

    @classmethod
    def from_json_dict(cls, data: dict) -> "ChannelRegistry":
        """Baut die Registry aus dem vom Teensy empfangenen JSON.

        Bewusst defensiv: der Inhalt kommt über eine unzuverlässige
        UART-/UDP-Strecke. Ein einzelner unplausibler Eintrag darf weder eine
        Exception im GUI-Poll-Timer auslösen noch den Rest verwerfen.
        """
        def _int_keyed(d) -> dict[int, str]:
            if not isinstance(d, dict):
                return {}
            out: dict[int, str] = {}
            for k, v in d.items():
                try:
                    idx = int(k)
                except (TypeError, ValueError):
                    continue
                if idx >= 0 and isinstance(v, str) and v:
                    out[idx] = v
            return out

        raw_overlays = data.get("overlays", [])
        overlays = [o for o in raw_overlays if isinstance(o, dict)] \
            if isinstance(raw_overlays, list) else []

        raw_meta = data.get("meta", {})
        meta = {k: v for k, v in raw_meta.items()
                if isinstance(k, str) and isinstance(v, (str, int, float, bool))} \
            if isinstance(raw_meta, dict) else {}

        raw_cfg = data.get("param_cfg", {})
        param_cfg = raw_cfg if isinstance(raw_cfg, dict) else {}

        return cls(
            channel_names=_int_keyed(data.get("channels", {})),
            channel_units=_int_keyed(data.get("units", {})),
            param_slow_float_names=_int_keyed(data.get("param_slow_floats", {})),
            param_slow_bool_names=_int_keyed(data.get("param_slow_bools", {})),
            param_fast_float_names=_int_keyed(data.get("param_fast_floats", {})),
            overlays=overlays,
            param_cfg=param_cfg,
            meta=meta,
            received=True,
        )

    def is_empty(self) -> bool:
        return not (self.channel_names or self.param_slow_float_names
                    or self.param_slow_bool_names or self.param_fast_float_names
                    or self.overlays or self.param_cfg)

    def firmware_label(self) -> str:
        """Kurztext fuer die Statuszeile, z. B. "fw 1.4.2 - PDS 2.1"."""
        parts = []
        if self.meta.get("fw"):
            parts.append(f"fw {self.meta['fw']}")
        if self.meta.get("pds"):
            parts.append(f"PDS {self.meta['pds']}")
        if self.meta.get("build"):
            parts.append(str(self.meta["build"]))
        return " - ".join(parts)

    def unit_for_channel(self, idx: int) -> str:
        return self.channel_units.get(idx, "")

    def name_for_channel(self, idx: int, fallback: str) -> str:
        return self.channel_names.get(idx, fallback)


# ══════════════════════════════════════════════════════════════════════════
#  DescriptorAssembler — Chunks -> vollständiges JSON
# ══════════════════════════════════════════════════════════════════════════
#  Bewusst als eigene, socket-freie Klasse: so ist die knifflige Logik
#  (Neustart mitten in der Übertragung, Einstieg ohne Chunk 0, Zufallstreffer
#  im Telemetriestrom) ohne Netzwerk testbar — siehe tools/selftest.py.

# Angefangene, aber nie beendete Übertragung nach dieser Zeit verwerfen.
DESCRIPTOR_ASSEMBLY_TIMEOUT_S = 5.0


class DescriptorAssembler:
    """Setzt Deskriptor-Chunks zu einem geparsten JSON-Objekt zusammen."""

    def __init__(self) -> None:
        self._chunks: dict[int, bytes] = {}
        self._expected: int | None = None
        self._started_at = 0.0
        self.rejected = 0        # unplausible/verwaiste Pakete
        self.completed = 0       # vollständig zusammengesetzte Deskriptoren

    @property
    def in_progress(self) -> bool:
        return self._expected is not None

    def reset(self) -> None:
        self._chunks = {}
        self._expected = None

    def check_timeout(self, now: float | None = None) -> bool:
        """True, wenn eine begonnene Übertragung abgelaufen ist (und verworfen
        wurde). Sonst würde ein abgebrochener Sendevorgang (Teensy-Reset mitten
        im Deskriptor) mit den Chunks des NÄCHSTEN Versuchs vermischt und ergäbe
        dauerhaft unlesbares JSON."""
        if self._expected is None:
            return False
        now = monotonic() if now is None else now
        if now - self._started_at <= DESCRIPTOR_ASSEMBLY_TIMEOUT_S:
            return False
        self.reset()
        return True

    def feed(self, raw: bytes, now: float | None = None) -> dict | None:
        """Ein UDP-Datagramm einspeisen. Gibt den fertigen Deskriptor zurück,
        sobald alle Chunks da sind — sonst None."""
        if len(raw) < CHANNEL_DESC_HEADER_BYTES or raw[:4] != _MAGIC_BYTES:
            return None

        chunk_idx, chunk_count, payload_len = raw[4], raw[5], raw[6]
        payload = raw[CHANNEL_DESC_HEADER_BYTES:CHANNEL_DESC_HEADER_BYTES + payload_len]
        if len(payload) != payload_len or chunk_count == 0 or chunk_idx >= chunk_count:
            self.rejected += 1
            return None   # unplausibler Header (z. B. Zufallstreffer im Telemetriestrom)

        # chunk_idx==0 markiert IMMER den Start eines (neuen oder erneuten)
        # Sendevorgangs -- alten Puffer verwerfen, auch bei identischem
        # chunk_count (z. B. erneute Anfrage mit unverändertem Deskriptor).
        if chunk_idx == 0:
            self._chunks = {}
            self._expected = chunk_count
            self._started_at = monotonic() if now is None else now
        elif self._expected is None:
            # Mitten in einen laufenden Sendevorgang eingestiegen (GUI später
            # gestartet als der Teensy): ohne Chunk 0 lässt sich das JSON nicht
            # zusammensetzen. Verwerfen statt Speicher anzusammeln — der Teensy
            # wiederholt den Deskriptor von allein (PDS_DESC_REPEAT_MS).
            self.rejected += 1
            return None
        elif chunk_count != self._expected:
            self.rejected += 1
            return None   # gehört zu einem anderen Sendevorgang

        self._chunks[chunk_idx] = payload
        if len(self._chunks) < self._expected:
            return None

        try:
            full_json = b"".join(self._chunks[i] for i in range(self._expected)).decode("utf-8")
            data = json.loads(full_json)
            if not isinstance(data, dict):
                raise ValueError("Deskriptor ist kein JSON-Objekt")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            log.warning("Deskriptor-Parsing fehlgeschlagen: %s", exc)
            self.reset()
            return None

        self.reset()
        self.completed += 1
        return data


# ══════════════════════════════════════════════════════════════════════════
#  UDP-Empfänger (eigener Prozess)
# ══════════════════════════════════════════════════════════════════════════

def descriptor_receiver_process(
    port: int,
    node_id: int,
    out_queue: mp.Queue,
    stop_event: mp.Event,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"[Desc-N{node_id}] %(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    proc_log = logging.getLogger()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(0.5)
    except OSError as exc:
        proc_log.error(f"UDP-Port {port} konnte nicht geöffnet werden: {exc}")
        return

    proc_log.info(f"Lauscht auf :{port}")
    assembler = DescriptorAssembler()

    while not stop_event.is_set():
        try:
            raw, _addr = sock.recvfrom(CHANNEL_DESC_HEADER_BYTES + 256)
        except socket.timeout:
            if assembler.check_timeout():
                proc_log.warning("Unvollständiger Deskriptor verworfen (Zeitüberschreitung).")
            continue
        except OSError:
            break

        data = assembler.feed(raw)
        if data is None:
            continue
        try:
            out_queue.put_nowait(data)
        except queue.Full:
            # GUI liest gerade nicht — der nächste Deskriptor kommt ohnehin
            # wieder; keinesfalls den Prozess sterben lassen.
            proc_log.warning("Deskriptor-Queue voll — Paket verworfen.")

    sock.close()
    proc_log.info("Beendet.")


# ══════════════════════════════════════════════════════════════════════════
#  Request senden (GUI -> Pi Zero -> Teensy)
# ══════════════════════════════════════════════════════════════════════════

def send_descriptor_request(node_ip: str, port: int) -> bool:
    """Schickt das 4-Byte-Anforderungspaket fire-and-forget an den Pi-Zero-Node.

    Gibt True zurück, wenn das Paket abgeschickt werden konnte. Der Socket
    wird über einen with-Block geschlossen — vorher blieb er bei einem Fehler
    in sendto() offen, was sich bei wiederholten Fehlversuchen zu einem
    Handle-Leck aufsummiert hat.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.sendto(_REQUEST_BYTES, (node_ip, port))
        return True
    except OSError as exc:
        log.warning("Deskriptor-Request an %s:%d fehlgeschlagen: %s", node_ip, port, exc)
        return False


# ══════════════════════════════════════════════════════════════════════════
#  Overlay-Defaults: registry.overlays -> visuals_overlays.json-Gruppen
# ══════════════════════════════════════════════════════════════════════════

def _parse_extra_kv(extra: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in extra.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _teensy_overlay_to_entry(ov: dict) -> tuple[str, dict]:
    """Wandelt einen vom Teensy empfangenen Overlay-Eintrag (siehe
    channel_config.h::OverlayDef) in einen visuals_overlays.json-kompatiblen
    Eintrag um. Gibt (Zielliste, Eintrag) zurueck -- Zielliste ist
    'overlays' (Text-Overlay auf dem Bild) oder 'graphics' (Gauge/Rotation/
    Vector/Table/Bodies-Widget)."""
    t = ov.get("type", "")
    label = ov.get("label", "")

    if t == "text":
        return "overlays", {
            "label": label,
            "channel_idx": int(ov.get("channel", 0)),
            "x_pct": float(ov.get("x_pct", 5.0)),
            "y_pct": float(ov.get("y_pct", 5.0)),
            "color": "#4ec9b0",
        }

    if t == "textgrid":
        # Ein einziger Eintrag erzeugt beliebig viele Textfelder — genau
        # dafuer gedacht, dass man bei 30 Messwerten nicht 30 Overlays mit
        # je eigener Position pflegen muss. Die Aufloesung in Einzelfelder
        # passiert erst in der GUI (visuals_bridge.expand_textgrid), damit
        # die gespeicherte Konfiguration kompakt und lesbar bleibt.
        kv = _parse_extra_kv(ov.get("extra", ""))
        return "overlays", {
            "type": "textgrid",
            "label": label,
            "channels": kv.get("channels", ""),
            "cols": int(float(kv.get("cols", 1))),
            "dx_pct": float(kv.get("dx", 20.0)),
            "dy_pct": float(kv.get("dy", 4.5)),
            "labels": kv.get("labels", "1") not in ("0", "false", "False"),
            "x_pct": float(ov.get("x_pct", 4.0)),
            "y_pct": float(ov.get("y_pct", 6.0)),
            "color": "#4ec9b0",
        }

    if t == "gauge":
        return "graphics", {
            "type": "gauge",
            "label": label,
            "channel": int(ov.get("channel", 0)),
            "min": float(ov.get("min", -1.0)),
            "max": float(ov.get("max", 1.0)),
        }

    if t == "rotation":
        entry = {"type": "rotation", "label": label, "channel": int(ov.get("channel", 0))}
        if "max" in ov:
            entry["max_val"] = float(ov["max"])
        return "graphics", entry

    if t == "vector":
        return "graphics", {
            "type": "vector",
            "label": label,
            "channel_angle": int(ov.get("channel", -1)),
            "channel_speed": int(ov.get("channel2", -1)),
            "max_val": float(ov.get("max", 1.0)),
        }

    if t == "table":
        return "graphics", {
            "type": "table",
            "title": label,
            "channels": ov.get("extra", ""),
        }

    if t == "bodies":
        kv = _parse_extra_kv(ov.get("extra", ""))

        def _body(prefix: str) -> dict:
            return {
                "label": kv.get(f"{prefix}_label", prefix),
                "color": kv.get(f"{prefix}_color", "#4ec9b0"),
                "diameter": float(kv.get(f"{prefix}_diameter", 18.0)),
                "channel_x": int(kv.get(f"{prefix}_channel_x", -1)),
                "channel_y": int(kv.get(f"{prefix}_channel_y", -1)),
                "channel_angle": int(kv.get(f"{prefix}_channel_angle", -1)),
                "channel_diameter": int(kv.get(f"{prefix}_channel_diameter", -1)),
            }

        # Feldmasse in ZENTIMETERN, im Feldkoordinatensystem:
        #   x = 0..field_x_cm nach Osten, y = 0..field_y_cm nach Norden.
        # Die Darstellung dreht das Feld um 90 Grad nach Osten (Querformat) —
        # siehe components/BodiesField.qml. field_width/field_height (Meter)
        # werden als Altformat weiterhin angenommen und umgerechnet.
        if "field_x_cm" in kv or "field_y_cm" in kv:
            field_x = float(kv.get("field_x_cm", 180.0))
            field_y = float(kv.get("field_y_cm", 240.0))
        else:
            field_x = float(kv.get("field_width", 1.8)) * 100.0
            field_y = float(kv.get("field_height", 2.4)) * 100.0

        return "graphics", {
            "type": "bodies",
            "label": label,
            "field_x_cm": field_x,
            "field_y_cm": field_y,
            "body1": _body("body1"),
            "body2": _body("body2"),
        }

    return "graphics", {"type": t, "label": label}


def apply_overlay_defaults(local_config: dict, registry: ChannelRegistry,
                           overwrite: bool = False) -> bool:
    """
    Übernimmt registry.overlays in local_config (visuals_overlays.json-
    Rohformat, siehe tab_visuals.py::load_config()/save_config()).

    overwrite=False (Standard): nur Gruppen befüllen, deren 'overlays' UND
    'graphics' noch leer sind. Bereits lokal befüllte Gruppen (manuell
    editiert oder früher schon gemerged) bleiben unangetastet.

    overwrite=True: auch befüllte Gruppen ersetzen. Wird genau dann benutzt,
    wenn sich der Fingerabdruck der Teensy-Overlays geändert hat — dann ist
    eine neue Firmware geflasht worden und ihre Anordnung ist die gewollte
    (siehe runtime_config.py, Abschnitt "Wer gewinnt bei einem Konflikt?").

    Gibt True zurück, wenn mindestens eine Gruppe verändert wurde (Aufrufer
    ist dann für save_config() zuständig).
    """
    if not registry.overlays:
        return False

    by_group: dict[int, list[dict]] = {}
    for ov in registry.overlays:
        by_group.setdefault(int(ov.get("group", 1)), []).append(ov)

    changed = False
    for group in local_config.get("groups", []):
        if not overwrite and (group.get("overlays") or group.get("graphics")):
            continue   # bereits befuellt -- nicht ueberschreiben

        entries = by_group.get(int(group.get("image_idx", 1)))
        if not entries:
            continue

        overlays: list[dict] = []
        graphics: list[dict] = []
        for ov in entries:
            target, entry = _teensy_overlay_to_entry(ov)
            (overlays if target == "overlays" else graphics).append(entry)

        group["overlays"] = overlays
        group["graphics"] = graphics
        changed = True

    return changed
