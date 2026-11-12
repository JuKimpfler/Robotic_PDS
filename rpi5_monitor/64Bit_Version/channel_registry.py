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
from udp_socket import open_udp_receiver

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
    # {"pds": "2.2", "fw": "...", "build": "...", "wire": 2, "channels": 200}
    meta:                   dict           = field(default_factory=dict)
    # Einstellungen der Oberflaeche, die der Teensy vorgibt (PDS 2.2):
    # Punktpfad -> Wert, z. B. {"ui.dark": True, "plotter.historySeconds": 20}.
    # Siehe app_settings.apply_teensy_settings().
    settings:               dict           = field(default_factory=dict)
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

        # Nur Skalare: alles andere kann der Teensy gar nicht schicken, und
        # was ueber UART/WLAN hereinkommt, wird grundsaetzlich geprueft und
        # nicht geglaubt. Die inhaltliche Pruefung (gibt es den Pfad? passt
        # der Typ?) macht app_settings.apply_teensy_settings().
        raw_settings = data.get("settings", {})
        settings = {}
        if isinstance(raw_settings, dict):
            settings = {k: v for k, v in raw_settings.items()
                        if isinstance(k, str) and k
                        and isinstance(v, (str, int, float, bool))}

        return cls(
            channel_names=_int_keyed(data.get("channels", {})),
            channel_units=_int_keyed(data.get("units", {})),
            param_slow_float_names=_int_keyed(data.get("param_slow_floats", {})),
            param_slow_bool_names=_int_keyed(data.get("param_slow_bools", {})),
            param_fast_float_names=_int_keyed(data.get("param_fast_floats", {})),
            overlays=overlays,
            param_cfg=param_cfg,
            meta=meta,
            settings=settings,
            received=True,
        )

    def is_empty(self) -> bool:
        return not (self.channel_names or self.param_slow_float_names
                    or self.param_slow_bool_names or self.param_fast_float_names
                    or self.overlays or self.param_cfg or self.settings)

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
        sock = open_udp_receiver(port)
    except OSError as exc:
        proc_log.error(f"UDP-Port {port} konnte nicht geöffnet werden: {exc} — läuft die GUI evtl. schon einmal?")
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

def _as_float(value, fallback: float) -> float:
    """Zahl aus dem Deskriptor, mit Rueckfall statt Ausnahme.

    Der Inhalt kommt ueber UART und WLAN und wird zusaetzlich aus einem
    `extra`-String zerlegt (siehe _parse_extra_kv) — dort steht also
    grundsaetzlich beliebiger Text. Ein `int()`/`float()` ohne Netz warf hier
    bis zuletzt bis in den Aufrufer hoch: im Poll-Timer wurde das nur geloggt
    (die Overlays des Teensy kamen dann nie an), im Slot
    `applyPendingTeensyConfig` beendete PyQt dagegen den ganzen Prozess.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if out != out else out


def _as_int(value, fallback: int) -> int:
    return int(_as_float(value, float(fallback)))


def _parse_extra_kv(extra: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in extra.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _truthy(text: str) -> bool:
    return str(text).strip().lower() not in ("", "0", "false", "nein", "off")


def _style_from_kv(kv: dict[str, str]) -> dict:
    """Darstellung einer Textbox aus dem `extra`-Text eines Teensy-Overlays.

    Die Schluessel sind bewusst kurz — jeder Buchstabe reist bei jedem
    Deskriptor ueber die UART-Leitung:

        color=#19f3ec   feste Farbe
        dec=0           Nachkommastellen
        size=11         Schriftgroesse (waechst mit dem Bild, siehe text_style)
        anchor=c        x/y ist die Mitte der Box (anchor=tl: linke obere Ecke)
        cmode=thr|lin   Box nach einem Kanalwert einfaerben:
                        thr = Schwelle (cthr), lin = Verlauf (cmin..cmax)
        cch=12          Kanal fuer die Farbe (fehlt = der angezeigte Kanal)
        clow / chigh    die beiden Farben

    Nur gesetzte Schluessel landen im Eintrag: was fehlt, behaelt die Vorgabe
    der GUI (bridge.utils.text_style) und macht die gespeicherte Datei nicht
    unnoetig lang.
    """
    out: dict = {}
    if kv.get("color", "").startswith("#"):
        out["color"] = kv["color"]
    if "dec" in kv:
        out["decimals"] = max(0, min(6, _as_int(kv["dec"], 2)))
    if "size" in kv:
        out["font_px"] = max(0.0, min(48.0, _as_float(kv["size"], 0.0)))
    if "anchor" in kv:
        out["centered"] = kv["anchor"].strip().lower() in ("c", "center", "mitte")
    mode = kv.get("cmode", "").strip().lower()
    if mode in ("thr", "threshold", "lin", "linear"):
        out["color_dynamic"] = True
        out["color_mode"] = "threshold" if mode.startswith("thr") else "linear"
        if "cch" in kv:
            out["color_channel"] = _as_int(kv["cch"], -1)
        for short, long, fallback in (("cthr", "color_threshold", 0.5),
                                      ("cmin", "color_min", 0.0),
                                      ("cmax", "color_max", 1.0)):
            if short in kv:
                out[long] = _as_float(kv[short], fallback)
        for short, long in (("clow", "color_low"), ("chigh", "color_high")):
            if kv.get(short, "").startswith("#"):
                out[long] = kv[short]
    return out


def _block_labels_from_kv(kv: dict[str, str]) -> dict:
    """Beschriftung der Zellen eines Blocks (textring/textpts):
    labels=0 -> nur Werte, prefix=IR -> IR1, IR2, … (first=1), sonst Kanalname."""
    out: dict = {"labels": _truthy(kv.get("labels", "1"))}
    if "prefix" in kv:
        out["prefix"] = kv["prefix"]
        if "first" in kv:
            out["first"] = _as_int(kv["first"], 1)
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
        entry = {
            "label": label,
            "channel_idx": _as_int(ov.get("channel"), 0),
            "x_pct": _as_float(ov.get("x_pct"), 5.0),
            "y_pct": _as_float(ov.get("y_pct"), 5.0),
            "color": "#4ec9b0",
        }
        entry.update(_style_from_kv(_parse_extra_kv(ov.get("extra", ""))))
        return "overlays", entry

    if t == "textring":
        # Viele Werte gleichmaessig auf einem Kreis — siehe
        # bridge.utils.expand_textring. x_pct/y_pct ist der Mittelpunkt.
        kv = _parse_extra_kv(ov.get("extra", ""))
        entry = {
            "type": "textring",
            "label": label,
            "channels": kv.get("channels", ""),
            "r_pct": _as_float(kv.get("r"), 40.0),
            "ry_pct": _as_float(kv.get("ry"), 0.0),
            "start_deg": _as_float(kv.get("start"), 0.0),
            "step_deg": _as_float(kv.get("step"), 0.0),
            "x_pct": _as_float(ov.get("x_pct"), 50.0),
            "y_pct": _as_float(ov.get("y_pct"), 50.0),
            "color": "#4ec9b0",
            "centered": True,
        }
        entry.update(_block_labels_from_kv(kv))
        entry.update(_style_from_kv(kv))
        return "overlays", entry

    if t == "textpts":
        # Viele Werte an frei vorgegebenen Punkten, als EIN Eintrag — siehe
        # bridge.utils.expand_textpts. x_pct/y_pct ist hier ein VERSATZ und
        # deshalb ohne Angabe 0 (nicht -1 wie "ungenutzt" im Deskriptor).
        kv = _parse_extra_kv(ov.get("extra", ""))
        entry = {
            "type": "textpts",
            "label": label,
            "channels": kv.get("channels", ""),
            "points": kv.get("pts", ""),
            "x_pct": _as_float(ov.get("x_pct"), 0.0),
            "y_pct": _as_float(ov.get("y_pct"), 0.0),
            "color": "#4ec9b0",
            "centered": True,
        }
        entry.update(_block_labels_from_kv(kv))
        entry.update(_style_from_kv(kv))
        return "overlays", entry

    if t == "textgrid":
        # Ein einziger Eintrag erzeugt beliebig viele Textfelder — genau
        # dafuer gedacht, dass man bei 30 Messwerten nicht 30 Overlays mit
        # je eigener Position pflegen muss. Die Aufloesung in Einzelfelder
        # passiert erst in der GUI (visuals_bridge.expand_textgrid), damit
        # die gespeicherte Konfiguration kompakt und lesbar bleibt.
        kv = _parse_extra_kv(ov.get("extra", ""))
        entry = {
            "type": "textgrid",
            "label": label,
            "channels": kv.get("channels", ""),
            "cols": max(1, _as_int(kv.get("cols"), 1)),
            "dx_pct": _as_float(kv.get("dx"), 20.0),
            "dy_pct": _as_float(kv.get("dy"), 4.5),
            "labels": kv.get("labels", "1") not in ("0", "false", "False"),
            "x_pct": _as_float(ov.get("x_pct"), 4.0),
            "y_pct": _as_float(ov.get("y_pct"), 6.0),
            "color": "#4ec9b0",
        }
        entry.update(_style_from_kv(kv))
        return "overlays", entry

    if t == "gauge":
        return "graphics", {
            "type": "gauge",
            "label": label,
            "channel": _as_int(ov.get("channel"), 0),
            "min": _as_float(ov.get("min"), -1.0),
            "max": _as_float(ov.get("max"), 1.0),
        }

    if t == "rotation":
        entry = {"type": "rotation", "label": label,
                 "channel": _as_int(ov.get("channel"), 0)}
        if "max" in ov:
            entry["max_val"] = _as_float(ov["max"], 5.0)
        return "graphics", entry

    if t == "vector":
        return "graphics", {
            "type": "vector",
            "label": label,
            "channel_angle": _as_int(ov.get("channel"), -1),
            "channel_speed": _as_int(ov.get("channel2"), -1),
            "max_val": _as_float(ov.get("max"), 1.0),
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
                "diameter": _as_float(kv.get(f"{prefix}_diameter"), 18.0),
                "channel_x": _as_int(kv.get(f"{prefix}_channel_x"), -1),
                "channel_y": _as_int(kv.get(f"{prefix}_channel_y"), -1),
                "channel_angle": _as_int(kv.get(f"{prefix}_channel_angle"), -1),
                "channel_diameter": _as_int(kv.get(f"{prefix}_channel_diameter"), -1),
            }

        # Feldmasse in ZENTIMETERN, in derselben Einheit wie die Kanalwerte:
        #   x = 0..field_x_cm nach rechts, y = 0..field_y_cm nach oben.
        #
        # field_width/field_height sind das Altformat und meinen DIESELBE
        # Einheit, nicht Meter. Die zwischenzeitliche Multiplikation mit 100
        # machte aus einem 240 x 180 cm grossen Feld ein 240 x 180 METER
        # grosses: das Tor war dann 0,25 % einer Kante breit und die
        # Rasterlinien alle 30 cm verschmolzen zu einer Flaeche.
        if "field_x_cm" in kv or "field_y_cm" in kv:
            field_x = _as_float(kv.get("field_x_cm"), 240.0)
            field_y = _as_float(kv.get("field_y_cm"), 180.0)
        else:
            field_x = _as_float(kv.get("field_width"), 240.0)
            field_y = _as_float(kv.get("field_height"), 180.0)

        entry = {
            "type": "bodies",
            "label": label,
            "field_x_cm": field_x,
            "field_y_cm": field_y,
            "body1": _body("body1"),
            "body2": _body("body2"),
        }
        # Optional, sonst gelten die Vorgaben der Feldansicht.
        if "goal_width_cm" in kv:
            entry["goal_width_cm"] = _as_float(kv["goal_width_cm"], 45.0)
        if "goal_depth_cm" in kv:
            entry["goal_depth_cm"] = _as_float(kv["goal_depth_cm"], 10.0)
        if "show_image" in kv:
            entry["show_image"] = _truthy(kv["show_image"])
        return "graphics", entry

    return "graphics", {"type": t, "label": label}


# ── Ansichten (Gruppen) vom Teensy ────────────────────────────────────────
#  Ein Overlay vom Typ "group" ist kein Anzeige-Element, sondern BESCHREIBT
#  eine Ansicht:
#
#      { 3, "group", "IR-Ring", -1, -1, 0, 0, -1, -1, "image=3" }
#
#  -> Ansicht 3 heisst "IR-Ring" und liegt auf bild/Bild3.png. Ohne solche
#  Eintraege gilt das alte Verhalten: die Gruppen der lokalen Datei bleiben
#  stehen und werden ueber ihre Bildnummer befuellt. MIT ihnen bestimmt der
#  Teensy die Liste der Ansichten vollstaendig — Reihenfolge, Name und Bild.
#  Nur so kann die Firmware eine fuenfte Ansicht anlegen oder eine umbenennen,
#  ohne dass jemand an der GUI eine Datei anfasst.

def _group_defs(overlays: list[dict]) -> list[dict]:
    """[{id, name, image_idx}] in der Reihenfolge der Firmware. Leer, wenn der
    Teensy keine Ansichten beschreibt."""
    defs: list[dict] = []
    seen: set[int] = set()
    for ov in overlays:
        if ov.get("type") != "group":
            continue
        gid = _as_int(ov.get("group"), 1)
        if gid in seen:
            continue
        seen.add(gid)
        kv = _parse_extra_kv(str(ov.get("extra", "")))
        defs.append({
            "id": gid,
            "name": str(ov.get("label") or f"Gruppe {gid}"),
            "image_idx": max(1, _as_int(kv.get("image"), gid)),
        })
    return defs


def _groups_from_teensy(overlays: list[dict], defs: list[dict]) -> list[dict]:
    by_group: dict[int, list[dict]] = {}
    for ov in overlays:
        if ov.get("type") == "group":
            continue
        by_group.setdefault(_as_int(ov.get("group"), 1), []).append(ov)

    # Eintraege, deren Gruppe nirgends beschrieben ist, duerfen nicht still
    # verschwinden — sie bekommen eine Ansicht mit Standardnamen.
    known = {d["id"] for d in defs}
    for gid in sorted(by_group):
        if gid not in known:
            defs = defs + [{"id": gid, "name": f"Gruppe {gid}", "image_idx": gid}]

    groups: list[dict] = []
    for d in defs:
        overlays_out: list[dict] = []
        graphics_out: list[dict] = []
        for ov in by_group.get(d["id"], []):
            target, entry = _teensy_overlay_to_entry(ov)
            (overlays_out if target == "overlays" else graphics_out).append(entry)
        groups.append({"name": d["name"], "image_idx": d["image_idx"],
                       "overlays": overlays_out, "graphics": graphics_out})
    return groups


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

    # Beschreibt der Teensy seine Ansichten selbst ("group"-Eintraege), ersetzt
    # seine Liste die lokale komplett — siehe _group_defs().
    defs = _group_defs(registry.overlays)
    if defs:
        local_groups = local_config.get("groups", [])
        filled = any(isinstance(g, dict) and (g.get("overlays") or g.get("graphics"))
                     for g in local_groups) if isinstance(local_groups, list) else False
        if filled and not overwrite:
            return False
        local_config["groups"] = _groups_from_teensy(registry.overlays, defs)
        return True

    by_group: dict[int, list[dict]] = {}
    for ov in registry.overlays:
        by_group.setdefault(_as_int(ov.get("group"), 1), []).append(ov)

    changed = False
    for group in local_config.get("groups", []):
        if not overwrite and (group.get("overlays") or group.get("graphics")):
            continue   # bereits befuellt -- nicht ueberschreiben

        entries = by_group.get(_as_int(group.get("image_idx"), 1))
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
