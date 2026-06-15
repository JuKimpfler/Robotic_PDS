"""
network_worker.py — Netzwerk-Backend für den RPi 5
====================================================
Verwaltet:
  1. Zwei UDP-Empfänger-Prozesse (Node 1 + 2), vollständig
     vom GUI-Thread entkoppelt via multiprocessing.Queue.
  2. TCP-Flash-Routing: Sendet .hex-Dateien per Thread
     an einen oder beide Nodes parallel.
"""

import struct
import socket
import logging
import threading
import multiprocessing as mp

import numpy as np

from config import (
    UDP_PORT_NODE1, UDP_PORT_NODE2,
    TCP_FLASH_PORT_NODE1, TCP_FLASH_PORT_NODE2,
    NODE1_IP, NODE2_IP,
    PACKET_HEADER_MAGIC, HEADER_SIZE,
    PACKET_SIZE_BYTES, DUMMY_VALUE,
    UDP_RECV_BUFFER, DATA_QUEUE_MAXSIZE,
)

log = logging.getLogger(__name__)


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
      1. Header-Magic validieren (0xDEADBEEF)
      2. Payload als numpy float32-Array deserialisieren (zero-copy)
      3. Dummy-Werte (9898) vektorisiert entfernen
      4. (node_id, timestamp, filtered_array) in out_queue legen

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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_RECV_BUFFER)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)           # Damit stop_event regelmäßig geprüft wird

    proc_log.info(f"Lauscht auf :{port}")

    pkt_ok    = 0
    pkt_drop  = 0   # Queue voll
    pkt_bad   = 0   # Ungültiger Header

    while not stop_event.is_set():
        try:
            raw, addr = sock.recvfrom(PACKET_SIZE_BYTES + 128)
        except socket.timeout:
            continue
        except OSError:
            break

        # ── Minimale Größenprüfung ────────────────────────────────────────────
        if len(raw) < HEADER_SIZE:
            pkt_bad += 1
            continue

        # ── Header validieren ─────────────────────────────────────────────────
        (magic,) = struct.unpack_from("<I", raw, 0)
        if magic != PACKET_HEADER_MAGIC:
            pkt_bad += 1
            continue

        (timestamp,) = struct.unpack_from("<I", raw, 4)

        # ── NumPy-Deserialisierung (zero-copy view auf den Empfangspuffer) ────
        payload = np.frombuffer(raw, dtype=np.float32, offset=HEADER_SIZE)

        # ── Vektorisierte Dummy-Filterung (9898 → entfernen) ─────────────────
        valid = payload[payload != DUMMY_VALUE]

        if valid.size == 0:
            continue

        # ── In Queue legen ────────────────────────────────────────────────────
        try:
            # Pass the sender IP (addr[0]) into the queue for dynamic routing
            out_queue.put_nowait((node_id, timestamp, valid.copy(), addr[0]))
            pkt_ok += 1
        except Exception:
            pkt_drop += 1   # Queue voll → Paket verwerfen

    sock.close()
    proc_log.info(
        f"Beendet | OK={pkt_ok} | Drops={pkt_drop} | Ungültig={pkt_bad}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  TCP Flash-Routing  (läuft in Threads — non-blocking für die GUI)
# ══════════════════════════════════════════════════════════════════════════════

def _send_hex_to_node(
    node_id: int,
    target_ip: str,
    hex_data: bytes,
    result_cb=None,
) -> None:
    """
    Sendet hex_data per TCP an den Flash-Daemon eines Nodes.
    Läuft in einem eigenen Thread (nicht im GUI-Thread).

    Args:
        node_id:   1 oder 2
        target_ip: IP-Adresse des Nodes
        hex_data:  Binärinhalt der .hex-Datei
        result_cb: Optional. callable(node_id: int, success: bool, msg: str)
    """
    target_port = TCP_FLASH_PORT_NODE1 if node_id == 1 else TCP_FLASH_PORT_NODE2

    log.info(f"[Flash] → Node {node_id} | {target_ip}:{target_port} | {len(hex_data):,} Bytes")

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((target_ip, target_port))

        # Dateigröße voranstellen (4 Bytes big-endian)
        sock.sendall(struct.pack(">I", len(hex_data)))

        # .hex-Daten in Chunks senden (vermeidet riesige sendall-Aufrufe)
        chunk_size = 65536
        for offset in range(0, len(hex_data), chunk_size):
            sock.sendall(hex_data[offset : offset + chunk_size])

        # Antwort vom Flash-Daemon lesen
        response = b""
        sock.settimeout(90)   # teensy_loader_cli braucht Zeit
        while True:
            chunk = sock.recv(512)
            if not chunk:
                break
            response += chunk
            if response.startswith(b"OK") or response.startswith(b"ERR"):
                break   # Vollständige Antwort empfangen

        resp_str = response.decode("utf-8", errors="replace").strip()
        success  = resp_str == "OK"

        log.info(f"[Flash] Node {node_id}: {resp_str}")

        if result_cb:
            result_cb(node_id, success, resp_str)

    except Exception as exc:
        msg = str(exc)
        log.error(f"[Flash] Node {node_id} Fehler: {msg}")
        if result_cb:
            result_cb(node_id, False, msg)

    finally:
        if sock:
            sock.close()


def flash_nodes(
    hex_path: str,
    node1: bool,
    node2: bool,
    ip_node1: str,
    ip_node2: str,
    result_cb=None,
) -> None:
    """
    Flasht einen oder beide Nodes parallel (je ein Thread).

    Args:
        hex_path:  Pfad zur .hex-Datei auf dem RPi 5
        node1:     True → Node 1 flashen
        node2:     True → Node 2 flashen
        ip_node1:  IP Adresse von Node 1
        ip_node2:  IP Adresse von Node 2
        result_cb: Optional. Wird für jeden Node aufgerufen:
                   callable(node_id: int, success: bool, message: str)
    """
    if not (node1 or node2):
        log.warning("[Flash] Kein Ziel ausgewählt.")
        return

    with open(hex_path, "rb") as f:
        hex_data = f.read()

    for nid, enabled, target_ip in ((1, node1, ip_node1), (2, node2, ip_node2)):
        if enabled:
            t = threading.Thread(
                target=_send_hex_to_node,
                args=(nid, target_ip, hex_data, result_cb),
                daemon=True,
                name=f"Flash-Node{nid}",
            )
            t.start()


# ══════════════════════════════════════════════════════════════════════════════
#  NetworkManager  (wird in main.py instanziert)
# ══════════════════════════════════════════════════════════════════════════════

class NetworkManager:
    """
    Startet und verwaltet alle Netzwerk-Hintergrundprozesse.
    Stellt Queues für den GUI-Thread bereit.
    """

    def __init__(self) -> None:
        self._stop_event = mp.Event()

        # Gemeinsame Queues (GUI-Prozess liest, Receiver-Prozesse schreiben)
        self.queue_node1: mp.Queue = mp.Queue(maxsize=DATA_QUEUE_MAXSIZE)
        self.queue_node2: mp.Queue = mp.Queue(maxsize=DATA_QUEUE_MAXSIZE)

        # Empfänger-Prozesse
        self._proc1 = mp.Process(
            target=udp_receiver_process,
            args=(UDP_PORT_NODE1, 1, self.queue_node1, self._stop_event),
            daemon=True,
            name="UDP-Node1",
        )
        self._proc2 = mp.Process(
            target=udp_receiver_process,
            args=(UDP_PORT_NODE2, 2, self.queue_node2, self._stop_event),
            daemon=True,
            name="UDP-Node2",
        )

    def start(self) -> None:
        self._proc1.start()
        self._proc2.start()
        log.info(
            f"[NetworkManager] Gestartet | "
            f"PID1={self._proc1.pid} | PID2={self._proc2.pid}"
        )

    def stop(self) -> None:
        log.info("[NetworkManager] Stoppe Prozesse...")
        self._stop_event.set()
        self._proc1.join(timeout=3)
        self._proc2.join(timeout=3)
        log.info("[NetworkManager] Beendet.")

    def get_queue(self, node_id: int) -> mp.Queue:
        """Gibt die Queue für den angegebenen Node zurück."""
        return self.queue_node1 if node_id == 1 else self.queue_node2

    @property
    def is_running(self) -> bool:
        return self._proc1.is_alive() and self._proc2.is_alive()
