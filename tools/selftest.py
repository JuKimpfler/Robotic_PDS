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
  9. QML-Zugriffe             — jeder Zugriff existiert wirklich in Python
 10. Aux-Uplink               — Ereignis/Param-Ack/Node-Status parsen
 11. runtime_config           — Teensy-Konfiguration -> param_config.json,
                                Fingerabdruck, atomares Speichern
 12. expand_textgrid          — Rasterlayout vieler Werte auf einem Bild
 13. overlay_schema           — Feldschema und Typumwandlung des Editors,
                                Konfliktregel Teensy <-> Handarbeit
 14. Thread-Ableitungen       — kein Attribut ueberdeckt ein Interna von
                                threading.Thread (versionsunabhaengig)
 15. Plotter-Marken /         — Marken bleiben im Bild, Trigger-Marke sitzt
     Controller-Mapping         an der Flanke; controller_config.json haelt
                                die GUI nie vom Start ab

Benoetigt nur die Standardbibliothek. numpy/PyQt6/pyserial/pygame duerfen
fehlen — fehlende Module werden fuer den Test durch Attrappen ersetzt.

Aufruf:
    python tools/selftest.py
Exit-Code 0 = alles gruen.
"""
from __future__ import annotations

import importlib.util
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
#  find_spec() statt eines try/except um `import serial`: der Import haette
#  hier nur die Frage "ist pyserial da?" beantwortet und einen Namen gebunden,
#  den niemand benutzt — pyflakes meldet genau das, und die CI-Stufe lief
#  deshalb rot. `# noqa` kennt pyflakes nicht.
if "serial" not in sys.modules:
    if importlib.util.find_spec("serial") is None:
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

    # ── Unlesbare Zahlen aus dem Deskriptor ───────────────────────────────
    #  Die Overlay-Werte kommen ueber UART/WLAN und teilweise aus einem frei
    #  geschriebenen `extra`-String — an einer Zahlenstelle kann also Text
    #  stehen. Ein ungeschuetztes int()/float() beendete den Prozess, sobald
    #  jemand im Editor "Teensy uebernehmen" gedrueckt hat
    #  (applyPendingTeensyConfig ist ein Slot, PyQt macht daraus ein abort()).
    kaputt = ChannelRegistry()
    kaputt.overlays = [
        {"type": "gauge", "label": "G", "group": 1, "channel": "nope",
         "min": "a", "max": None},
        {"type": "rotation", "label": "R", "group": 1, "channel": 2, "max": "schnell"},
        {"type": "textgrid", "label": "B", "group": "1",
         "extra": "channels=0-3;cols=zwei;dx=;dy=4"},
        {"type": "bodies", "label": "F", "group": 1,
         "extra": "field_x_cm=xx;body1_channel_x=3;body1_diameter=nan"},
    ]
    ziel = {"groups": [{"name": "A", "image_idx": 1, "overlays": [], "graphics": []}]}
    try:
        apply_overlay_defaults(ziel, kaputt, overwrite=True)
        ok = True
    except Exception as exc:                                   # noqa: BLE001
        ok = False
        print(f"       {type(exc).__name__}: {exc}")
    check("unlesbare Overlay-Zahlen werfen keine Ausnahme", ok)
    if ok:
        grafiken = {g["type"]: g for g in ziel["groups"][0]["graphics"]}
        check("Zeiger faellt auf brauchbare Grenzen zurueck",
              grafiken["gauge"]["min"] < grafiken["gauge"]["max"],
              str(grafiken.get("gauge")))
        check("Feldmasse fallen auf 240 x 180 cm zurueck",
              (grafiken["bodies"]["field_x_cm"],
               grafiken["bodies"]["field_y_cm"]) == (240.0, 180.0),
              str(grafiken.get("bodies")))
        check("Kanal aus dem extra-String bleibt erhalten",
              grafiken["bodies"]["body1"]["channel_x"] == 3)
        raster = ziel["groups"][0]["overlays"][0]
        check("unlesbare Spaltenzahl wird zu mindestens 1",
              raster["cols"] >= 1, str(raster))


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

    # pc_flash_tool/ enthaelt ABSICHTLICH eine zweite, identische Kopie des
    # Protokolls: das Verzeichnis soll sich allein auf einen anderen PC
    # kopieren lassen (bt_flash_sender.py nimmt shared/, wenn es da ist, und
    # sonst die Kopie daneben). Zwei Dateien, die von Hand gleich gehalten
    # werden muessen, laufen aber irgendwann auseinander — und dann redet der
    # PC ein anderes Protokoll als der Node, ohne dass es jemandem auffaellt.
    shared = (ROOT / "shared" / "bt_flash_protocol.py").read_bytes()
    copy = (ROOT / "pc_flash_tool" / "bt_flash_protocol.py").read_bytes()
    check("Kopie in pc_flash_tool/ ist identisch mit shared/",
          shared == copy,
          "beide Dateien muessen Byte fuer Byte gleich sein")

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



# ══════════════════════════════════════════════════════════════════════════
#  10) Aux-Uplink: Ereignisse, Param-Ack, Node-Status
# ══════════════════════════════════════════════════════════════════════════
def test_aux_uplink() -> None:
    section("10) Aux-Uplink (Ereignisse, Param-Ack, Node-Status)")
    import config
    from aux_receiver import parse_aux_packet
    import uart_receiver as node

    # ── Ereignis ──────────────────────────────────────────────────────────
    text = "Ball verloren".encode("utf-8")
    ev = struct.pack("<IIfBBBB", config.PDS_EVENT_MAGIC, 123456, 4.25,
                      0, 1, len(text), 0) + text
    check("Ereignis: Kopfgroesse stimmt mit params.h ueberein",
          config.PDS_EVENT_HEADER_BYTES == 16)
    parsed = parse_aux_packet(ev)
    check("Ereignis wird erkannt", parsed is not None and parsed[0] == "event")
    if parsed:
        d = parsed[1]
        check("Ereignis: Text", d["text"] == "Ball verloren", d["text"])
        check("Ereignis: Zeitstempel/Wert/Stufe",
              d["ts_us"] == 123456 and abs(d["value"] - 4.25) < 1e-6 and d["level"] == 1)

    bad = bytearray(ev)
    bad[15] = 7        # reserved != 0
    check("Ereignis mit belegtem Reserve-Byte wird verworfen",
          parse_aux_packet(bytes(bad)) is None)
    bad = bytearray(ev)
    bad[12] = 9        # kind ausserhalb 0/1
    check("Ereignis mit unbekannter Art wird verworfen",
          parse_aux_packet(bytes(bad)) is None)
    check("zu kurzes Ereignis wird verworfen", parse_aux_packet(ev[:10]) is None)

    # ── Parameter-Rueckmeldung ────────────────────────────────────────────
    floats = [i * 0.5 for i in range(config.PARAM_SLOW_FLOAT_COUNT)]
    bools = [(i % 3) == 0 for i in range(config.PARAM_SLOW_BOOL_COUNT)]
    fast = [-1.0, 0.0, 1.0, 2.0, 3.0][:config.PARAM_FAST_FLOAT_COUNT]
    ack = (struct.pack("<IIIII", config.PARAM_ACK_MAGIC, 7, 8, 120, 0xFFFFFFFF)
           + struct.pack(f"<{len(floats)}f", *floats)
           + bytes(1 if b else 0 for b in bools)
           + struct.pack(f"<{len(fast)}f", *fast))
    check("Param-Ack: Paketgroesse wie in params.h",
          len(ack) == config.PARAM_ACK_PACKET_BYTES,
          f"{len(ack)} statt {config.PARAM_ACK_PACKET_BYTES}")
    parsed = parse_aux_packet(ack)
    check("Param-Ack wird erkannt", parsed is not None and parsed[0] == "ack")
    if parsed:
        d = parsed[1]
        check("Param-Ack: Floats unveraendert",
              all(abs(a - b) < 1e-6 for a, b in zip(d["floats"], floats)))
        check("Param-Ack: Bools unveraendert", list(d["bools"]) == bools)
        check("Param-Ack: 0xFFFFFFFF wird zu 'nie empfangen'",
              d["fast_age_ms"] is None and d["slow_age_ms"] == 120)
    check("Param-Ack mit falscher Laenge wird verworfen",
          parse_aux_packet(ack[:-1]) is None)

    # ── Node-Status ───────────────────────────────────────────────────────
    st = struct.pack(config.NODE_STATUS_STRUCT, config.NODE_STATUS_MAGIC, 2,
                      config.NODE_STATUS_FLAG_TEENSY | config.NODE_STATUS_FLAG_WIFI, 0,
                      52.5, 0.75, 41.0, -58.0, 3600, 1000, 2, 999)
    check("Node-Status: Paketgroesse", len(st) == config.NODE_STATUS_PACKET_BYTES)
    parsed = parse_aux_packet(st)
    check("Node-Status wird erkannt", parsed is not None and parsed[0] == "status")
    if parsed:
        d = parsed[1]
        check("Node-Status: Werte",
              d["node_id"] == 2 and abs(d["cpu_temp_c"] - 52.5) < 1e-6
              and abs(d["wifi_rssi_dbm"] + 58.0) < 1e-6)
        check("Node-Status: Flags", d["teensy_link"] and d["wifi_ok"] and not d["unicast"])
        check("Node-Status: Uptime", d["uptime_s"] == 3600)

    check("unbekanntes Magic wird verworfen",
          parse_aux_packet(struct.pack("<I", 0x12345678) + b"x" * 40) is None)

    # ── Assembler des Nodes auf einem gemischten Bytestrom ────────────────
    #  Genau der kritische Fall: Ereignis und Ack stecken MITTEN in einem
    #  Telemetriestrom und muessen sauber herausgefischt werden.
    telemetry = struct.pack("<II", node.MAGIC, 42) + b"\x11" * (node.PACKET_BYTES - 8)
    stream = telemetry + ev + telemetry + ack + b"\x00\x01\x02"

    ea = node.EventFrameAssembler()
    got = []
    for i in range(0, len(stream), 97):          # bewusst krumme Blockgroesse
        got += ea.feed(stream[i:i + 97])
    check("EventFrameAssembler findet das Ereignis im Telemetriestrom",
          len(got) == 1 and got[0] == ev, f"{len(got)} Treffer")

    aa = node.ParamAckFrameAssembler()
    got = []
    for i in range(0, len(stream), 61):
        got += aa.feed(stream[i:i + 61])
    check("ParamAckFrameAssembler findet die Rueckmeldung",
          len(got) == 1 and got[0] == ack, f"{len(got)} Treffer")


# ══════════════════════════════════════════════════════════════════════════
#  11) runtime_config: Konfiguration vom Teensy
# ══════════════════════════════════════════════════════════════════════════
def test_runtime_config() -> None:
    section("11) runtime_config (Teensy-Konfiguration, reboot-fest)")
    import runtime_config as rc

    desc_cfg = {
        "slow_floats": [
            {"i": 0, "n": "Kp", "w": "slider", "min": 0, "max": 10, "step": 0.05,
             "def": 2.5, "g": "Regler"},
            {"i": 1, "n": "Ki", "w": "number", "min": 0, "max": 5, "step": 0.01, "def": 0.2},
            {"i": 1, "n": "Doppelt", "w": "slider"},        # doppelter Index
            {"i": 2, "n": "Kaputt", "w": "slider", "min": 5, "max": 1},  # leerer Bereich
            {"i": 3, "w": "slider"},                        # ohne Namen
        ],
        "slow_bools": [{"i": 0, "n": "Motoren", "w": "toggle"},
                        {"i": 1, "n": "NotAus", "w": "button", "m": True}],
        "fast_floats": [{"i": 0, "n": "X", "w": "slider", "min": -100, "max": 100}],
        "joysticks": [{"n": "Fahrt", "s": "fast", "x": 0, "y": 1,
                       "xr": [-100, 100], "yr": [-100, 100], "c": True},
                       {"n": "Kaputt", "s": "schnell", "x": 0, "y": 1}],
    }
    cfg = rc.param_config_from_descriptor(desc_cfg)
    check("Konfiguration wird erzeugt", cfg is not None)
    if cfg:
        idx = [e["index"] for e in cfg["floats"]]
        check("doppelter Index wird verworfen", idx.count(1) == 1, str(idx))
        check("Eintrag ohne Namen wird verworfen", 3 not in idx, str(idx))
        kaputt = [e for e in cfg["floats"] if e["index"] == 2]
        check("leerer Wertebereich wird korrigiert",
              len(kaputt) == 1 and kaputt[0]["max"] > kaputt[0]["min"])
        check("Default wird in den Bereich geklemmt",
              all(e["min"] <= e["default"] <= e["max"] for e in cfg["floats"]))
        check("Bools werden zu Wahrheitswerten",
              all(isinstance(e["default"], bool) for e in cfg["bools"]))
        check("momentary bleibt erhalten",
              any(e["momentary"] for e in cfg["bools"]))
        check("ungueltige Joystick-Quelle wird verworfen",
              len(cfg["joysticks"]) == 1, str(cfg["joysticks"]))

        # Die erzeugte Konfiguration muss param_io tatsaechlich laden koennen —
        # sonst waere der Parameter-Tab nach einem Firmware-Update tot.
        import param_io
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "param_config.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            loaded = param_io.load_param_config(path)
            check("param_io laedt die erzeugte Konfiguration",
                  loaded.floats[0].name == "Kp" and loaded.bools[1].momentary)

    check("leere Teensy-Konfiguration -> None",
          rc.param_config_from_descriptor({}) is None)
    check("Unsinn statt dict -> None",
          rc.param_config_from_descriptor("nope") is None)

    # ── Ein unbrauchbarer Eintrag darf nicht die ganze Datei kosten ───────
    #  Der Deskriptor kommt ueber UART und WLAN. Bis hierher warf ein
    #  `float(None)` auf einem einzigen Feld bis in _persist_registry hoch —
    #  gefangen wurde es dort zwar, aber die KOMPLETTE Parameter-
    #  Konfiguration des Roboters war damit weg, und die GUI lief still mit
    #  der Vorlage aus dem Repository weiter.
    muell = rc.param_config_from_descriptor({
        "slow_floats": [
            {"i": 0, "n": "Gut", "w": "slider", "min": 0, "max": 10, "def": 1.0},
            {"i": 1, "n": "DefNull", "w": "slider", "min": 0, "max": 10, "def": None},
            {"i": 2, "n": "StepText", "w": "slider", "step": "abc"},
            {"i": 3, "n": "MinText", "w": "slider", "min": "lo"},
            {"i": 4, "n": "DefNaN", "w": "slider", "def": float("nan")},
            {"i": 5, "n": "AuchGut", "w": "slider", "min": 0, "max": 4, "def": 3.0},
        ],
        "joysticks": [{"n": "BereichText", "s": "fast", "x": 0, "y": 1,
                        "xr": ["a", "b"]},
                       {"n": "Gut", "s": "fast", "x": 2, "y": 3}],
    })
    check("unlesbare Einzelwerte werfen keine Ausnahme", muell is not None)
    if muell:
        namen = [e["name"] for e in muell["floats"]]
        check("brauchbare Eintraege bleiben erhalten",
              "Gut" in namen and "AuchGut" in namen, str(namen))
        check("unlesbare Zahlenfelder verwerfen nur ihren Eintrag",
              "StepText" not in namen and "MinText" not in namen, str(namen))
        check("NaN landet nie in der Konfiguration",
              all(e["default"] == e["default"] for e in muell["floats"]))
        check("unlesbarer Joystick-Bereich verwirft nur diesen Joystick",
              [j["name"] for j in muell["joysticks"]] == ["Gut"],
              str(muell["joysticks"]))

    # ── Fingerabdruck + atomares Speichern ────────────────────────────────
    h1 = rc.teensy_hash({"a": 1, "b": [2, 3]})
    h2 = rc.teensy_hash({"b": [2, 3], "a": 1})
    check("Fingerabdruck ist unabhaengig von der Schluesselreihenfolge", h1 == h2)
    check("Fingerabdruck aendert sich bei geaendertem Inhalt",
          h1 != rc.teensy_hash({"a": 1, "b": [2, 4]}))

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        orig_path_fn = rc.runtime_config_path
        orig_dir = rc.RUNTIME_CONFIG_DIR
        rc.runtime_config_path = lambda nid, name: base / f"node{nid}" / name
        rc.RUNTIME_CONFIG_DIR = base
        try:
            ok = rc.save_json(1, "test.json", {"x": 1})
            check("save_json legt die Datei an", ok and (base / "node1" / "test.json").exists())
            check("load_json liest sie zurueck", rc.load_json(1, "test.json") == {"x": 1})
            check("kein .tmp-Rest nach dem Schreiben",
                  not list((base / "node1").glob("*.tmp")))
            check("fehlende Datei -> None", rc.load_json(1, "fehlt.json") is None)
            (base / "node1" / "kaputt.json").write_text("{nicht json", encoding="utf-8")
            check("kaputte Datei -> None statt Ausnahme",
                  rc.load_json(1, "kaputt.json") is None)

            path, written = rc.sync_param_config(1, desc_cfg)
            check("sync_param_config schreibt beim ersten Mal", written)
            _path2, written2 = rc.sync_param_config(1, desc_cfg)
            check("unveraenderte Konfiguration wird NICHT erneut geschrieben",
                  not written2)
            changed = dict(desc_cfg)
            changed["slow_floats"] = desc_cfg["slow_floats"] + [
                {"i": 9, "n": "Neu", "w": "slider", "min": 0, "max": 1}]
            _path3, written3 = rc.sync_param_config(1, changed)
            check("geaenderte Konfiguration wird uebernommen", written3)

            removed = rc.clear(1)
            check("clear() loescht die gespeicherten Dateien", removed >= 1)
        finally:
            rc.runtime_config_path = orig_path_fn
            rc.RUNTIME_CONFIG_DIR = orig_dir


# ══════════════════════════════════════════════════════════════════════════
#  12) textgrid: viele Werte als Raster auf einem Bild
# ══════════════════════════════════════════════════════════════════════════
def test_textgrid() -> None:
    section("12) Overlay-Typ textgrid")
    sys.path.insert(0, str(ROOT / "rpi5_monitor" / "64Bit_Version"))
    from bridge.utils import expand_textgrid

    def name_for(ch):
        return f"K{ch}"

    grid = expand_textgrid({
        "channels": "0-3,10", "cols": 2, "dx_pct": 20, "dy_pct": 5,
        "x_pct": 4, "y_pct": 6,
    }, name_for)
    check("Kanalliste inkl. Bereich wird aufgeloest", len(grid) == 5, str(len(grid)))
    if len(grid) == 5:
        check("Kanaele in der richtigen Reihenfolge",
              [g["channel"] for g in grid] == [0, 1, 2, 3, 10])
        check("erste Zeile: zwei Spalten nebeneinander",
              grid[0]["xPct"] == 4 and grid[1]["xPct"] == 24
              and grid[0]["yPct"] == grid[1]["yPct"])
        check("zweite Zeile beginnt wieder links und eine Zeile tiefer",
              grid[2]["xPct"] == 4 and grid[2]["yPct"] == 11)
        check("Beschriftung kommt aus der Namensfunktion", grid[0]["label"] == "K0")

    ohne = expand_textgrid({"channels": "0-1", "labels": False}, name_for)
    check("labels=0 laesst die Beschriftung weg",
          all(g["label"] == "" for g in ohne))
    check("ohne Kanalliste kommt nichts heraus",
          expand_textgrid({"cols": 2}, name_for) == [])


# ══════════════════════════════════════════════════════════════════════════
#  13) Overlay-Editor: Feldschema, Typumwandlung, Konfliktregel
# ══════════════════════════════════════════════════════════════════════════
def test_overlay_editor() -> None:
    section("13) Overlay-Editor")
    import overlay_schema as osch
    import runtime_config

    # ── Arten und Feldschema ─────────────────────────────────────────────
    check("fehlendes 'type' bedeutet Text",
          osch.entry_kind({"label": "x"}) == "text")
    check("unbekanntes 'type' faellt auf Text zurueck",
          osch.entry_kind({"type": "quatsch"}) == "text")

    for kind in osch.OVERLAY_KINDS + osch.GRAPHIC_KINDS:
        entry = osch.new_entry(kind)
        fields = osch.describe(entry)
        check(f"{kind}: neuer Eintrag hat Felder und alle einen Wert",
              len(fields) > 0 and all("value" in f for f in fields))
        check(f"{kind}: neuer Eintrag ist ohne Beanstandung",
              osch.problems(entry) == [], str(osch.problems(entry)))
        check(f"{kind}: Art bleibt nach dem Anlegen erhalten",
              osch.entry_kind(entry) == kind)

    # "text" darf KEIN type-Feld bekommen, sonst versteht die alte
    # visuals_overlays.json-Ladelogik den Eintrag nicht mehr.
    check("Text-Eintrag bleibt ohne 'type'-Schluessel",
          "type" not in osch.new_entry("text"))

    # ── Typumwandlung: QML liefert alles als Zeichenkette ────────────────
    grid = osch.new_entry("textgrid")
    osch.set_value(grid, "cols", "3")
    check("Zahl aus einem Textfeld wird zu int",
          grid["cols"] == 3 and isinstance(grid["cols"], int))
    osch.set_value(grid, "dx_pct", "22,5")
    check("deutsches Dezimalkomma wird verstanden", grid["dx_pct"] == 22.5)
    osch.set_value(grid, "cols", "999")
    check("zu grosser Wert wird auf das Maximum begrenzt", grid["cols"] == 12)
    before = grid["dy_pct"]
    osch.set_value(grid, "dy_pct", "keine Zahl")
    check("unlesbare Eingabe laesst das Feld unveraendert", grid["dy_pct"] == before)
    osch.set_value(grid, "dy_pct", float("nan"))
    check("NaN landet nie in der Konfiguration", grid["dy_pct"] == before)
    osch.set_value(grid, "labels", "0")
    check('"0" wird zu False', grid["labels"] is False)
    osch.set_value(grid, "channels", " 0-11,20 ")
    check("Kanal-Spezifikation bleibt als Text erhalten (nicht aufgeloest)",
          grid["channels"] == "0-11,20")
    check("unbekannter Schluessel wird abgewiesen",
          osch.set_value(grid, "gibtsnicht", 1) is False)

    # ── DIE Regression: ein Raster bleibt EIN Eintrag ────────────────────
    #  Wuerde der Editor die aufbereitete Fassung zurueckschreiben, waeren
    #  aus einem Block hier 13 Einzeleintraege geworden — und der ganze
    #  Sinn ("nicht 13 Positionen von Hand pflegen") waere dahin.
    from bridge.utils import expand_textgrid
    cells = expand_textgrid(grid, lambda c: f"K{c}")
    check("das Raster zeigt viele Zellen", len(cells) == 13)
    x0, y0 = grid["x_pct"], grid["y_pct"]
    grid["x_pct"], grid["y_pct"] = osch.move_position(grid, 5.0, -3.0)
    check("Ziehen verschiebt nur die linke obere Ecke",
          grid["x_pct"] == x0 + 5 and grid["y_pct"] == y0 - 3
          and len(osch.describe(grid)) == len(osch.fields_for("textgrid")))
    moved = expand_textgrid(grid, lambda c: f"K{c}")
    check("alle Zellen wandern um denselben Betrag mit",
          all(abs((m["xPct"] - c["xPct"]) - 5.0) < 1e-9
              and abs((m["yPct"] - c["yPct"]) + 3.0) < 1e-9
              for c, m in zip(cells, moved)))

    # ── Positionsgrenzen ─────────────────────────────────────────────────
    check("nach links aus dem Bild geschoben wird begrenzt",
          osch.move_position({"x_pct": 0, "y_pct": 0}, -500, -500)
          == (osch.POS_MIN, osch.POS_MIN))
    check("nach rechts aus dem Bild geschoben wird begrenzt",
          osch.move_position({"x_pct": 0, "y_pct": 0}, 500, 500)
          == (osch.POS_MAX, osch.POS_MAX))
    check("Text an einer Zahlenstelle stuerzt nicht ab",
          osch.move_position({"x_pct": "kaputt", "y_pct": None}, 1, 1)
          == (6.0, 9.0))

    # ── Verschachtelte Schluessel (Feldansicht) ──────────────────────────
    bodies = osch.new_entry("bodies")
    osch.set_value(bodies, "body2.label", "Ball")
    check("verschachtelter Schluessel wird gesetzt",
          bodies["body2"]["label"] == "Ball"
          and osch.get_value(bodies, "body2.label") == "Ball")
    osch.set_value(bodies, "body1.channel_x", "7")
    check("nur x gesetzt, y fehlt -> Hinweis",
          any("x und y" in p for p in osch.problems(bodies)),
          str(osch.problems(bodies)))
    osch.set_value(bodies, "body1.channel_y", "8")
    check("x und y gesetzt -> kein Hinweis mehr",
          not any("x und y" in p for p in osch.problems(bodies)))

    # ── Pruefungen ───────────────────────────────────────────────────────
    g = osch.new_entry("gauge")
    osch.set_value(g, "max", -5.0)
    check("Minimum >= Maximum wird gemeldet",
          any("Minimum" in p for p in osch.problems(g)))
    tg = osch.new_entry("textgrid")
    tg["channels"] = ""
    check("leere Kanalliste wird gemeldet",
          any("Kanaele" in p for p in osch.problems(tg)))
    tg["channels"] = "0,999"
    check("Kanal ausserhalb des Wire-Formats wird gemeldet",
          any("999" in p for p in osch.problems(tg)))

    # Ein OPTIONALER Kanal, der schlicht nicht gesetzt ist, ist kein Mangel —
    # ein Koerper der Feldansicht braucht weder Winkel noch Durchmesser.
    # Vorher lief get_value() dort auf None, int(None) warf, und der Editor
    # meldete fuer jeden nicht belegten Kanal "keine gueltige Kanalnummer".
    knapp = {"type": "bodies", "body1": {"channel_x": 5, "channel_y": 6}, "body2": {}}
    check("nicht gesetzter optionaler Kanal ist kein Mangel",
          osch.problems(knapp) == [], str(osch.problems(knapp)))

    # ── summary()/problems() laufen in pyqtProperty-Gettern ──────────────
    #  Eine Ausnahme dort beendet den Prozess. Die Eintraege kommen aber aus
    #  einer von Hand editierbaren JSON-Datei, an einer Zahlenstelle kann
    #  also Text stehen.
    def _name(i):
        return f"K{i}"

    for entry in ({"label": "T", "channel_idx": "x"},
                   {"type": "gauge", "label": "G", "channel": "x"},
                   {"type": "vector", "label": "V", "channel_angle": None},
                   {"type": "bodies", "label": "F", "field_x_cm": "240"},
                   {"type": "bodies", "body1": {"channel_x": "abc"}}):
        try:
            osch.summary(entry, _name)
            osch.problems(entry)
            ok = True
        except Exception as exc:                               # noqa: BLE001
            ok = False
            print(f"       {type(exc).__name__}: {exc}")
        check(f"unlesbare Zahl in {osch.entry_kind(entry)} wirft nicht", ok)

    # Die Feldansicht ist 240 cm BREIT und 180 cm hoch — x waagerecht,
    # y senkrecht. In summary() standen die Rueckfallwerte vertauscht, ein
    # Eintrag ohne Feldmasse erschien in der Liste deshalb als 180x240 cm,
    # waehrend die Ansicht daneben 240 x 180 zeichnete.
    check("Feldansicht ohne Masse wird als 240x180 cm zusammengefasst",
          "240x180" in osch.summary({"type": "bodies", "label": "F"}, _name),
          osch.summary({"type": "bodies", "label": "F"}, _name))
    check("Feldansicht im Altformat behaelt ihre Masse",
          "300x200" in osch.summary(
              {"type": "bodies", "field_width": 300, "field_height": 200}, _name))

    # ── Konfliktregel Teensy <-> Handarbeit ──────────────────────────────
    H, E = runtime_config.TEENSY_HASH_KEY, runtime_config.LOCAL_EDIT_KEY
    check("nichts gespeichert -> Teensy befuellt",
          runtime_config.merge_decision(None, "abc") == "overwrite")
    check("gleicher Fingerabdruck -> nichts tun",
          runtime_config.merge_decision({H: "abc"}, "abc") == "keep")
    check("neue Firmware ohne Handarbeit -> Teensy gewinnt",
          runtime_config.merge_decision({H: "alt"}, "neu") == "overwrite")
    check("neue Firmware MIT Handarbeit -> nachfragen",
          runtime_config.merge_decision({H: "alt", E: True}, "neu") == "ask")
    check("gleicher Fingerabdruck schlaegt Handarbeit -> nicht nachfragen",
          runtime_config.merge_decision({H: "abc", E: True}, "abc") == "keep")
    check("offene, ungespeicherte Bearbeitung -> immer nachfragen",
          runtime_config.merge_decision(None, "abc", editing_unsaved=True) == "ask")


# ══════════════════════════════════════════════════════════════════════════
#  14) Thread-Ableitungen duerfen keine Interna von threading.Thread ueberdecken
# ══════════════════════════════════════════════════════════════════════════
def test_thread_attribute_clash() -> None:
    section("14) Thread-Ableitungen")
    import ast
    import threading

    # Interna, die threading.Thread ueber die Jahre hatte. Die aktuelle
    # Laufzeit allein reicht NICHT: Python 3.14 hat _stop entfernt, in 3.11
    # und 3.12 gibt es die Methode aber weiterhin — und genau dort lief die
    # GUI in "TypeError: 'Event' object is not callable", weil ein Attribut
    # namens _stop sie ueberdeckte. Ein Test, der nur die eigene Version
    # befragt, haette das auf einem 3.14-Rechner nie gesehen.
    HISTORISCH = {
        "_stop", "_bootstrap", "_bootstrap_inner", "_delete", "_handle",
        "_reset_internal_locks", "_set_ident", "_set_native_id",
        "_set_tstate_lock", "_wait_for_tstate_lock", "_invoke_excepthook",
        "_target", "_args", "_kwargs", "_name", "_daemonic", "_ident",
        "_native_id", "_tstate_lock", "_started", "_is_stopped",
        "_initialized", "_stderr",
    }
    verboten = HISTORISCH | {n for n in dir(threading.Thread) if n.startswith("_")}

    def basisnamen(node: ast.ClassDef) -> set[str]:
        out = set()
        for b in node.bases:
            if isinstance(b, ast.Name):
                out.add(b.id)
            elif isinstance(b, ast.Attribute):
                out.add(b.attr)
        return out

    geprueft = 0
    treffer: list[str] = []
    for pfad in sorted(ROOT.rglob("*.py")):
        if any(teil in (".git", "__pycache__") for teil in pfad.parts):
            continue
        try:
            baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
        except SyntaxError:
            continue
        for node in ast.walk(baum):
            if not isinstance(node, ast.ClassDef) or "Thread" not in basisnamen(node):
                continue
            geprueft += 1
            for stmt in ast.walk(node):
                ziele = []
                if isinstance(stmt, ast.Assign):
                    ziele = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    ziele = [stmt.target]
                for ziel in ziele:
                    if (isinstance(ziel, ast.Attribute)
                            and isinstance(ziel.value, ast.Name)
                            and ziel.value.id == "self"
                            and ziel.attr in verboten):
                        treffer.append(f"{pfad.relative_to(ROOT)}:{ziel.lineno}: "
                                       f"{node.name}.self.{ziel.attr}")

    check("mindestens eine Thread-Ableitung gefunden", geprueft >= 1, str(geprueft))
    check("keine Thread-Ableitung ueberdeckt ein Attribut von threading.Thread",
          not treffer, "; ".join(treffer))


# ══════════════════════════════════════════════════════════════════════════
#  15) Plotter-Marken und Controller-Mapping
# ══════════════════════════════════════════════════════════════════════════
#  Beide brauchen PyQt6 (und numpy). Fehlen sie, wird der Abschnitt sauber
#  uebersprungen — die CI installiert beides, dort laeuft er also immer.
def test_plot_markers_and_controller() -> None:
    section("15) Plotter-Marken und Controller-Mapping")
    # Wirklich importieren statt nur find_spec(): das pip-Paket PyQt6 kann
    # vollstaendig installiert sein und sich trotzdem nicht laden lassen,
    # weil die Qt-Systembibliotheken fehlen — auf einem nackten Linux wirft
    # schon `import PyQt6.QtGui` "libEGL.so.1: cannot open shared object
    # file". find_spec() findet dort die Moduldatei, und der Import
    # scheiterte erst mitten im Abschnitt statt ihn zu ueberspringen.
    # import_module() statt `import X`: sonst meldet pyflakes den
    # ungenutzten Namen (siehe pyserial-Attrappe oben).
    for mod in ("numpy", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtQuick"):
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            print(f"  [ -- ] uebersprungen: {mod} laesst sich nicht laden ({exc})")
            return

    import numpy as np
    from bridge.plot_bridge import PlotBridge

    # ── Marken duerfen nie ausserhalb der Zeichenflaeche landen ───────────
    #  Sichtbar sind die Samples first..total-1. Gerechnet wurde gegen
    #  `total`, eine gerade gesetzte Marke kam damit auf count/(count-1) > 1
    #  heraus — und wurde rechts neben das Bild gezeichnet, also gar nicht.
    pb = PlotBridge()
    pb.setPointsCount(100)
    pb.append_block(np.zeros((100, 8), dtype=np.float32))
    pb.add_marker("Ereignis", 1)
    marken = pb.visible_markers(pb.pointsCount)
    check("Marke am rechten Rand bleibt sichtbar",
          len(marken) == 1 and 0.0 <= marken[0][0] <= 1.0, str(marken))

    # ── Die Trigger-Marke gehoert an die Ausloesestelle ───────────────────
    #  add_marker() laeuft NACH append_block(); ohne die uebergebene Stelle
    #  landete die Marke am Ende des ganzen Blocks statt an der Flanke.
    tp = PlotBridge()
    tp.setPointsCount(100)
    tp.setTriggerChannel(0)
    tp.setTriggerMode("above")
    tp.setTriggerLevel(0.5)
    tp.setTriggerMarkOnly(True)       # nur markieren, nicht einfrieren
    tp.setTriggerEnabled(True)
    tp.append_block(np.zeros((97, 8), dtype=np.float32))
    block = np.zeros((5, 8), dtype=np.float32)
    block[1:, 0] = 1.0                # ab Sample 1 des Blocks ueber der Schwelle
    tp.append_block(block)
    check("Trigger loest an der Flanke aus", tp._trig_fired_at == 98,
          str(tp._trig_fired_at))
    tmark = tp.visible_markers(tp.pointsCount)
    check("Trigger-Marke steht an der Ausloesestelle", len(tmark) == 1
          and abs(tmark[0][0] - (98 - (tp._total - 100)) / 99.0) < 1e-9,
          str(tmark))
    check("Trigger-Marke liegt im Bild", tmark and 0.0 <= tmark[0][0] <= 1.0)

    # ── controller_config.json darf die GUI nicht am Start hindern ────────
    #  Die Datei ist ausdruecklich zum Editieren von Hand gedacht. Ein
    #  Tippfehler lief bis zuletzt in float(self._map["deadzone"]) im
    #  Konstruktor und riss den kompletten Aufbau der Oberflaeche mit.
    import config
    import bridge.controller_bridge as cb

    original = config.CONTROLLER_CONFIG_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "controller_config.json"
            for inhalt, erwartet in (
                ({"deadzone": None}, cb.DEFAULT_MAPPING["deadzone"]),
                ({"deadzone": 1.5}, cb.DEFAULT_MAPPING["deadzone"]),
                ({"deadzone": "0.2"}, 0.2),
            ):
                path.write_text(json.dumps(inhalt), encoding="utf-8")
                cb.CONTROLLER_CONFIG_PATH = path
                m = cb._load_mapping()
                check(f"deadzone={inhalt['deadzone']!r} ergibt {erwartet}",
                      m["deadzone"] == erwartet, str(m["deadzone"]))

            path.write_text(json.dumps({"axis_r2": "fuenf", "axis_left_x": "3"}),
                             encoding="utf-8")
            cb.CONTROLLER_CONFIG_PATH = path
            m = cb._load_mapping()
            check("unlesbarer Achsenindex behaelt den Standardwert",
                  m["axis_r2"] == cb.DEFAULT_MAPPING["axis_r2"], str(m["axis_r2"]))
            check("Achsenindex als Text wird zu int",
                  m["axis_left_x"] == 3 and isinstance(m["axis_left_x"], int),
                  repr(m["axis_left_x"]))

            path.write_text('["kein", "objekt"]', encoding="utf-8")
            cb.CONTROLLER_CONFIG_PATH = path
            check("Datei ohne Objekt faellt auf das Standard-Mapping zurueck",
                  cb._load_mapping() == cb.DEFAULT_MAPPING)
    finally:
        cb.CONTROLLER_CONFIG_PATH = original
        config.CONTROLLER_CONFIG_PATH = original


def main() -> int:
    print("Power Debug System — Selbsttest")
    for fn in (test_wire_format, test_frame_assemblers, test_descriptor,
               test_param_io, test_bt_protocol, test_qml_bindings,
               test_aux_uplink, test_runtime_config, test_textgrid,
               test_overlay_editor, test_thread_attribute_clash,
               test_plot_markers_and_controller):
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
