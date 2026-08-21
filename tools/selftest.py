#!/usr/bin/env python3
"""
tools/selftest.py — Selbsttest ohne Hardware und ohne PyQt6
==============================================================
Prueft genau die Teile, die man sonst nur mit Teensy + Node + WLAN
testen kann, und die erfahrungsgemaess die meisten Fehler enthalten:

  1. Wire-Format-Konsistenz (tools/check_wire_format.py)
  2. TelemetryFrameAssembler  — Resync nach Byte-Muell, zerstueckelte Pakete
  3. ChunkFrameAssembler      — Deskriptor-Chunks im Telemetriestrom,
                                Abwehr von Zufallstreffern des Magic
  4. DescriptorAssembler      — Zusammensetzen, Neustart mitten in der
                                Uebertragung, Einstieg ohne Chunk 0
  5. ChannelRegistry          — Robustheit gegen kaputtes JSON
  6. apply_overlay_defaults   — leere Gruppen befuellen, volle nie ueberschreiben
  7. param_io                 — Konfiguration laden, Defaults schreiben/lesen
  8. bt_flash_protocol        — Frame-Round-Trip inkl. CRC und Resync

Benoetigt nur die Standardbibliothek. numpy/PyQt6/pyserial/pygame duerfen
fehlen — fehlende Module werden fuer den Test durch Attrappen ersetzt.

Aufruf:
    python tools/selftest.py
Exit-Code 0 = alles gruen.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rpi5_monitor" / "64Bit_Version"))
sys.path.insert(0, str(ROOT / "rpi_zero_node"))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "tools"))

# ── pyserial-Attrappe: uart_receiver.py importiert serial auf Modulebene ────
if "serial" not in sys.modules:
    try:
        import serial  # noqa: F401
    except ImportError:
        stub = types.ModuleType("serial")
        stub.EIGHTBITS = 8
        stub.PARITY_NONE = "N"
        stub.STOPBITS_ONE = 1
        stub.VERSION = "0-stub"

        class _SerialException(Exception):
            pass

        stub.SerialException = _SerialException
        stub.Serial = object
        sys.modules["serial"] = stub

_failures: list[str] = []
_checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    if condition:
        print(f"  [ ok ] {name}")
    else:
        print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")
        _failures.append(name)


def section(title: str) -> None:
    print(f"\n== {title} ==")


# ══════════════════════════════════════════════════════════════════════════
#  1) Wire-Format
# ══════════════════════════════════════════════════════════════════════════
def test_wire_format() -> None:
    section("1) Wire-Format-Konsistenz")
    import check_wire_format
    values = check_wire_format.collect()
    for key in ("MAX_FLOATS", "PARAM_SLOW_MAGIC", "PARAM_FAST_MAGIC",
                "CHANNEL_DESC_MAGIC", "PACKET_HEADER_MAGIC"):
        present = [v[key] for v in values.values() if key in v]
        check(f"{key} auf allen Seiten gleich", len(set(present)) == 1, str(present))


# ══════════════════════════════════════════════════════════════════════════
#  2+3) Frame-Assembler des Nodes
# ══════════════════════════════════════════════════════════════════════════
def test_frame_assemblers() -> None:
    section("2) TelemetryFrameAssembler")
    import uart_receiver as node

    def make_packet(seq: int) -> bytes:
        payload = struct.pack(f"<{node.MAX_FLOATS}f",
                              *[float(seq * 1000 + i) for i in range(node.MAX_FLOATS)])
        return node.MAGIC_BYTES + struct.pack("<I", seq) + payload

    asm = node.TelemetryFrameAssembler()
    p0, p1 = make_packet(0), make_packet(1)

    out = asm.feed(p0)
    check("vollstaendiges Paket wird erkannt", out == [p0])

    # In 7 unterschiedlich grossen Stuecken einspeisen
    out = []
    stream = p1
    for i in range(0, len(stream), 113):
        out += asm.feed(stream[i:i + 113])
    check("zerstueckeltes Paket wird korrekt zusammengesetzt", out == [p1])

    # Byte-Muell davor -> Resync + Sync-Verlust gezaehlt
    before = asm.sync_losses
    out = asm.feed(b"\x11\x22\x33\x44\x55" + p0)
    check("Resync nach Byte-Muell", out == [p0])
    check("Sync-Verlust wird gezaehlt", asm.sync_losses > before)

    # Zwei Pakete in einem Block
    out = asm.feed(p0 + p1)
    check("zwei Pakete in einem Block", out == [p0, p1])

    # Puffer waechst nicht unbegrenzt, wenn nur Muell kommt
    for _ in range(50):
        asm.feed(b"\x00" * 1000)
    check("kein Pufferwachstum bei reinem Muell", len(asm._buf) <= 3,
          f"{len(asm._buf)} Bytes")

    section("3) ChunkFrameAssembler (Deskriptor im Telemetriestrom)")
    desc = node.ChunkFrameAssembler()

    def make_chunk(idx: int, count: int, payload: bytes) -> bytes:
        return (node.CHANNEL_DESC_MAGIC_BYTES
                + bytes([idx, count, len(payload)]) + payload)

    c0 = make_chunk(0, 2, b'{"channels":{"0":"A"')
    c1 = make_chunk(1, 2, b',"1":"B"}}')
    out = desc.feed(p0 + c0 + p1 + c1)
    check("Chunks werden aus dem Telemetriestrom gefischt", out == [c0, c1])

    # Zufallstreffer: Magic mit unmoeglichem Header (chunk_idx >= chunk_count)
    before = desc.false_magics
    bogus = node.CHANNEL_DESC_MAGIC_BYTES + bytes([9, 2, 200]) + b"x" * 200
    out = desc.feed(bogus + c0 + c1)
    check("unplausibler Chunk-Header wird verworfen", out == [c0, c1])
    check("Fehlalarm wird gezaehlt", desc.false_magics > before)

    # Ueber Blockgrenzen zerschnittenes Magic
    desc2 = node.ChunkFrameAssembler()
    out = desc2.feed(c0[:2]) + desc2.feed(c0[2:])
    check("ueber Blockgrenze zerschnittener Chunk", out == [c0])


# ══════════════════════════════════════════════════════════════════════════
#  4+5+6) Deskriptor-Zusammenbau + Registry
# ══════════════════════════════════════════════════════════════════════════
def test_descriptor() -> None:
    section("4) DescriptorAssembler")
    import config
    from channel_registry import (ChannelRegistry, DescriptorAssembler,
                                  apply_overlay_defaults)

    magic = struct.pack("<I", config.CHANNEL_DESC_MAGIC)

    def chunks_for(payload: bytes, size: int = 20) -> list[bytes]:
        parts = [payload[i:i + size] for i in range(0, len(payload), size)] or [b""]
        return [magic + bytes([i, len(parts), len(p)]) + p for i, p in enumerate(parts)]

    doc = {"channels": {"0": "Motor_L", "1": "Motor_R"},
           "param_slow_floats": {"0": "Kp"},
           "param_slow_bools": {}, "param_fast_floats": {"3": "Speed"},
           "overlays": [{"group": 1, "type": "gauge", "label": "M-L",
                         "channel": 0, "min": -5.0, "max": 5.0}]}
    payload = json.dumps(doc).encode()

    asm = DescriptorAssembler()
    result = None
    for c in chunks_for(payload):
        result = asm.feed(c) or result
    check("Deskriptor wird korrekt zusammengesetzt", result == doc)

    # Neustart mitten in der Uebertragung: neuer Chunk 0 verwirft den alten Stand
    asm = DescriptorAssembler()
    cs = chunks_for(payload)
    asm.feed(cs[0])
    asm.feed(cs[1])
    result = None
    for c in cs:                      # kompletter Neuanlauf
        result = asm.feed(c) or result
    check("Neustart mitten in der Uebertragung", result == doc)

    # Einstieg ohne Chunk 0 (GUI spaeter gestartet) -> verwerfen, kein Muell
    asm = DescriptorAssembler()
    for c in cs[1:]:
        check_none = asm.feed(c)
        if check_none is not None:
            break
    check("Einstieg ohne Chunk 0 liefert nichts", not asm.in_progress)
    result = None
    for c in cs:
        result = asm.feed(c) or result
    check("naechster vollstaendiger Durchlauf klappt trotzdem", result == doc)

    # Zeitueberschreitung
    asm = DescriptorAssembler()
    asm.feed(cs[0], now=1000.0)
    check("angefangene Uebertragung laeuft", asm.in_progress)
    check("Zeitueberschreitung verwirft sie", asm.check_timeout(now=1010.0))

    section("5) ChannelRegistry (Robustheit)")
    reg = ChannelRegistry.from_json_dict(doc)
    check("Kanalnamen uebernommen", reg.channel_names == {0: "Motor_L", 1: "Motor_R"})
    check("Fast-Param-Namen uebernommen", reg.param_fast_float_names == {3: "Speed"})
    check("is_empty() ist False", not reg.is_empty())

    kaputt = {"channels": {"abc": "X", "-1": "Y", "2": 42, "3": "OK"},
              "overlays": "kein array"}
    reg2 = ChannelRegistry.from_json_dict(kaputt)
    check("unbrauchbare Eintraege werden ignoriert", reg2.channel_names == {3: "OK"},
          str(reg2.channel_names))
    check("overlays kein Array -> leere Liste", reg2.overlays == [])
    check("leerer Deskriptor -> is_empty()",
          ChannelRegistry.from_json_dict({}).is_empty())

    section("6) apply_overlay_defaults")
    local = {"groups": [
        {"name": "leer", "image_idx": 1, "overlays": [], "graphics": []},
        {"name": "belegt", "image_idx": 1, "overlays": [{"label": "eigen"}], "graphics": []},
    ]}
    changed = apply_overlay_defaults(local, reg)
    check("leere Gruppe wird befuellt", changed and local["groups"][0]["graphics"])
    check("bereits belegte Gruppe bleibt unangetastet",
          local["groups"][1]["overlays"] == [{"label": "eigen"}])
    check("zweiter Aufruf aendert nichts mehr",
          apply_overlay_defaults(local, reg) is False)


# ══════════════════════════════════════════════════════════════════════════
#  7) param_io
# ══════════════════════════════════════════════════════════════════════════
def test_param_io() -> None:
    section("7) param_io")
    import config
    from param_io import (load_param_config, read_param_defaults_h,
                           write_param_defaults_h)

    cfg = load_param_config(config.PARAM_CONFIG_PATH)
    check("param_config.json laedt", len(cfg.floats) == config.PARAM_SLOW_FLOAT_COUNT)
    check("Bool-Liste vollstaendig", len(cfg.bools) == config.PARAM_SLOW_BOOL_COUNT)
    check("Fast-Liste vollstaendig", len(cfg.fast_floats) == config.PARAM_FAST_FLOAT_COUNT)
    check("jeder Eintrag hat einen Namen", all(e.name for e in cfg.floats))
    idx = [e.index for e in cfg.floats]
    check("Indizes 0..n-1 lueckenlos", idx == list(range(len(idx))))

    for js in cfg.joysticks:
        limit = (config.PARAM_SLOW_FLOAT_COUNT if js.source == "slow"
                 else config.PARAM_FAST_FLOAT_COUNT)
        check(f"Joystick '{js.name}' zeigt auf gueltige Indizes",
              0 <= js.x_index < limit and 0 <= js.y_index < limit)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "param_defaults.h"
        floats = [i * 0.5 for i in range(config.PARAM_SLOW_FLOAT_COUNT)]
        bools = [i % 3 == 0 for i in range(config.PARAM_SLOW_BOOL_COUNT)]
        fast = [1.5, -2.5, 0.0, 99.0, -0.25]
        write_param_defaults_h(path, floats, bools, fast)
        back = read_param_defaults_h(path)
        check("param_defaults.h Round-Trip: Floats", back["floats"] == floats)
        check("param_defaults.h Round-Trip: Bools", back["bools"] == bools)
        check("param_defaults.h Round-Trip: Fast", back["fast_floats"] == fast)

        (Path(tmp) / "kaputt.h").write_text("das ist kein C", encoding="utf-8")
        check("kaputte Datei -> None statt Exception",
              read_param_defaults_h(Path(tmp) / "kaputt.h") is None)
        check("fehlende Datei -> None",
              read_param_defaults_h(Path(tmp) / "gibtsnicht.h") is None)


# ══════════════════════════════════════════════════════════════════════════
#  8) bt_flash_protocol
# ══════════════════════════════════════════════════════════════════════════
def test_bt_protocol() -> None:
    section("8) bt_flash_protocol")
    from bt_flash_protocol import Cmd, ProtocolError, recv_frame, send_frame

    a, b = socket.socketpair()
    try:
        send_frame(a, Cmd.HELLO, b"token123")
        cmd, payload = recv_frame(b)
        check("Frame-Round-Trip", cmd == Cmd.HELLO and payload == b"token123")

        send_frame(a, Cmd.FLASH_END)
        cmd, payload = recv_frame(b)
        check("Frame ohne Payload", cmd == Cmd.FLASH_END and payload == b"")

        big = os.urandom(8192)
        send_frame(a, Cmd.DATA_CHUNK, big)
        cmd, payload = recv_frame(b)
        check("8-kB-Chunk unveraendert", payload == big)

        # Byte-Muell vor dem Frame -> recv_frame faedelt sich wieder ein
        a.sendall(b"\xde\xad\xbe")
        send_frame(a, Cmd.PING)
        cmd, _ = recv_frame(b)
        check("Resync nach Byte-Muell", cmd == Cmd.PING)

        # Verfaelschte Payload -> CRC-Fehler
        import zlib
        header = struct.pack("<IBI", 0xB17F1A55, Cmd.DATA_CHUNK, 4)
        a.sendall(header + b"ABCD" + struct.pack("<I", zlib.crc32(b"XXXX")))
        try:
            recv_frame(b)
            check("CRC-Fehler wird erkannt", False, "keine Exception")
        except ProtocolError:
            check("CRC-Fehler wird erkannt", True)
    finally:
        a.close()
        b.close()


# ══════════════════════════════════════════════════════════════════════════
#  9) QML <-> Python-Bruecken
# ══════════════════════════════════════════════════════════════════════════
def test_qml_bindings() -> None:
    section("9) QML-Zugriffe auf die Python-Bruecken")
    import check_qml_bindings as q

    members = {name: q.members_of(path, cls)
               for name, (path, cls) in q.BRIDGE_CLASSES.items()}
    qml_files = sorted(q.QML_DIR.rglob("*.qml"))
    check("QML-Dateien gefunden", len(qml_files) > 0)

    problems: list[str] = []
    for f in qml_files:
        problems += q.check_balance(f)
        problems += q.check_file(f, members)
    check(f"{len(qml_files)} QML-Dateien ohne unbekannte Zugriffe/Klammerfehler",
          not problems, "; ".join(problems[:4]))


def main() -> int:
    print("Power Debug System — Selbsttest")
    for fn in (test_wire_format, test_frame_assemblers, test_descriptor,
               test_param_io, test_bt_protocol, test_qml_bindings):
        try:
            fn()
        except Exception as exc:            # noqa: BLE001
            import traceback
            print(f"  [FAIL] {fn.__name__} hat eine Ausnahme ausgeloest: {exc}")
            traceback.print_exc()
            _failures.append(fn.__name__)

    print(f"\n{'=' * 60}")
    if _failures:
        print(f"{len(_failures)} von {_checks} Pruefungen FEHLGESCHLAGEN:")
        for f in _failures:
            print(f"  * {f}")
        return 1
    print(f"Alle {_checks} Pruefungen bestanden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
