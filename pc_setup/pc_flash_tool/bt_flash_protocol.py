#!/usr/bin/env python3
"""
bt_flash_protocol.py
=====================
Gemeinsames Byte-Frame-Protokoll für den Bluetooth-Flash-Kanal
(Windows-PC <-> RPi Zero 2 W). Diese Datei ist auf BEIDEN Seiten identisch:

  - PC:  pc_setup/pc_flash_tool/bt_flash_sender.py importiert sie aus ../../shared/
  - Pi:  rpi_zero_node/bt_flash_receiver.py importiert sie aus ../shared/
         (setup_node.sh kopiert sie mit nach /opt/power_debug_node/shared/)

Nur Python-Standardbibliothek (struct, zlib) — keine Abhängigkeiten, funktioniert
also unverändert unter Windows und unter Raspberry Pi OS (Bullseye ODER Bookworm).

Frame-Format (Little-Endian), siehe Flash_Implementierung.md Abschnitt 4:

    MAGIC (4 Byte) | CMD (1 Byte) | LEN (4 Byte) | PAYLOAD (LEN Byte) | CRC32 (4 Byte)

Hinweis zur Abweichung vom Plandokument: dort stand als Platzhalter der
ungültige Hex-Wert `0xB17F1A5H` (kein gültiges Hex, 'H' ist keine Hex-Ziffer).
Hier wird stattdessen der gültige, eindeutige Wert 0xB17F1A55 verwendet.
"""
from __future__ import annotations

import socket
import struct
import zlib

MAGIC = 0xB17F1A55

_HEADER = struct.Struct("<IBI")  # MAGIC, CMD, LEN
_TRAILER = struct.Struct("<I")   # CRC32
_MAGIC_BYTES = struct.pack("<I", MAGIC)


class Cmd:
    """Kommando-Bytes gemäß Flash_Implementierung.md Abschnitt 4."""
    HELLO = 0x01            # PC -> Pi: Auth-Token
    HELLO_ACK = 0x02        # Pi -> PC: {"ok": bool, "node_id": str, "msg": str}
    FLASH_START = 0x03      # PC -> Pi: {"filename": str, "size": int, "sha256": str}
    FLASH_START_ACK = 0x04  # Pi -> PC: {"ok": bool, "msg": str}
    DATA_CHUNK = 0x05       # PC -> Pi: rohe Bytes eines Datei-Chunks
    DATA_CHUNK_ACK = 0x06   # Pi -> PC: {"ok": bool, "received": int}
    FLASH_END = 0x07        # PC -> Pi: (kein Payload)
    FLASH_RESULT = 0x08     # Pi -> PC: {"ok": bool, "returncode": int, "output": str}
    PING = 0x09
    PONG = 0x0A


class ProtocolError(Exception):
    """Wird bei Verbindungsabbruch, CRC-Fehler oder Fehlsynchronisation ausgelöst."""


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProtocolError("Verbindung wurde während des Empfangs geschlossen")
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock: socket.socket, cmd: int, payload: bytes = b"") -> None:
    """Sendet ein vollständiges Frame (Header + Payload + CRC32) über den Socket."""
    header = _HEADER.pack(MAGIC, cmd, len(payload))
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    sock.sendall(header + payload + _TRAILER.pack(crc))


def recv_frame(sock: socket.socket, max_payload: int = 4 * 1024 * 1024) -> tuple[int, bytes]:
    """Empfängt ein vollständiges Frame. Sucht dabei byteweise nach MAGIC, um sich
    nach einer eventuellen Fehlsynchronisation (z. B. nach Verbindungsabbruch
    mitten in einem Frame) automatisch wieder einzufädeln."""
    window = bytearray()
    while bytes(window) != _MAGIC_BYTES:
        window.extend(_recv_exact(sock, 1))
        if len(window) > 4:
            del window[0]

    cmd_len = _recv_exact(sock, 5)
    cmd, length = struct.unpack("<BI", cmd_len)
    if length > max_payload:
        raise ProtocolError(f"Payload zu groß gemeldet: {length} Bytes")

    payload = _recv_exact(sock, length) if length else b""
    (crc_recv,) = _TRAILER.unpack(_recv_exact(sock, 4))
    crc_calc = zlib.crc32(payload) & 0xFFFFFFFF
    if crc_recv != crc_calc:
        raise ProtocolError("CRC32 der Payload stimmt nicht überein")

    return cmd, payload
