#!/usr/bin/env python3
"""
uart_receiver.py — RPi Zero W Node  (v6 — Unicast-Telemetrie + Fast-Coalescing)
==========================================================
Liest Binärpakete vom Teensy 4.0 über UART und leitet sie sofort als
UDP-Datagramm an den RPi 5 weiter. Empfängt außerdem zwei Param-Downlink-
Streams (Slow + Fast) vom RPi 5 und reicht sie unverändert über UART_DBG-TX
an den Teensy weiter.

────────────────────────────────────────────────────────────────────────────
WAS v6 GEGENÜBER v5 ÄNDERT (Bugfix: Latenz der Fernsteuerung):
────────────────────────────────────────────────────────────────────────────
1. TELEMETRIE PER UNICAST STATT BROADCAST.
   v5 hat jedes Telemetriepaket (808 B, 100 Hz = 80.8 kB/s) an
   255.255.255.255 geschickt. WLAN sendet Broadcast-/Multicast-Frames
   zwingend mit der niedrigsten Basisrate des BSS, ohne MAC-Level-ACK und
   ohne Frame-Aggregation. Bei 6 Mbit/s Basisrate belegt ein Node damit
   grob 10-15 % der Funkzeit, bei 1 Mbit/s ein Vielfaches davon — mit zwei
   Nodes ist der Kanal praktisch dicht. Die 28-Byte-Fast-Pakete (Joystick/
   Controller) in der Gegenrichtung stehen dann in der Sendewarteschlange
   des Access Points an und kommen verzögert und stoßweise an: genau das
   spürbare "Steuerung reagiert träge/ruckelig".
   v6 lernt die Adresse der GUI aus den eingehenden Param-Paketen und
   schickt die Telemetrie danach per Unicast dorthin (volle MCS-Rate,
   Aggregation, ARQ). Solange noch nichts gelernt wurde — und wenn länger
   als DEST_LEARN_TIMEOUT nichts mehr von der GUI kam — bleibt es beim
   bisherigen Broadcast, das Verhalten ist also nie schlechter als v5.

2. NUR DAS JEWEILS NEUESTE FAST-PAKET WIRD WEITERGEREICHT.
   Lagen mehrere Fast-Pakete im Socket-Puffer (WLAN liefert sie gern in
   Bündeln aus), hat v5 sie alle nacheinander über die UART geschoben. Der
   Teensy hat dann veraltete Joystick-Stände abgearbeitet, bevor er beim
   aktuellen ankam. v6 verwirft die überholten Pakete sofort — beim
   Fast-Kanal zählt ausschließlich der neueste Stand.

3. KEIN subprocess-FORK MEHR IM 15-Sekunden-Takt.
   Der WLAN-Check hat "ip addr show wlan0" gestartet, also den kompletten
   Python-Prozess geforkt. Auf dem RPi Zero 2 W ist das ein spürbarer
   Aussetzer mitten im 100-Hz-Betrieb. Jetzt per ioctl(SIOCGIFADDR).

────────────────────────────────────────────────────────────────────────────
WARUM v5 EIN KOMPLETTER UMBAU WAR (Bugfix für Throughput-Einbruch):
────────────────────────────────────────────────────────────────────────────
In v4 liefen UART-Reader, NetworkMonitor, ParamDownlinkSlow und
ParamDownlinkFast als VIER separate Python-Threads. Sobald der Fast-Kanal
(100 Hz) aktiv gesendet hat, ist die Telemetrie-Rate von 100 auf ca. 70
Pakete/s eingebrochen — das war kein Bandbreiten- oder Kabelproblem
(2.8 kB/s Fast-Traffic sind nichts gegen die ~100 kB/s Baud-Budget),
sondern ein GIL-Scheduling-Problem: CPython fuehrt nur EINEN Thread
gleichzeitig aus. Der Fast-Downlink-Thread wachte 100x/s auf und hat dem
UART-Reader-Thread Ausfuehrungszeit auf dem schwachen Cortex-A53-Kern des
RPi Zero 2 W weggenommen. Geriet der Reader dadurch kurz in Verzug, war die
(alte) Resync-Logik selbst wieder teuer (Byte-fuer-Byte-Lesen), was den
Effekt verstaerkt hat.

v5 loest das strukturell: ALLES (UART lesen/schreiben, beide UDP-Ports)
laeuft in EINEM einzigen Thread ueber eine `selectors`-Event-Loop (wie
select/epoll). Es gibt keine konkurrierenden Python-Threads mehr, also auch
keine GIL-Umschaltung zwischen ihnen. Zusaetzlich ersetzt ein einfacher
Puffer-Zustandsautomat (TelemetryFrameAssembler) die alte byte-fuer-byte
Resync-Schleife durch ein effizientes bytearray.find()-basiertes Verfahren.

Umgebungsvariablen:
    NODE_ID   = 1 oder 2  (Standard: 1)
    RPI5_IP   = erwartete IP des RPi 5 (Standard: 192.168.42.1). Nur
                Anzeige/Log — welches Ziel tatsaechlich verwendet wird,
                ergibt sich aus den eingehenden Param-Paketen (siehe
                TelemetryTarget).
    PDS_TELEMETRY_DEST      = feste Ziel-IP erzwingen (kein Lernen, kein
                              Broadcast). Nuetzlich fuer feste Setups.
    PDS_TELEMETRY_BROADCAST = "1" -> immer Broadcast wie in v5 (Notnagel,
                              falls das Lernen in einem exotischen Netz
                              nicht funktioniert).

Paket-Format (vom Teensy, Telemetrie):
    [Header: 4 Bytes = 0xDEADBEEF][Timestamp: 4 Bytes][Data: 200 × float32]
    Gesamt: 808 Bytes   (bei MAX_FLOATS=200 — siehe PDS.cpp)

Param-Downlink (vom RPi 5, Gegenrichtung):
    Slow-Kanal (Port 700X): 50 Floats + 50 Bools, 2 Hz    (Magic 0xCAFEFEED, 258 B)
    Fast-Kanal (Port 701X): 5 Floats, 100 Hz               (Magic 0xFA57DA7A, 28 B)

Verdrahtung (Teensy-Seite = UART_DBG, per Default Serial3 -> Pin 14/15;
siehe teensy_firmware/src/params.h):
    RPi GPIO15 (Pin 10, UART RX) ←── Teensy Pin 14 (TX3)
    RPi GPIO14 (Pin  8, UART TX) ──→ Teensy Pin 15 (RX3)  [Pflicht fuer Param-Downlink]
    GND (Pin 6)                  ───  GND

UART-Einrichtung (RPi Zero W, einmalig):
    /boot/firmware/config.txt:
        dtoverlay=disable-bt    ← PL011 UART auf GPIO14/15 (BT deaktiviert)
        enable_uart=1
    /boot/firmware/cmdline.txt:
        console=serial0,115200  ← DIESE ZEILE ENTFERNEN (kein Login-Prompt)
    Danach: sudo reboot
"""

import os
import time
import socket
import struct
import logging
import selectors

try:
    import fcntl          # nur Linux — auf dem Node immer vorhanden
except ImportError:       # pragma: no cover  (erlaubt Import/Lint unter Windows)
    fcntl = None

import serial

# status_leds.py liegt im selben Verzeichnis. Fehlt es (oder fehlt gpiozero),
# liefert der Import-Fallback eine funktionslose Attrappe — die Weiterleitung
# darf niemals an den LEDs scheitern.
try:
    from status_leds import StatusLEDs
except Exception:         # pragma: no cover
    class StatusLEDs:     # type: ignore[no-redef]
        def start(self) -> None: ...
        def stop(self) -> None: ...
        def startup_sequence(self) -> None: ...
        def set_network(self, connected: bool) -> None: ...
        def blink_data(self) -> None: ...

# ── Konfiguration: Telemetrie ────────────────────────────────────────────────
NODE_ID      = int(os.environ.get("NODE_ID", "1"))
RPI5_IP      = os.environ.get("RPI5_IP", "192.168.42.1")
UDP_PORT     = 5000 + NODE_ID          # 5001 oder 5002

# Ziel-Auswahl fuer den Telemetrie-Uplink (siehe Modul-Docstring, Punkt 1)
FORCED_DEST        = os.environ.get("PDS_TELEMETRY_DEST", "").strip()
FORCE_BROADCAST    = os.environ.get("PDS_TELEMETRY_BROADCAST", "").strip() == "1"
BROADCAST_ADDR     = "255.255.255.255"
DEST_LEARN_TIMEOUT = 10.0   # s ohne Param-Paket -> zurueck auf Broadcast

UART_PORT    = "/dev/ttyAMA0"          # PL011 Full-UART (nach dtoverlay=disable-bt)
UART_BAUD    = 1_000_000               # 1 Mbps — muss mit params.h (UART_DBG_BAUD) übereinstimmen!

MAX_FLOATS   = 200                     # Muss mit Teensy PDS.cpp (MAX_FLOATS) übereinstimmen!
HEADER_SIZE  = 8                       # uint32 magic + uint32 timestamp
PACKET_BYTES = HEADER_SIZE + MAX_FLOATS * 4   # 808 Bytes (bei MAX_FLOATS=200)

MAGIC        = 0xDEADBEEF
MAGIC_BYTES  = struct.pack("<I", MAGIC)

NET_CHECK_INTERVAL = 15.0   # Sekunden
STAT_LOG_INTERVAL  = 4.0    # Sekunden

# ── Konfiguration: Param-Downlink ────────────────────────────────────────────
# Muss exakt mit params.h (Teensy) und config.py (RPi 5) übereinstimmen!

PARAM_SLOW_MAGIC        = 0xCAFEFEED
PARAM_SLOW_MAGIC_BYTES  = struct.pack("<I", PARAM_SLOW_MAGIC)
PARAM_SLOW_FLOAT_COUNT  = 50
PARAM_SLOW_BOOL_COUNT   = 50
PARAM_SLOW_PACKET_BYTES = HEADER_SIZE + PARAM_SLOW_FLOAT_COUNT * 4 + PARAM_SLOW_BOOL_COUNT   # 258
UDP_PARAM_SLOW_PORT     = 7000 + NODE_ID   # 7001 / 7002

PARAM_FAST_MAGIC        = 0xFA57DA7A
PARAM_FAST_MAGIC_BYTES  = struct.pack("<I", PARAM_FAST_MAGIC)
PARAM_FAST_FLOAT_COUNT  = 5
PARAM_FAST_PACKET_BYTES = HEADER_SIZE + PARAM_FAST_FLOAT_COUNT * 4                            # 28
UDP_PARAM_FAST_PORT     = 7010 + NODE_ID   # 7011 / 7012

# ── Konfiguration: Namens-/Overlay-Deskriptor ────────────────────────────────
# Muss exakt mit params.h (Teensy) und config.py (RPi 5) übereinstimmen!
# Teensy -> GUI: gechunktes JSON (Kanal-/Param-Namen + Overlay-Zuordnung),
# einmalig beim Boot + auf Anfrage. GUI -> Teensy: 4-Byte Request ohne Payload.

CHANNEL_DESC_MAGIC          = 0xDE5C0001
CHANNEL_DESC_MAGIC_BYTES    = struct.pack("<I", CHANNEL_DESC_MAGIC)
CHANNEL_DESC_HEADER_BYTES   = 7    # magic(4) + chunk_idx(1) + chunk_count(1) + payload_len(1)
CHANNEL_DESC_CHUNK_PAYLOAD_MAX = 250   # muss mit params.h uebereinstimmen
UDP_CHANNEL_DESC_PORT       = 5010 + NODE_ID   # 5011 / 5012

CHANNEL_DESC_REQUEST_MAGIC        = 0xDE5C00F0
CHANNEL_DESC_REQUEST_MAGIC_BYTES  = struct.pack("<I", CHANNEL_DESC_REQUEST_MAGIC)
CHANNEL_DESC_REQUEST_PACKET_BYTES = 4    # nur Magic, kein Payload
UDP_CHANNEL_DESC_REQUEST_PORT     = 7020 + NODE_ID   # 7021 / 7022

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format=f"[uart_rx Node{NODE_ID}] %(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger()


# ══════════════════════════════════════════════════════════════════════════════
#  TelemetryFrameAssembler — ersetzt die alte byte-für-byte Resync-Schleife
# ══════════════════════════════════════════════════════════════════════════════

class TelemetryFrameAssembler:
    """
    Nimmt beliebig große, beliebig geschnittene Byte-Chunks entgegen (wie sie
    von einem nicht-blockierenden UART-Read zurückkommen) und liefert
    vollständige Telemetrie-Pakete zurück, sobald sie komplett sind.

    Nutzt bytearray.find() für die Magic-Suche statt einer Python-Schleife
    mit Einzelbyte-Reads — das ist der Teil, der in v4 bei Sync-Verlust
    unverhältnismäßig teuer war und zum GIL-Kontentions-Teufelskreis
    beigetragen hat (siehe Modul-Docstring).
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.sync_losses = 0
        self.packets_out = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        self._buf.extend(chunk)
        packets: list[bytes] = []

        while True:
            idx = self._buf.find(MAGIC_BYTES)
            if idx == -1:
                # Kein vollständiger Magic im Puffer -- die letzten 3 Bytes
                # könnten der Anfang eines noch nicht komplett angekommenen
                # Magic sein, den Rest können wir gefahrlos verwerfen.
                if len(self._buf) > 3:
                    del self._buf[:-3]
                break

            if idx > 0:
                # Byte-Müll vor dem Magic -- Sync-Verlust zählen und verwerfen
                self.sync_losses += 1
                del self._buf[:idx]

            if len(self._buf) < PACKET_BYTES:
                break   # Paket ist noch nicht vollständig angekommen

            packets.append(bytes(self._buf[:PACKET_BYTES]))
            del self._buf[:PACKET_BYTES]
            self.packets_out += 1

        return packets


# ══════════════════════════════════════════════════════════════════════════════
#  ChunkFrameAssembler — wie TelemetryFrameAssembler, aber variable Laenge
# ══════════════════════════════════════════════════════════════════════════════

class ChunkFrameAssembler:
    """
    Setzt Namens-/Overlay-Deskriptor-Chunks (variable Laenge, siehe
    channel_config.h/PDS.cpp auf dem Teensy) aus dem UART-Bytestrom zusammen.

    Anders als TelemetryFrameAssembler (feste Paketgroesse) traegt hier der
    Header selbst die Payload-Laenge (payload_len-Byte an Offset 6), da der
    letzte Chunk eines Deskriptors fast immer kuerzer ist als die anderen.

    Läuft unabhängig neben TelemetryFrameAssembler auf demselben Rohbyte-Strom
    (beide bekommen denselben ser.read()-Chunk): Bytes, die nicht zum eigenen
    Magic gehören, werden verworfen -- das ist unproblematisch, da
    Telemetrie-Header (0xDEADBEEF) und Deskriptor-Header (0xDE5C0001, gefolgt
    von reinem ASCII-JSON) sich nicht überschneiden können.

    Optimierung: Solange KEIN Deskriptor unterwegs ist (der Normalfall — der
    Teensy sendet ihn nur beim Boot und auf Anfrage), landet der komplette
    80-kB/s-Telemetriestrom hier trotzdem an. Statt ihn wie bisher in einen
    wachsenden bytearray zu kopieren und anschliessend wieder zu beschneiden,
    wird jetzt nur noch direkt auf dem Eingangs-Chunk gesucht und lediglich
    dessen letzte 3 Bytes gemerkt (ein Magic koennte ueber die Chunk-Grenze
    hinweg zerschnitten sein). Erst wenn wirklich ein Magic auftaucht, wird
    gepuffert.
    """

    def __init__(self) -> None:
        self._buf = bytearray()   # nur belegt, solange ein Chunk unvollstaendig ist
        self._tail = b""          # letzte <=3 Bytes des vorherigen Blocks
        self.packets_out = 0
        self.false_magics = 0     # Zufallstreffer im Telemetriestrom

    @staticmethod
    def _header_plausible(buf) -> bool:
        """Plausibilitaetspruefung des Chunk-Headers.

        Der Deskriptor-Assembler laeuft auf demselben Rohbyte-Strom wie die
        Telemetrie. Deren Nutzdaten sind beliebige Float-Bytes — mit kleiner,
        aber nicht verschwindender Wahrscheinlichkeit steht darin irgendwann
        zufaellig die 4-Byte-Folge des Deskriptor-Magic. Ohne diese Pruefung
        haette der Node daraufhin ein Muellpaket an die GUI geschickt, das
        dort einen gerade laufenden Deskriptor-Zusammenbau zerstoert.
        chunk_idx < chunk_count und payload_len <= MAX sortieren praktisch
        alle Zufallstreffer aus.
        """
        chunk_idx, chunk_count, payload_len = buf[4], buf[5], buf[6]
        return (chunk_count > 0
                and chunk_idx < chunk_count
                and payload_len <= CHANNEL_DESC_CHUNK_PAYLOAD_MAX)

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []

        if not self._buf:
            # Suchmodus: nur pruefen, ob ueberhaupt ein Magic im Strom ist.
            probe = (self._tail + chunk) if self._tail else chunk
            idx = probe.find(CHANNEL_DESC_MAGIC_BYTES)
            if idx < 0:
                self._tail = probe[-3:]
                return []
            self._buf.extend(probe[idx:])
            self._tail = b""
        else:
            self._buf.extend(chunk)

        packets: list[bytes] = []

        while True:
            idx = self._buf.find(CHANNEL_DESC_MAGIC_BYTES)
            if idx < 0:
                # Nur noch Fremdbytes im Puffer -> zurueck in den Suchmodus
                self._tail = bytes(self._buf[-3:])
                self._buf.clear()
                break

            if idx > 0:
                del self._buf[:idx]

            if len(self._buf) < CHANNEL_DESC_HEADER_BYTES:
                break   # Header noch nicht vollständig da

            if not self._header_plausible(self._buf):
                # Zufallstreffer: ein Byte weiterruecken und neu suchen.
                self.false_magics += 1
                del self._buf[:1]
                continue

            payload_len = self._buf[6]
            total_len = CHANNEL_DESC_HEADER_BYTES + payload_len

            if len(self._buf) < total_len:
                break   # Chunk noch nicht vollständig angekommen

            packets.append(bytes(self._buf[:total_len]))
            del self._buf[:total_len]
            self.packets_out += 1

        return packets


# ══════════════════════════════════════════════════════════════════════════════
#  Netzwerk-Check — ohne Prozess-Fork
# ══════════════════════════════════════════════════════════════════════════════

_SIOCGIFADDR = 0x8915   # linux/sockios.h


def _wlan_ip(iface: str = "wlan0") -> str | None:
    """IPv4-Adresse eines Interfaces oder None (kein DHCP-Lease).

    Frueher via subprocess "ip addr show wlan0" — das forkt den kompletten
    Python-Prozess und erzeugt auf dem RPi Zero 2 W einen Aussetzer von
    zig Millisekunden mitten im 100-Hz-Weiterleitungsbetrieb. Der ioctl
    kostet dagegen nichts.
    """
    if fcntl is None:
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = fcntl.ioctl(
            sock.fileno(), _SIOCGIFADDR,
            struct.pack("256s", iface.encode("utf-8")[:15]),
        )
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return None
    finally:
        sock.close()


# ══════════════════════════════════════════════════════════════════════════════
#  TelemetryTarget — wohin der Uplink geht (siehe Modul-Docstring, Punkt 1)
# ══════════════════════════════════════════════════════════════════════════════

class TelemetryTarget:
    """Bestimmt die Ziel-IP fuer Telemetrie- und Deskriptor-Pakete.

    Reihenfolge:
      1. PDS_TELEMETRY_BROADCAST=1  -> immer Broadcast (altes v5-Verhalten)
      2. PDS_TELEMETRY_DEST=<ip>    -> immer diese Adresse
      3. Adresse, von der zuletzt ein Param-/Deskriptor-Paket kam (Unicast)
      4. Broadcast, solange nichts gelernt wurde bzw. die gelernte Adresse
         laenger als DEST_LEARN_TIMEOUT stumm ist

    Punkt 4 ist die Sicherheitsleine: schlimmstenfalls verhaelt sich der Node
    exakt wie vorher, es kann also nichts ausfallen, was vorher lief.
    """

    def __init__(self) -> None:
        self._learned: str | None = None
        self._last_seen = 0.0
        self.changes = 0

    def note_sender(self, addr: str) -> None:
        """Adresse aus einem eingehenden Paket der GUI uebernehmen."""
        self._last_seen = time.monotonic()
        if addr != self._learned:
            log.info(
                "Telemetrie-Ziel: %s -> %s (Unicast statt Broadcast)",
                self._learned or "Broadcast", addr,
            )
            self._learned = addr
            self.changes += 1

    def resolve(self) -> str:
        if FORCE_BROADCAST:
            return BROADCAST_ADDR
        if FORCED_DEST:
            return FORCED_DEST
        if self._learned is None:
            return BROADCAST_ADDR
        if time.monotonic() - self._last_seen > DEST_LEARN_TIMEOUT:
            log.warning(
                "Seit %.0f s kein Param-Paket von %s — zurueck auf Broadcast.",
                DEST_LEARN_TIMEOUT, self._learned,
            )
            self._learned = None
            return BROADCAST_ADDR
        return self._learned

    @property
    def is_broadcast(self) -> bool:
        return self.resolve() == BROADCAST_ADDR


# ══════════════════════════════════════════════════════════════════════════════
#  UART öffnen / nach einem Fehler neu öffnen
# ══════════════════════════════════════════════════════════════════════════════

def _open_uart() -> "serial.Serial":
    ser = serial.Serial(
        port         = UART_PORT,
        baudrate     = UART_BAUD,
        bytesize     = serial.EIGHTBITS,
        parity       = serial.PARITY_NONE,
        stopbits     = serial.STOPBITS_ONE,
        timeout      = 0,      # nicht-blockierend: read() liefert sofort, was da ist
        # write_timeout war 0 (nicht-blockierend). pyserial gibt dann bei
        # einem vollen Kernel-Puffer die Zahl der TATSAECHLICH geschriebenen
        # Bytes zurueck, ohne Fehler -- ein halb geschriebenes Param-Paket
        # bringt den Teensy-Parser aus dem Tritt. Der Downlink ist mit
        # ~3.3 kB/s gegen 100 kB/s Leitungskapazitaet so schmal, dass dieser
        # Fall praktisch nie eintritt; falls doch, wartet write() jetzt lieber
        # kurz, statt den Bytestrom zu zerreissen.
        write_timeout = 0.05,
        xonxoff      = False,
        rtscts       = False,
        dsrdtr       = False,
    )
    ser.reset_input_buffer()
    return ser


# ══════════════════════════════════════════════════════════════════════════════
#  Hauptfunktion — einthreadige Event-Loop
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info(
        f"Starte | NODE_ID={NODE_ID} | UDP-Port {UDP_PORT} | erwarteter RPi5: {RPI5_IP} | "
        f"UART {UART_PORT} @ {UART_BAUD // 1_000_000} Mbps | "
        f"{PACKET_BYTES} Bytes/Paket | {MAX_FLOATS} Floats"
    )
    log.info(
        f"Param-Downlink | Slow: UDP :{UDP_PARAM_SLOW_PORT} -> {PARAM_SLOW_PACKET_BYTES} B | "
        f"Fast: UDP :{UDP_PARAM_FAST_PORT} -> {PARAM_FAST_PACKET_BYTES} B"
    )
    log.info(
        f"Namens-/Overlay-Deskriptor | Chunks: UDP :{UDP_CHANNEL_DESC_PORT} | "
        f"Request: UDP :{UDP_CHANNEL_DESC_REQUEST_PORT}"
    )
    if FORCE_BROADCAST:
        log.info("v6: Telemetrie-Ziel = Broadcast (PDS_TELEMETRY_BROADCAST=1 erzwungen)")
    elif FORCED_DEST:
        log.info(f"v6: Telemetrie-Ziel = {FORCED_DEST} (PDS_TELEMETRY_DEST erzwungen)")
    else:
        log.info("v6: Telemetrie-Ziel wird aus den Param-Paketen der GUI gelernt "
                 "(bis dahin Broadcast)")

    # ── UART öffnen (nicht-blockierend lesen: timeout=0 -> read() kehrt sofort zurück) ──
    try:
        ser = _open_uart()
    except serial.SerialException as exc:
        log.error(f"UART {UART_PORT} konnte nicht geöffnet werden: {exc}")
        log.error("→ Prüfe: dtoverlay=miniuart-bt in /boot/firmware/config.txt?")
        log.error("→ Prüfe: console=serial0,... in cmdline.txt entfernt?")
        raise SystemExit(1)

    log.info(f"UART {UART_PORT} geöffnet — warte auf ersten Teensy-Frame...")

    # ── UDP Socket (Telemetrie, Broadcast an RPi 5) ─────────────────────────────
    udp_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_out.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)
    udp_out.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # ── UDP Sockets (Param-Downlink, empfangend, nicht-blockierend) ────────────
    slow_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    slow_sock.setblocking(False)
    slow_sock.bind(("0.0.0.0", UDP_PARAM_SLOW_PORT))

    fast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fast_sock.setblocking(False)
    fast_sock.bind(("0.0.0.0", UDP_PARAM_FAST_PORT))

    # ── UDP Socket (Deskriptor-Request, empfangend, nicht-blockierend) ─────────
    desc_request_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    desc_request_sock.setblocking(False)
    desc_request_sock.bind(("0.0.0.0", UDP_CHANNEL_DESC_REQUEST_PORT))

    # ── Event-Loop: alle vier Quellen (UART, 3× UDP) über EINEN Selector ──────
    sel = selectors.DefaultSelector()
    sel.register(ser.fileno(), selectors.EVENT_READ, data="uart")
    sel.register(slow_sock, selectors.EVENT_READ, data="param_slow")
    sel.register(fast_sock, selectors.EVENT_READ, data="param_fast")
    sel.register(desc_request_sock, selectors.EVENT_READ, data="desc_request")

    assembler = TelemetryFrameAssembler()
    desc_assembler = ChunkFrameAssembler()
    target = TelemetryTarget()

    # ── Status-LEDs (optional, siehe status_leds.py) ───────────────────────────
    leds = StatusLEDs()
    leds.start()
    leds.startup_sequence()

    # ── Statistik ────────────────────────────────────────────────────────────
    pkt_sent      = 0
    bytes_sent    = 0
    send_errors   = 0
    fwd_slow_ok   = 0
    fwd_fast_ok   = 0
    fwd_bad       = 0
    fwd_stale     = 0   # ueberholte Fast-Pakete, bewusst verworfen
    fwd_desc_req  = 0
    desc_pkt_sent = 0
    last_sync_losses = 0

    t_stat_start     = time.monotonic()
    t_last_netcheck  = time.monotonic()
    t_last_uart_retry = 0.0

    # Ein einziger Fehlerzustand fuer die UART: sobald Lesen oder Schreiben
    # fehlschlaegt, wird die Schnittstelle in der Hauptschleife geschlossen
    # und neu geoeffnet, statt den Prozess sterben zu lassen (systemd haette
    # ihn zwar neu gestartet, aber mit mehreren Sekunden Ausfall).
    state = {"ser": ser, "broken": False}

    def uart_write(data: bytes, tag: str) -> bool:
        """Schreibt ein komplettes Paket auf die UART. Ein Teilschreibvorgang
        wuerde den Paketstrom fuer den Teensy-Parser zerreissen, deshalb wird
        er als Fehler behandelt und geloggt statt still hingenommen."""
        try:
            written = state["ser"].write(data)
        except (serial.SerialException, OSError) as exc:
            log.warning(f"[{tag}] UART-Schreibfehler: {exc}")
            state["broken"] = True
            return False
        if written is not None and written != len(data):
            log.warning(f"[{tag}] UART-Teilschreibvorgang: {written}/{len(data)} Bytes")
            return False
        return True

    def drain_latest(sock, max_len: int, magic: bytes, exact_len: int):
        """Liest ALLE anstehenden Datagramme des Sockets und gibt nur das
        letzte gueltige zurueck, zusammen mit (Anzahl_verworfen, Anzahl_ungueltig).

        Fuer den Fast-Kanal ist das der entscheidende Punkt: liefert das WLAN
        drei Pakete auf einmal aus, sind die ersten beiden Joystick-Staende
        bereits ueberholt. Sie trotzdem ueber die UART zu schieben kostet nur
        Zeit und laesst den Teensy veraltete Werte abarbeiten."""
        newest = None
        newest_addr = None
        stale = 0
        bad = 0
        while True:
            try:
                data, addr = sock.recvfrom(max_len)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            if len(data) == exact_len and data[:4] == magic:
                if newest is not None:
                    stale += 1
                newest = data
                newest_addr = addr[0]
            else:
                bad += 1
        return newest, newest_addr, stale, bad

    log.info("Event-Loop gestartet — warte auf Daten (UART + 3× UDP)...")

    try:
        while True:
            # timeout=1.0: mind. 1x/s aufwachen, auch wenn nichts anliegt,
            # damit periodische Aufgaben (Stats, Netzwerk-Check) nicht liegen bleiben
            events = sel.select(timeout=1.0)

            for key, _mask in events:
                if key.data == "uart":
                    # Nicht-blockierend: liefert sofort 0..N verfügbare Bytes
                    try:
                        chunk = state["ser"].read(4096)
                    except (serial.SerialException, OSError) as exc:
                        log.warning(f"UART-Lesefehler: {exc}")
                        state["broken"] = True
                        continue
                    dest = target.resolve()
                    if chunk:
                        leds.blink_data()

                    for raw in assembler.feed(chunk):
                        try:
                            sent = udp_out.sendto(raw, (dest, UDP_PORT))
                            pkt_sent += 1
                            bytes_sent += sent
                        except OSError as exc:
                            log.warning(f"UDP-Sendefehler: {exc}")
                            send_errors += 1

                    # Deskriptor-Chunks laufen unabhängig über denselben Rohstrom
                    # (siehe ChunkFrameAssembler-Docstring).
                    for raw in desc_assembler.feed(chunk):
                        try:
                            udp_out.sendto(raw, (dest, UDP_CHANNEL_DESC_PORT))
                            desc_pkt_sent += 1
                        except OSError as exc:
                            log.warning(f"UDP-Sendefehler (Deskriptor): {exc}")
                            send_errors += 1

                elif key.data == "desc_request":
                    data, addr, _stale, bad = drain_latest(
                        desc_request_sock,
                        CHANNEL_DESC_REQUEST_PACKET_BYTES + 64,
                        CHANNEL_DESC_REQUEST_MAGIC_BYTES,
                        CHANNEL_DESC_REQUEST_PACKET_BYTES,
                    )
                    fwd_bad += bad
                    if data is not None:
                        target.note_sender(addr)
                        if uart_write(data, "DescRequest"):
                            fwd_desc_req += 1

                elif key.data == "param_slow":
                    # Slow-Kanal: ebenfalls nur der neueste Stand — ein
                    # ueberholtes Konfigurationspaket 258 B durch die UART zu
                    # schieben verzoegert nur den Fast-Kanal dahinter.
                    data, addr, stale, bad = drain_latest(
                        slow_sock,
                        PARAM_SLOW_PACKET_BYTES + 64,
                        PARAM_SLOW_MAGIC_BYTES,
                        PARAM_SLOW_PACKET_BYTES,
                    )
                    fwd_bad += bad
                    fwd_stale += stale
                    if data is not None:
                        target.note_sender(addr)
                        if uart_write(data, "Slow"):
                            fwd_slow_ok += 1

                elif key.data == "param_fast":
                    data, addr, stale, bad = drain_latest(
                        fast_sock,
                        PARAM_FAST_PACKET_BYTES + 64,
                        PARAM_FAST_MAGIC_BYTES,
                        PARAM_FAST_PACKET_BYTES,
                    )
                    fwd_bad += bad
                    fwd_stale += stale
                    if data is not None:
                        target.note_sender(addr)
                        if uart_write(data, "Fast"):
                            fwd_fast_ok += 1

            # ── UART nach einem Fehler wiederherstellen ────────────────────────
            #  Ohne das war jeder einzelne Lese-/Schreibfehler (Wackler am
            #  Stecker, Teensy zieht kurz Strom weg) das Ende des Prozesses.
            if state["broken"]:
                now = time.monotonic()
                if now - t_last_uart_retry >= 1.0:
                    t_last_uart_retry = now
                    try:
                        sel.unregister(state["ser"].fileno())
                    except (KeyError, OSError, ValueError):
                        pass
                    try:
                        state["ser"].close()
                    except (serial.SerialException, OSError):
                        pass
                    try:
                        state["ser"] = _open_uart()
                        sel.register(state["ser"].fileno(), selectors.EVENT_READ, data="uart")
                        state["broken"] = False
                        assembler = TelemetryFrameAssembler()
                        desc_assembler = ChunkFrameAssembler()
                        log.info(f"UART {UART_PORT} nach Fehler wieder geöffnet.")
                    except (serial.SerialException, OSError) as exc:
                        log.warning(f"UART {UART_PORT} noch nicht verfügbar: {exc}")

            # ── Periodische Aufgaben (statt eigener Threads) ────────────────────
            now = time.monotonic()

            if now - t_stat_start >= STAT_LOG_INTERVAL:
                elapsed = now - t_stat_start
                pps = pkt_sent / elapsed
                kbps = bytes_sent / elapsed / 1024
                new_losses = assembler.sync_losses - last_sync_losses
                dest = target.resolve()
                log.info(
                    f"Telemetrie -> {dest}: {pps:.1f} Pkt/s | {kbps:.1f} KB/s | "
                    f"Sync-Verluste: {new_losses} | Sendefehler: {send_errors} || "
                    f"Param-Downlink: Slow={fwd_slow_ok} Fast={fwd_fast_ok} "
                    f"({fwd_fast_ok / elapsed:.1f} Pkt/s) überholt={fwd_stale} "
                    f"ungültig={fwd_bad} || "
                    f"Deskriptor: Chunks_ok={desc_pkt_sent} Requests_fwd={fwd_desc_req}"
                    + (f" Fehlalarme={desc_assembler.false_magics}"
                       if desc_assembler.false_magics else "")
                )
                if pkt_sent == 0:
                    log.warning(
                        "Keine Telemetrie vom Teensy — Verkabelung (Pin 14 -> GPIO15), "
                        "Baudrate (%d) und MAX_FLOATS (%d) prüfen.", UART_BAUD, MAX_FLOATS
                    )
                pkt_sent = bytes_sent = send_errors = 0
                fwd_slow_ok = fwd_fast_ok = fwd_bad = fwd_stale = 0
                desc_pkt_sent = fwd_desc_req = 0
                last_sync_losses = assembler.sync_losses
                t_stat_start = now

            if now - t_last_netcheck >= NET_CHECK_INTERVAL:
                ip = _wlan_ip()
                if ip is None:
                    log.warning("WLAN nicht verbunden (keine IP-Adresse auf wlan0)")
                leds.set_network(ip is not None)
                t_last_netcheck = now

    except KeyboardInterrupt:
        log.info("Gestoppt (KeyboardInterrupt).")
    finally:
        leds.stop()
        sel.close()
        try:
            state["ser"].close()
        except (serial.SerialException, OSError):
            pass
        udp_out.close()
        slow_sock.close()
        fast_sock.close()
        desc_request_sock.close()
        log.info("Alle Ressourcen freigegeben.")


if __name__ == "__main__":
    main()