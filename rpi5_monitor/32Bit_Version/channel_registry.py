"""
channel_registry.py — Kanal-/Param-Namen + Overlay-Zuordnung vom Teensy
==========================================================================
Der Teensy ist die Quelle für Anzeigenamen (200 Debug-Kanäle + 50 Slow-
Floats + 50 Slow-Bools + 5 Fast-Floats) und für die Overlay-Zuordnung
(welche Kanäle auf welchem Bild/Body-Objekt/Widget erscheinen) — gepflegt
in channel_config.h auf dem Teensy, siehe teensy_firmware/src/PDS.cpp für
den Sende-Mechanismus.

Wire-Format (siehe rpi_zero_node/spi_receiver.py::ChunkFrameAssembler):
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
import socket
import struct
import logging
import multiprocessing as mp
from dataclasses import dataclass, field

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
    param_slow_float_names: dict[int, str] = field(default_factory=dict)
    param_slow_bool_names:  dict[int, str] = field(default_factory=dict)
    param_fast_float_names: dict[int, str] = field(default_factory=dict)
    overlays:               list[dict]     = field(default_factory=list)
    received:               bool           = False

    @classmethod
    def from_json_dict(cls, data: dict) -> "ChannelRegistry":
        def _int_keyed(d: dict) -> dict[int, str]:
            return {int(k): v for k, v in d.items()}
        return cls(
            channel_names=_int_keyed(data.get("channels", {})),
            param_slow_float_names=_int_keyed(data.get("param_slow_floats", {})),
            param_slow_bool_names=_int_keyed(data.get("param_slow_bools", {})),
            param_fast_float_names=_int_keyed(data.get("param_fast_floats", {})),
            overlays=list(data.get("overlays", [])),
            received=True,
        )

    def name_for_channel(self, idx: int, fallback: str) -> str:
        return self.channel_names.get(idx, fallback)


# ══════════════════════════════════════════════════════════════════════════
#  UDP-Empfänger (eigener Prozess) — setzt Chunks zu vollständigem JSON zusammen
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

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)

    proc_log.info(f"Lauscht auf :{port}")

    chunks: dict[int, bytes] = {}
    expected_count: int | None = None

    while not stop_event.is_set():
        try:
            raw, _addr = sock.recvfrom(CHANNEL_DESC_HEADER_BYTES + 256)
        except socket.timeout:
            continue
        except OSError:
            break

        if len(raw) < CHANNEL_DESC_HEADER_BYTES or raw[:4] != _MAGIC_BYTES:
            continue

        chunk_idx, chunk_count, payload_len = raw[4], raw[5], raw[6]
        payload = raw[CHANNEL_DESC_HEADER_BYTES:CHANNEL_DESC_HEADER_BYTES + payload_len]
        if len(payload) != payload_len:
            continue

        # chunk_idx==0 markiert IMMER den Start eines (neuen oder erneuten)
        # Sendevorgangs -- alten Puffer verwerfen, auch bei identischem
        # chunk_count (z. B. erneute Anfrage mit unveraendertem Deskriptor).
        if chunk_idx == 0:
            chunks = {}
            expected_count = chunk_count

        chunks[chunk_idx] = payload

        if expected_count is not None and len(chunks) == expected_count:
            try:
                full_json = b"".join(chunks[i] for i in range(expected_count)).decode("utf-8")
                data = json.loads(full_json)
                out_queue.put_nowait(data)
            except (KeyError, ValueError, UnicodeDecodeError) as exc:
                proc_log.warning(f"Deskriptor-Parsing fehlgeschlagen: {exc}")
            chunks = {}
            expected_count = None

    sock.close()
    proc_log.info("Beendet.")


# ══════════════════════════════════════════════════════════════════════════
#  Request senden (GUI -> Pi Zero -> Teensy)
# ══════════════════════════════════════════════════════════════════════════

def send_descriptor_request(node_ip: str, port: int) -> None:
    """Schickt das 4-Byte-Anforderungspaket fire-and-forget an den Pi-Zero-Node."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(_REQUEST_BYTES, (node_ip, port))
        sock.close()
    except OSError as exc:
        log.warning("Deskriptor-Request an %s:%d fehlgeschlagen: %s", node_ip, port, exc)


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
                "diameter": float(kv.get(f"{prefix}_diameter", 0.3)),
                "channel_x": int(kv.get(f"{prefix}_channel_x", -1)),
                "channel_y": int(kv.get(f"{prefix}_channel_y", -1)),
                "channel_angle": int(kv.get(f"{prefix}_channel_angle", -1)),
                "channel_diameter": int(kv.get(f"{prefix}_channel_diameter", -1)),
            }

        return "graphics", {
            "type": "bodies",
            "label": label,
            "field_width": float(kv.get("field_width", 2.0)),
            "field_height": float(kv.get("field_height", 1.5)),
            "body1": _body("body1"),
            "body2": _body("body2"),
        }

    return "graphics", {"type": t, "label": label}


def apply_overlay_defaults(local_config: dict, registry: ChannelRegistry) -> bool:
    """
    Befüllt Gruppen aus local_config (visuals_overlays.json-Rohformat, siehe
    tab_visuals.py::load_config()/save_config()), deren 'overlays' UND
    'graphics' noch leer sind, aus registry.overlays. Bereits lokal befüllte
    Gruppen (manuell editiert oder früher schon gemerged) bleiben unangetastet.

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
        if group.get("overlays") or group.get("graphics"):
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
