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
    }
    print("-" * 74)
    for name, size in derived.items():
        print(f"{name:34} {size:>12}")

    # Baudraten-Budget: passt der Uplink ueberhaupt auf die Leitung?
    pkt = derived["Telemetriepaket (Bytes)"]
    bytes_per_s = pkt * 100                       # 100 Hz
    capacity = t["BAUD"] / 10                     # 8N1 = 10 Bit je Byte
    load = bytes_per_s / capacity * 100
    print(f"{'Uplink-Auslastung bei 100 Hz':34} {load:>11.1f} %")
    if load > 90:
        problems.append(
            f"Uplink-Auslastung {load:.1f} % > 90 % — Baudrate erhoehen oder "
            f"MAX_FLOATS senken (Teensy, Node UND GUI gemeinsam)."
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
