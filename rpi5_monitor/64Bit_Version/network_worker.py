"""
network_worker.py — Netzwerk-Backend für den RPi 5
====================================================
Verwaltet:
  1. Zwei UDP-Empfänger-Prozesse (Node 1 + 2), vollständig
     vom GUI-Thread entkoppelt via multiprocessing.Queue.
"""

import struct
import socket
import logging
import multiprocessing as mp
from time import monotonic

import numpy as np

from config import (
    UDP_PORT_NODE1, UDP_PORT_NODE2,
    PACKET_HEADER_MAGIC, HEADER_SIZE,
    PACKET_SIZE_BYTES, DUMMY_VALUE,
    UDP_RECV_BUFFER, DATA_QUEUE_MAXSIZE,
    UDP_CHANNEL_DESC_PORT_NODE1, UDP_CHANNEL_DESC_PORT_NODE2,
)
from channel_registry import descriptor_receiver_process

log = logging.getLogger(__name__)

_MAGIC_BYTES = struct.pack("<I", PACKET_HEADER_MAGIC)


# ══════════════════════════════════════════════════════════════════════════════
#  UDP-Empfänger  (läuft als eigenständiger Prozess — kein GIL, kein GUI-Block)
# ══════════════════════════════════════════════════════════════════════════════

def udp_receiver_process(
    port: int,
    node_id: int,
    out_queue: mp.Queue,
    stop_event: mp.Event,
) -> None:
    """
    Hochperformanter UDP-Empfänger.

    Für jedes empfangene Paket:
      1. Header-Magic UND Paketgröße validieren
      2. Payload als numpy float32-Array deserialisieren (zero-copy view)
      3. Nachlaufende Dummy-Kanäle (9898) abschneiden
      4. (node_id, timestamp, values, sender_ip) in out_queue legen

    Args:
        port:       UDP-Empfangsport (5001 oder 5002)
        node_id:    1 oder 2
        out_queue:  Gemeinsame Queue mit dem GUI-Hauptprozess
        stop_event: multiprocessing.Event zum Stoppen des Prozesses
    """
    # Prozess-eigenes Logging
    logging.basicConfig(
        level=logging.INFO,
        format=f"[UDP-N{node_id}] %(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    proc_log = logging.getLogger()

    # ── Socket aufbauen ───────────────────────────────────────────────────────
    #  Ein Fehler beim Binden (Port belegt) darf den Prozess nicht stumm
    #  sterben lassen — dann stünde die GUI dauerhaft ohne Daten da, ohne
    #  dass irgendwo eine Ursache steht.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_RECV_BUFFER)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(0.5)       # Damit stop_event regelmäßig geprüft wird
    except OSError as exc:
        proc_log.error(
            f"UDP-Port {port} konnte nicht geöffnet werden: {exc} — "
            f"läuft die GUI evtl. schon einmal?"
        )
        return

    proc_log.info(f"Lauscht auf :{port}")

    pkt_ok    = 0
    pkt_drop  = 0   # Queue voll
    pkt_bad   = 0   # Ungültiger Header / falsche Größe
    last_bad_log = 0.0

    while not stop_event.is_set():
        try:
            raw, addr = sock.recvfrom(PACKET_SIZE_BYTES + 128)
        except socket.timeout:
            continue
        except OSError:
            break

        # ── Header UND Größe validieren ───────────────────────────────────────
        #  Die Größenprüfung war vorher nur `< HEADER_SIZE`. Ein Paket mit
        #  abweichender Länge (anderes MAX_FLOATS auf dem Teensy, gekürztes
        #  Datagramm) ließ np.frombuffer() unten mit einem ValueError
        #  hochgehen — der Empfänger-Prozess starb daraufhin still, und die
        #  GUI zeigte für immer 0 Pakete/s ohne erkennbaren Grund.
        if len(raw) != PACKET_SIZE_BYTES or raw[:4] != _MAGIC_BYTES:
            pkt_bad += 1
            now = monotonic()
            if now - last_bad_log >= 5.0:
                last_bad_log = now
                proc_log.warning(
                    f"Paket verworfen ({len(raw)} statt {PACKET_SIZE_BYTES} Bytes "
                    f"bzw. falsches Magic) von {addr[0]} — MAX_FLOATS auf Teensy, "
                    f"Node und GUI müssen übereinstimmen."
                )
            continue

        (timestamp,) = struct.unpack_from("<I", raw, 4)

        # ── NumPy-Deserialisierung (zero-copy view auf den Empfangspuffer) ────
        payload = np.frombuffer(raw, dtype=np.float32, offset=HEADER_SIZE)

        # ── Nachlaufende Dummy-Kanäle abschneiden ────────────────────────────
        #  Vorher wurde JEDER Wert == 9898 herausgefiltert. Lag ein Dummy
        #  mitten im Array (oder traf ein echter Messwert zufällig 9898.0),
        #  rutschten alle folgenden Kanäle um eine Position nach vorne —
        #  Kanal 42 wurde dann als Kanal 41 angezeigt, inklusive Namen,
        #  Overlays und Plotter-Auswahl. Jetzt wird nur der zusammenhängende
        #  Dummy-Block am ENDE entfernt; die Indizes bleiben damit exakt die
        #  Kanalnummern des Teensy.
        active = np.flatnonzero(payload != DUMMY_VALUE)
        if active.size == 0:
            continue
        values = payload[: int(active[-1]) + 1].copy()

        # ── In Queue legen ────────────────────────────────────────────────────
        try:
            # Sender-IP (addr[0]) mitgeben, damit die GUI die Node-Adresse lernt
            out_queue.put_nowait((node_id, timestamp, values, addr[0]))
            pkt_ok += 1
        except Exception:
            pkt_drop += 1   # Queue voll → Paket verwerfen

    sock.close()
    proc_log.info(
        f"Beendet | OK={pkt_ok} | Drops={pkt_drop} | Ungültig={pkt_bad}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  NetworkManager  (wird in main.py instanziert)
# ══════════════════════════════════════════════════════════════════════════════

class NetworkManager:
    """
    Startet und verwaltet alle Netzwerk-Hintergrundprozesse.
    Stellt Queues für den GUI-Thread bereit.

    Robustheit: `supervise()` (wird vom GUI-Poll-Timer 1x/s aufgerufen)
    startet einen Empfänger-Prozess neu, der sich unerwartet beendet hat.
    Vorher hätte ein einzelner Absturz — z. B. ein Paket mit falscher Länge —
    die Telemetrie dieses Nodes bis zum GUI-Neustart dauerhaft stillgelegt.
    """

    # (Attributname, Zielfunktion, Port, node_id, Queue-Attribut, Prozessname)
    _SPECS = (
        ("_proc1",      udp_receiver_process,        UDP_PORT_NODE1,              1, "queue_node1",      "UDP-Node1"),
        ("_proc2",      udp_receiver_process,        UDP_PORT_NODE2,              2, "queue_node2",      "UDP-Node2"),
        ("_desc_proc1", descriptor_receiver_process, UDP_CHANNEL_DESC_PORT_NODE1, 1, "queue_desc_node1", "Desc-Node1"),
        ("_desc_proc2", descriptor_receiver_process, UDP_CHANNEL_DESC_PORT_NODE2, 2, "queue_desc_node2", "Desc-Node2"),
    )

    def __init__(self) -> None:
        self._stop_event = mp.Event()

        # Gemeinsame Queues (GUI-Prozess liest, Receiver-Prozesse schreiben)
        self.queue_node1: mp.Queue = mp.Queue(maxsize=DATA_QUEUE_MAXSIZE)
        self.queue_node2: mp.Queue = mp.Queue(maxsize=DATA_QUEUE_MAXSIZE)

        # Namens-/Overlay-Deskriptor: eigene Queues. Bewusst MIT maxsize —
        # eine unbegrenzte Queue, die niemand leert (GUI hängt/steht), wächst
        # sonst unbemerkt bis der Speicher voll ist.
        self.queue_desc_node1: mp.Queue = mp.Queue(maxsize=16)
        self.queue_desc_node2: mp.Queue = mp.Queue(maxsize=16)

        self._restarts: dict[str, int] = {}
        self._procs: dict[str, mp.Process] = {}
        for attr, target, port, node_id, queue_attr, name in self._SPECS:
            self._procs[attr] = self._make_proc(target, port, node_id, queue_attr, name)
            self._restarts[attr] = 0

    # ── intern ────────────────────────────────────────────────────────────
    def _make_proc(self, target, port: int, node_id: int,
                    queue_attr: str, name: str) -> mp.Process:
        return mp.Process(
            target=target,
            args=(port, node_id, getattr(self, queue_attr), self._stop_event),
            daemon=True,
            name=name,
        )

    # ── öffentlich ────────────────────────────────────────────────────────
    @property
    def stop_event(self) -> "mp.Event":
        """Wird u. a. vom Simulator-Prozess mitbenutzt (siehe main_qml.py)."""
        return self._stop_event

    def start(self) -> None:
        for proc in self._procs.values():
            proc.start()
        log.info(
            "[NetworkManager] Gestartet | %s",
            " | ".join(f"{p.name}={p.pid}" for p in self._procs.values()),
        )

    def supervise(self) -> list[str]:
        """Beendete Empfänger-Prozesse neu starten. Gibt die Namen der neu
        gestarteten Prozesse zurück (für eine Statusmeldung in der GUI)."""
        if self._stop_event.is_set():
            return []
        restarted: list[str] = []
        for attr, target, port, node_id, queue_attr, name in self._SPECS:
            proc = self._procs[attr]
            if proc.is_alive():
                continue
            # Höchstens ein paar Versuche: ist der Port dauerhaft belegt,
            # würde eine Endlosschleife nur das Log fluten.
            if self._restarts[attr] >= 5:
                continue
            self._restarts[attr] += 1
            log.warning("[NetworkManager] %s ist beendet (Exit %s) — Neustart %d/5.",
                        name, proc.exitcode, self._restarts[attr])
            new_proc = self._make_proc(target, port, node_id, queue_attr, name)
            new_proc.start()
            self._procs[attr] = new_proc
            restarted.append(name)
        return restarted

    def stop(self) -> None:
        log.info("[NetworkManager] Stoppe Prozesse...")
        self._stop_event.set()
        for proc in self._procs.values():
            proc.join(timeout=3)
            if proc.is_alive():
                log.warning("[NetworkManager] %s reagiert nicht — terminate().", proc.name)
                proc.terminate()
                proc.join(timeout=1)
        # Queues explizit schließen, sonst hält der Feeder-Thread des
        # GUI-Prozesses den Interpreter beim Beenden gelegentlich fest.
        for q in (self.queue_node1, self.queue_node2,
                  self.queue_desc_node1, self.queue_desc_node2):
            q.close()
            q.cancel_join_thread()
        log.info("[NetworkManager] Beendet.")

    def get_queue(self, node_id: int) -> mp.Queue:
        """Gibt die Queue für den angegebenen Node zurück."""
        return self.queue_node1 if node_id == 1 else self.queue_node2

    def get_desc_queue(self, node_id: int) -> mp.Queue:
        """Gibt die Deskriptor-Queue (Namen/Overlays) für den angegebenen Node zurück."""
        return self.queue_desc_node1 if node_id == 1 else self.queue_desc_node2

    @property
    def is_running(self) -> bool:
        return all(p.is_alive() for p in self._procs.values())
