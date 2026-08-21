#!/usr/bin/env python3
"""
tools/check_wire_format.py — prueft die drei Seiten des Wire-Formats
=======================================================================
Magic-Werte, Paketgroessen, Kanalzahl und Baudrate stehen an DREI Stellen
und muessen exakt uebereinstimmen:

    teensy_firmware/src/params.h  +  PDS.cpp     (Teensy)
    rpi_zero_node/uart_receiver.py               (Node)
    rpi5_monitor/64Bit_Version/config.py         (GUI)

Weichen sie voneinander ab, verwirft der Node jedes Paket stillschweigend
als Groessen-Mismatch — der haeufigste und am schwersten zu findende Fehler
in diesem Projekt. Genau dagegen ist dieses Skript da.

Aufruf (keine Abhaengigkeiten, laeuft ueberall):
    python tools/check_wire_format.py
Exit-Code 0 = alles konsistent, 1 = Abweichung gefunden.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PARAMS_H  = ROOT / "teensy_firmware" / "src" / "params.h"
PDS_CPP   = ROOT / "teensy_firmware" / "src" / "PDS.cpp"
NODE_PY   = ROOT / "rpi_zero_node" / "uart_receiver.py"
CONFIG_PY = ROOT / "rpi5_monitor" / "64Bit_Version" / "config.py"


def _read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"[FEHLER] Datei fehlt: {path}")
    return path.read_text(encoding="utf-8")


def _num(text: str, pattern: str, source: str) -> int:
    """Erste Zahl hinter `pattern` (Regex mit genau einer Gruppe) holen.
    Unterstuetzt Dezimal, Hex und C++-/Python-Zifferntrenner (1'000'000 / 1_000_000).
    """
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        raise SystemExit(f"[FEHLER] '{pattern}' nicht gefunden in {source}")
    raw = m.group(1).replace("'", "").replace("_", "").strip()
    return int(raw, 16) if raw.lower().startswith("0x") else int(raw)


def collect() -> dict[str, dict[str, int]]:
    params, pds = _read(PARAMS_H), _read(PDS_CPP)
    node, cfg = _read(NODE_PY), _read(CONFIG_PY)

    teensy = {
        "MAX_FLOATS":              _num(pds,    r"MAX_FLOATS\s*=\s*([0-9']+)", "PDS.cpp"),
        "HEADER_SIZE":             8,   # Magic(4) + micros(4), fest im Format
        "PARAM_SLOW_MAGIC":        _num(params, r"PARAM_SLOW_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "params.h"),
        "PARAM_SLOW_FLOAT_COUNT":  _num(params, r"PARAM_SLOW_FLOAT_COUNT\s*=\s*([0-9']+)", "params.h"),
        "PARAM_SLOW_BOOL_COUNT":   _num(params, r"PARAM_SLOW_BOOL_COUNT\s*=\s*([0-9']+)", "params.h"),
        "PARAM_HEADER_BYTES":      _num(params, r"PARAM_HEADER_BYTES\s*=\s*([0-9']+)", "params.h"),
        "PARAM_FAST_MAGIC":        _num(params, r"PARAM_FAST_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "params.h"),
        "PARAM_FAST_FLOAT_COUNT":  _num(params, r"PARAM_FAST_FLOAT_COUNT\s*=\s*([0-9']+)", "params.h"),
        "CHANNEL_DESC_MAGIC":      _num(params, r"CHANNEL_DESC_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "params.h"),
        "CHANNEL_DESC_REQUEST_MAGIC": _num(params, r"CHANNEL_DESC_REQUEST_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "params.h"),
        "CHANNEL_DESC_HEADER_BYTES": _num(params, r"CHANNEL_DESC_CHUNK_HEADER_BYTES\s*=\s*([0-9']+)", "params.h"),
        "CHANNEL_DESC_CHUNK_PAYLOAD_MAX": _num(params, r"CHANNEL_DESC_CHUNK_PAYLOAD_MAX\s*=\s*([0-9']+)", "params.h"),
        "BAUD":                    _num(params, r"UART_DBG_BAUD\s*=\s*([0-9']+)", "params.h"),
        "PACKET_HEADER_MAGIC":     _num(pds,    r"HEADER_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "PDS.cpp"),
        "WIRE_VERSION":            _num(params, r"#define\s+PDS_WIRE_VERSION\s+([0-9]+)", "params.h"),
        "PDS_EVENT_MAGIC":         _num(params, r"PDS_EVENT_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "params.h"),
        "PDS_EVENT_HEADER_BYTES":  _num(params, r"PDS_EVENT_HEADER_BYTES\s*=\s*([0-9']+)", "params.h"),
        "PDS_EVENT_TEXT_MAX":      _num(params, r"PDS_EVENT_TEXT_MAX\s*=\s*([0-9']+)", "params.h"),
        "PARAM_ACK_MAGIC":         _num(params, r"PARAM_ACK_MAGIC\s*=\s*(0x[0-9A-Fa-f']+)", "params.h"),
        "PARAM_ACK_HEADER_BYTES":  _num(params, r"PARAM_ACK_HEADER_BYTES\s*=\s*([0-9']+)", "params.h"),
    }

    node_vals = {
        "MAX_FLOATS":              _num(node, r"^MAX_FLOATS\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "HEADER_SIZE":             _num(node, r"^HEADER_SIZE\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PARAM_SLOW_MAGIC":        _num(node, r"^PARAM_SLOW_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "PARAM_SLOW_FLOAT_COUNT":  _num(node, r"^PARAM_SLOW_FLOAT_COUNT\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PARAM_SLOW_BOOL_COUNT":   _num(node, r"^PARAM_SLOW_BOOL_COUNT\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PARAM_HEADER_BYTES":      _num(node, r"^HEADER_SIZE\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PARAM_FAST_MAGIC":        _num(node, r"^PARAM_FAST_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "PARAM_FAST_FLOAT_COUNT":  _num(node, r"^PARAM_FAST_FLOAT_COUNT\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "CHANNEL_DESC_MAGIC":      _num(node, r"^CHANNEL_DESC_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "CHANNEL_DESC_REQUEST_MAGIC": _num(node, r"^CHANNEL_DESC_REQUEST_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "CHANNEL_DESC_HEADER_BYTES": _num(node, r"^CHANNEL_DESC_HEADER_BYTES\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "CHANNEL_DESC_CHUNK_PAYLOAD_MAX": _num(node, r"^CHANNEL_DESC_CHUNK_PAYLOAD_MAX\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "BAUD":                    _num(node, r"^UART_BAUD\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PACKET_HEADER_MAGIC":     _num(node, r"^MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "DISCOVERY_MAGIC":         _num(node, r"^DISCOVERY_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "DISCOVERY_PACKET_BYTES":  _num(node, r"^DISCOVERY_PACKET_BYTES\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "DISCOVERY_ECHO_MAGIC":    _num(node, r"^DISCOVERY_ECHO_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "DISCOVERY_ECHO_PACKET_BYTES": _num(node, r"^DISCOVERY_ECHO_PACKET_BYTES\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PDS_EVENT_MAGIC":         _num(node, r"^PDS_EVENT_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "PDS_EVENT_HEADER_BYTES":  _num(node, r"^PDS_EVENT_HEADER_BYTES\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PDS_EVENT_TEXT_MAX":      _num(node, r"^PDS_EVENT_TEXT_MAX\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "PARAM_ACK_MAGIC":         _num(node, r"^PARAM_ACK_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        "PARAM_ACK_HEADER_BYTES":  _num(node, r"^PARAM_ACK_HEADER_BYTES\s*=\s*([0-9_]+)", "uart_receiver.py"),
        "NODE_STATUS_MAGIC":       _num(node, r"^NODE_STATUS_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "uart_receiver.py"),
        # Der Node rechnet UDP_AUX_PORT = 5020 + NODE_ID, die GUI hat feste
        # Ports je Node. Verglichen wird deshalb der Port von Node 1.
        "AUX_PORT_NODE1":          _num(node, r"^UDP_AUX_PORT\s*=\s*([0-9_]+)", "uart_receiver.py") + 1,
        "WIRE_VERSION":            _num(node, r"^PDS_WIRE_VERSION\s*=\s*([0-9_]+)", "uart_receiver.py"),
    }

    gui = {
        "MAX_FLOATS":              _num(cfg, r"^MAX_FLOATS\s*=\s*([0-9_]+)", "config.py"),
        "HEADER_SIZE":             _num(cfg, r"^HEADER_SIZE\s*=\s*([0-9_]+)", "config.py"),
        "PARAM_SLOW_MAGIC":        _num(cfg, r"^PARAM_SLOW_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "PARAM_SLOW_FLOAT_COUNT":  _num(cfg, r"^PARAM_SLOW_FLOAT_COUNT\s*=\s*([0-9_]+)", "config.py"),
        "PARAM_SLOW_BOOL_COUNT":   _num(cfg, r"^PARAM_SLOW_BOOL_COUNT\s*=\s*([0-9_]+)", "config.py"),
        "PARAM_HEADER_BYTES":      _num(cfg, r"^PARAM_HEADER_SIZE\s*=\s*([0-9_]+)", "config.py"),
        "PARAM_FAST_MAGIC":        _num(cfg, r"^PARAM_FAST_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "PARAM_FAST_FLOAT_COUNT":  _num(cfg, r"^PARAM_FAST_FLOAT_COUNT\s*=\s*([0-9_]+)", "config.py"),
        "CHANNEL_DESC_MAGIC":      _num(cfg, r"^CHANNEL_DESC_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "CHANNEL_DESC_REQUEST_MAGIC": _num(cfg, r"^CHANNEL_DESC_REQUEST_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "CHANNEL_DESC_HEADER_BYTES": _num(cfg, r"^CHANNEL_DESC_HEADER_BYTES\s*=\s*([0-9_]+)", "config.py"),
        "PACKET_HEADER_MAGIC":     _num(cfg, r"^PACKET_HEADER_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "DISCOVERY_MAGIC":         _num(cfg, r"^DISCOVERY_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "DISCOVERY_PACKET_BYTES":  _num(cfg, r"^DISCOVERY_PACKET_BYTES\s*=\s*([0-9_]+)", "config.py"),
        "DISCOVERY_ECHO_MAGIC":    _num(cfg, r"^DISCOVERY_ECHO_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "DISCOVERY_ECHO_PACKET_BYTES": _num(cfg, r"^DISCOVERY_ECHO_PACKET_BYTES\s*=\s*([0-9_]+)", "config.py"),
        "PDS_EVENT_MAGIC":         _num(cfg, r"^PDS_EVENT_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "PDS_EVENT_HEADER_BYTES":  _num(cfg, r"^PDS_EVENT_HEADER_BYTES\s*=\s*([0-9_]+)", "config.py"),
        "PDS_EVENT_TEXT_MAX":      _num(cfg, r"^PDS_EVENT_TEXT_MAX\s*=\s*([0-9_]+)", "config.py"),
        "PARAM_ACK_MAGIC":         _num(cfg, r"^PARAM_ACK_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "PARAM_ACK_HEADER_BYTES":  _num(cfg, r"^PARAM_ACK_HEADER_BYTES\s*=\s*([0-9_]+)", "config.py"),
        "NODE_STATUS_MAGIC":       _num(cfg, r"^NODE_STATUS_MAGIC\s*=\s*(0x[0-9A-Fa-f_]+)", "config.py"),
        "NODE_STATUS_PACKET_BYTES": _num(cfg, r"^NODE_STATUS_PACKET_BYTES\s*=\s*([0-9_]+)", "config.py"),
        "AUX_PORT_NODE1":          _num(cfg, r"^UDP_AUX_PORT_NODE1\s*=\s*([0-9_]+)", "config.py"),
        "WIRE_VERSION":            _num(cfg, r"^PDS_WIRE_VERSION\s*=\s*([0-9_]+)", "config.py"),
    }

    return {"Teensy": teensy, "Node": node_vals, "GUI": gui}


def main() -> int:
    values = collect()
    keys = sorted({k for side in values.values() for k in side})

    problems: list[str] = []
    print(f"{'Konstante':34} {'Teensy':>12} {'Node':>12} {'GUI':>12}")
    print("-" * 74)
    for key in keys:
        row = {side: vals.get(key) for side, vals in values.items()}
        present = [v for v in row.values() if v is not None]
        consistent = len(set(present)) <= 1

        def fmt(v: int | None) -> str:
            if v is None:
                return "-"
            return f"0x{v:08X}" if "MAGIC" in key else str(v)

        mark = "" if consistent else "   <== ABWEICHUNG"
        print(f"{key:34} {fmt(row['Teensy']):>12} {fmt(row['Node']):>12} {fmt(row['GUI']):>12}{mark}")
        if not consistent:
            problems.append(f"{key}: " + ", ".join(
                f"{side}={fmt(v)}" for side, v in row.items() if v is not None))

    # Abgeleitete Paketgroessen zusaetzlich pruefen
    t = values["Teensy"]
    derived = {
        "Telemetriepaket (Bytes)":  t["HEADER_SIZE"] + t["MAX_FLOATS"] * 4,
        "Slow-Parampaket (Bytes)":  t["PARAM_HEADER_BYTES"] + t["PARAM_SLOW_FLOAT_COUNT"] * 4
                                    + t["PARAM_SLOW_BOOL_COUNT"],
        "Fast-Parampaket (Bytes)":  t["PARAM_HEADER_BYTES"] + t["PARAM_FAST_FLOAT_COUNT"] * 4,
        "Param-Ack-Paket (Bytes)":  t["PARAM_ACK_HEADER_BYTES"] + t["PARAM_SLOW_FLOAT_COUNT"] * 4
                                    + t["PARAM_SLOW_BOOL_COUNT"] + t["PARAM_FAST_FLOAT_COUNT"] * 4,
        "Ereignispaket max (Bytes)": t["PDS_EVENT_HEADER_BYTES"] + t["PDS_EVENT_TEXT_MAX"],
        "Deskriptor-Chunk (Bytes)": t["CHANNEL_DESC_HEADER_BYTES"] + t["CHANNEL_DESC_CHUNK_PAYLOAD_MAX"],
    }
    print("-" * 74)
    for name, size in derived.items():
        print(f"{name:34} {size:>12}")

    # ── Baudraten-Budget ────────────────────────────────────────────────
    #  Auf der Leitung liegen inzwischen vier Stroeme. Der Deskriptor ist
    #  der einzige, der die Auslastung kurzzeitig hochtreibt (Boot und auf
    #  Anfrage) — er wird deshalb getrennt ausgewiesen. PDS.cpp laesst ihn
    #  ohnehin nur schreiben, wenn zusaetzlich ein komplettes
    #  Telemetriepaket in den TX-Puffer passt (txRoomFor), er kann den
    #  100-Hz-Takt also nicht verdraengen.
    capacity = t["BAUD"] / 10                     # 8N1 = 10 Bit je Byte
    telemetry_bps = derived["Telemetriepaket (Bytes)"] * 100
    ack_bps = derived["Param-Ack-Paket (Bytes)"] * 2
    event_bps = derived["Ereignispaket max (Bytes)"] * 20     # PDS_EVENT_MAX_PER_SEC
    desc_bps = derived["Deskriptor-Chunk (Bytes)"] * 50       # ein Chunk je 20 ms

    load = (telemetry_bps + ack_bps + event_bps) / capacity * 100
    peak = (telemetry_bps + ack_bps + event_bps + desc_bps) / capacity * 100
    print(f"{'Uplink-Auslastung (Dauerbetrieb)':34} {load:>11.1f} %")
    print(f"{'Uplink-Spitze (mit Deskriptor)':34} {peak:>11.1f} %")
    if load > 90:
        problems.append(
            f"Uplink-Dauerlast {load:.1f} % > 90 % — Baudrate erhoehen oder "
            f"MAX_FLOATS senken (Teensy, Node UND GUI gemeinsam)."
        )
    if peak > 100:
        problems.append(
            f"Uplink-Spitze {peak:.1f} % > 100 % — der Deskriptor passt nicht "
            f"mehr neben die Telemetrie. DESC_CHUNK_PERIOD_MS in PDS.cpp erhoehen."
        )

    print()
    if problems:
        print("FEHLER — das Wire-Format ist NICHT konsistent:")
        for p in problems:
            print(f"  * {p}")
        return 1
    print("OK — Teensy, Node und GUI verwenden dasselbe Wire-Format.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
