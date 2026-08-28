"""
aux_receiver.py — Aux-Uplink des Nodes (Ereignisse, Param-Ack, Node-Status)
============================================================================
Der Pi-Zero-Node buendelt drei kleine Uplink-Pakettypen auf EINEM UDP-Port
(5021/5022) und unterscheidet sie nur am Magic. Dieses Modul enthaelt

  1. `parse_aux_packet()` — reines Byte-Parsing, ohne Socket und ohne Qt,
     damit es in tools/selftest.py ohne Hardware pruefbar ist,
  2. `aux_receiver_process()` — den zugehoerigen Empfaengerprozess
     (analog zu network_worker.py::udp_receiver_process).

Wire-Format siehe teensy_firmware/src/params.h und
rpi_zero_node/uart_receiver.py — die drei Formate im Ueberblick:

  Ereignis/Log  0xE7E5C0DE  16..64 B   PDS.event()/PDS.log() vom Teensy
  Param-Ack     0xACC0FEED     290 B   was der Teensy wirklich haelt, 2 Hz
  Node-Status   0x0DE57A75      40 B   CPU/WLAN/Uptime des Pi Zero, 1 Hz
"""
from __future__ import annotations

import queue
import socket
import struct
import logging
import multiprocessing as mp

from config import (
    PDS_EVENT_MAGIC, PDS_EVENT_HEADER_BYTES, PDS_EVENT_TEXT_MAX,
    PARAM_ACK_MAGIC, PARAM_ACK_HEADER_BYTES, PARAM_ACK_PACKET_BYTES,
    PARAM_SLOW_FLOAT_COUNT, PARAM_SLOW_BOOL_COUNT, PARAM_FAST_FLOAT_COUNT,
    NODE_STATUS_MAGIC, NODE_STATUS_STRUCT, NODE_STATUS_PACKET_BYTES,
    NODE_STATUS_FLAG_TEENSY, NODE_STATUS_FLAG_WIFI, NODE_STATUS_FLAG_UNICAST,
)

log = logging.getLogger(__name__)

_EVENT_MAGIC_BYTES  = struct.pack("<I", PDS_EVENT_MAGIC)
_ACK_MAGIC_BYTES    = struct.pack("<I", PARAM_ACK_MAGIC)
_STATUS_MAGIC_BYTES = struct.pack("<I", NODE_STATUS_MAGIC)

_ACK_FLOATS = struct.Struct(f"<{PARAM_SLOW_FLOAT_COUNT}f")
_ACK_FAST   = struct.Struct(f"<{PARAM_FAST_FLOAT_COUNT}f")
_STATUS     = struct.Struct(NODE_STATUS_STRUCT)


def parse_aux_packet(raw: bytes) -> tuple[str, dict] | None:
    """Ein Aux-Datagramm in (Art, Werte) zerlegen.

    Gibt None zurueck, wenn das Paket nicht zu einem der drei bekannten
    Formate passt — der Aufrufer zaehlt es dann als ungueltig. Bewusst
    streng: die Pakete stammen aus einem Bytestrom, in dem ein Magic auch
    zufaellig auftreten kann (siehe MagicFrameAssembler im Node).
    """
    if len(raw) < 4:
        return None
    magic = raw[:4]

    # ── Ereignis / Logzeile ───────────────────────────────────────────────
    if magic == _EVENT_MAGIC_BYTES:
        if len(raw) < PDS_EVENT_HEADER_BYTES:
            return None
        ts_us, value = struct.unpack_from("<If", raw, 4)
        kind, level, text_len, reserved = raw[12], raw[13], raw[14], raw[15]
        if kind > 1 or level > 2 or reserved != 0 or text_len > PDS_EVENT_TEXT_MAX:
            return None
        if len(raw) < PDS_EVENT_HEADER_BYTES + text_len:
            return None
        text = raw[PDS_EVENT_HEADER_BYTES:PDS_EVENT_HEADER_BYTES + text_len]
        return "event", {
            "ts_us": ts_us,
            "value": value,
            "kind": kind,
            "level": level,
            # errors="replace": eine zerhackte UTF-8-Sequenz darf niemals eine
            # Exception im Empfaengerprozess ausloesen.
            "text": text.decode("utf-8", errors="replace"),
        }

    # ── Parameter-Rueckmeldung ────────────────────────────────────────────
    if magic == _ACK_MAGIC_BYTES:
        if len(raw) != PARAM_ACK_PACKET_BYTES:
            return None
        slow_seq, fast_seq, slow_age, fast_age = struct.unpack_from("<IIII", raw, 4)
        off = PARAM_ACK_HEADER_BYTES
        floats = _ACK_FLOATS.unpack_from(raw, off)
        off += _ACK_FLOATS.size
        bools = tuple(b != 0 for b in raw[off:off + PARAM_SLOW_BOOL_COUNT])
        off += PARAM_SLOW_BOOL_COUNT
        fast = _ACK_FAST.unpack_from(raw, off)
        return "ack", {
            "slow_seq": slow_seq,
            "fast_seq": fast_seq,
            # 0xFFFFFFFF heisst "noch nie empfangen" (siehe params.h)
            "slow_age_ms": None if slow_age == 0xFFFF_FFFF else slow_age,
            "fast_age_ms": None if fast_age == 0xFFFF_FFFF else fast_age,
            "floats": floats,
            "bools": bools,
            "fast_floats": fast,
        }

    # ── Systemzustand des Nodes ───────────────────────────────────────────
    if magic == _STATUS_MAGIC_BYTES:
        if len(raw) != NODE_STATUS_PACKET_BYTES:
            return None
        (_m, node_id, flags, _rsv, cpu_temp, load1, mem_pct, rssi,
         uptime_s, uart_pkts, sync_losses, udp_tx) = _STATUS.unpack(raw)
        return "status", {
            "node_id": node_id,
            "teensy_link": bool(flags & NODE_STATUS_FLAG_TEENSY),
            "wifi_ok": bool(flags & NODE_STATUS_FLAG_WIFI),
            "unicast": bool(flags & NODE_STATUS_FLAG_UNICAST),
            "cpu_temp_c": cpu_temp,
            "load1": load1,
            "mem_used_pct": mem_pct,
            "wifi_rssi_dbm": rssi,
            "uptime_s": uptime_s,
            "uart_packets": uart_pkts,
            "sync_losses": sync_losses,
            "udp_tx": udp_tx,
        }

    return None


def aux_receiver_process(
    port: int,
    node_id: int,
    out_queue: "mp.Queue",
    stop_event,
) -> None:
    """UDP-Empfaenger fuer den Aux-Port eines Nodes (eigener Prozess)."""
    logging.basicConfig(
        level=logging.INFO,
        format=f"[Aux-N{node_id}] %(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    proc_log = logging.getLogger()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(0.5)
    except OSError as exc:
        proc_log.error("UDP-Port %d konnte nicht geoeffnet werden: %s", port, exc)
        return

    proc_log.info("Lauscht auf :%d", port)
    ok = bad = dropped = 0

    while not stop_event.is_set():
        try:
            raw, _addr = sock.recvfrom(PARAM_ACK_PACKET_BYTES + 128)
        except socket.timeout:
            continue
        except OSError:
            break

        parsed = parse_aux_packet(raw)
        if parsed is None:
            bad += 1
            continue
        kind, data = parsed
        try:
            out_queue.put_nowait((node_id, kind, data))
            ok += 1
        except queue.Full:
            dropped += 1
        except Exception:                       # noqa: BLE001
            break   # Queue beim Herunterfahren geschlossen

    sock.close()
    proc_log.info("Beendet | OK=%d | Ungueltig=%d | Verworfen=%d", ok, bad, dropped)
