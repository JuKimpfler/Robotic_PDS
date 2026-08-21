"""
config.py — Zentrale Konfiguration des Power Debug Monitors
=============================================================
Alle IPs, Ports, Paket-Parameter und GUI-Konstanten
an einem einzigen Ort.
"""

import platform

# Muss mit teensy_firmware/src/params.h (PDS_WIRE_VERSION) uebereinstimmen.
# tools/check_wire_format.py prueft das.
PDS_WIRE_VERSION = 2

# ── Automatische OS-Erkennung für Testbetrieb ──────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    # Lokaler Testmodus auf dem PC
    RPI5_IP  = "127.0.0.1"
    NODE1_IP = "127.0.0.1"
    NODE2_IP = "127.0.0.1"
else:
    # Realer Betrieb auf dem Raspberry Pi 5
    RPI5_IP  = "127.0.0.1" # oder "192.168.42.1"
    NODE1_IP = "192.168.42.11"
    NODE2_IP = "192.168.42.12"

# Die Ports können gleich bleiben
UDP_PORT_NODE1      = 5001
UDP_PORT_NODE2      = 5002
# TCP_PARAM_PORT = 7001  # ersetzt durch PARAM_SLOW/FAST-Konstanten (UDP statt TCP,
#                         # siehe Param-Feature-Plan v2 Abschnitt 2.1 — fire-and-forget
#                         # passt besser zu UDP als zu TCP)

# ── Param-Downlink: Slow-Kanal (50 Floats + 50 Bools, 2 Hz) ────────────────────
PARAM_SLOW_MAGIC        = 0xCAFE_FEED
PARAM_SLOW_FLOAT_COUNT  = 50
PARAM_SLOW_BOOL_COUNT   = 50
PARAM_HEADER_SIZE       = 8
PARAM_SLOW_PACKET_BYTES = (
    PARAM_HEADER_SIZE + PARAM_SLOW_FLOAT_COUNT * 4 + PARAM_SLOW_BOOL_COUNT
)  # 258

UDP_PARAM_SLOW_PORT_NODE1 = 7001
UDP_PARAM_SLOW_PORT_NODE2 = 7002

PARAM_SLOW_SEND_HZ          = 2.0
PARAM_SLOW_SEND_INTERVAL_MS = int(1000 / PARAM_SLOW_SEND_HZ)   # 500

# ── Param-Downlink: Fast-Kanal (5 Floats, 100 Hz, Joystick-Echtzeitsteuerung) ──
PARAM_FAST_MAGIC        = 0xFA57_DA7A
PARAM_FAST_FLOAT_COUNT  = 5
PARAM_FAST_PACKET_BYTES = PARAM_HEADER_SIZE + PARAM_FAST_FLOAT_COUNT * 4   # 28

UDP_PARAM_FAST_PORT_NODE1 = 7011
UDP_PARAM_FAST_PORT_NODE2 = 7012

PARAM_FAST_SEND_HZ          = 100.0
PARAM_FAST_SEND_INTERVAL_MS = int(1000 / PARAM_FAST_SEND_HZ)   # 10

# ── PS4-Controller (siehe bridge/controller_bridge.py) ────────────────────────
# Die optionale Datei CONTROLLER_CONFIG_PATH (weiter unten definiert)
# überschreibt bei Bedarf die Achsen-/Button-Zuordnung.
#
# Wie oft die Controller-Werte an QML gemeldet werden. Der Fast-Kanal wird
# unabhängig davon mit PARAM_FAST_SEND_HZ gesendet — die Anzeige muss dem
# aber nicht mit 100 Hz folgen (das Display schafft max. 60 fps und jedes
# Signal kostet GUI-Thread-Zeit, die dem Sendetimer fehlt).
CONTROLLER_UI_NOTIFY_MS = 40    # 25 Hz

# ── Discovery/Keepalive (GUI -> Node, 1 Hz an BEIDE Nodes) ────────────────────
#  Der Node schickt seine Telemetrie per Unicast an die Adresse, von der er
#  zuletzt ein Paket der GUI bekommen hat — sonst per Broadcast. Broadcast
#  kostet im WLAN ein Vielfaches an Funkzeit (niedrigste Basisrate, keine
#  Aggregation, keine ACKs) und war die Hauptursache der trägen Fernsteuerung
#  (siehe Doku/Latenz_Fernsteuerung.md).
#
#  Param-Pakete gehen aber immer nur an den AKTIVEN Node — der inaktive hat
#  deshalb nie eine Adresse gelernt und dauerhaft mit 80 kB/s gebroadcastet,
#  was den Funkkanal auch für den aktiven Node belastet hat.
#
#  Dieses 4-Byte-Paket schließt die Lücke: es geht an BEIDE Nodes, der Node
#  wertet ausschließlich die Absenderadresse aus und leitet es NICHT an den
#  Teensy weiter. Damit kann es auch nie versehentlich Parameter in den
#  falschen Roboter schreiben.
#  Muss mit rpi_zero_node/uart_receiver.py übereinstimmen.
#  Seit Wire-Format 2 traegt das Paket zusaetzlich eine laufende Nummer und
#  den Sendezeitpunkt. Der Node schickt beides unveraendert zurueck
#  (DISCOVERY_ECHO_MAGIC) — daraus misst die GUI die echte Round-Trip-Zeit
#  zum Node, ohne dafuer ein eigenes Ping-Protokoll zu brauchen.
DISCOVERY_MAGIC             = 0xD15C_0BE5
DISCOVERY_PACKET_BYTES      = 12    # magic(4) + seq(4) + t_send_ms(4)
DISCOVERY_STRUCT            = "<III"
UDP_DISCOVERY_PORT_NODE1    = 7031
UDP_DISCOVERY_PORT_NODE2    = 7032
DISCOVERY_SEND_INTERVAL_MS  = 1000

DISCOVERY_ECHO_MAGIC        = 0xD15C_EC40
DISCOVERY_ECHO_PACKET_BYTES = 16    # magic(4) + node_id(4) + seq(4) + t_send_ms(4)
DISCOVERY_ECHO_STRUCT       = "<IIII"

# ── Namens-/Overlay-Deskriptor (Teensy -> GUI, einmalig beim Boot + auf Anfrage) ─
# Muss exakt mit params.h (Teensy) und rpi_zero_node/uart_receiver.py übereinstimmen!
CHANNEL_DESC_MAGIC          = 0xDE5C0001
CHANNEL_DESC_HEADER_BYTES   = 7    # magic(4) + chunk_idx(1) + chunk_count(1) + payload_len(1)

CHANNEL_DESC_REQUEST_MAGIC        = 0xDE5C00F0
CHANNEL_DESC_REQUEST_PACKET_BYTES = 4

UDP_CHANNEL_DESC_PORT_NODE1         = 5011
UDP_CHANNEL_DESC_PORT_NODE2         = 5012
UDP_CHANNEL_DESC_REQUEST_PORT_NODE1 = 7021
UDP_CHANNEL_DESC_REQUEST_PORT_NODE2 = 7022

# ── Aux-Uplink (Node -> GUI): Ereignisse, Param-Ack, Node-Status ──────────────
#  EIN Port fuer alle kleinen Uplink-Pakete; die GUI trennt sie am Magic
#  (siehe network_worker.py::aux_receiver_process). Ein eigener Port je Typ
#  waere ein weiterer Empfaengerprozess ohne jeden Gegenwert.
#  Muss mit rpi_zero_node/uart_receiver.py und teensy_firmware/src/params.h
#  uebereinstimmen.
UDP_AUX_PORT_NODE1 = 5021
UDP_AUX_PORT_NODE2 = 5022

# Ereignisse und Logzeilen vom Teensy (PDS.event / PDS.log)
PDS_EVENT_MAGIC        = 0xE7E5_C0DE
PDS_EVENT_HEADER_BYTES = 16    # magic(4) micros(4) value(4) kind level len rsv
PDS_EVENT_TEXT_MAX     = 48
PDS_EVENT_KIND_EVENT   = 0
PDS_EVENT_KIND_LOG     = 1
PDS_EVENT_LEVEL_NAMES  = {0: "Info", 1: "Warnung", 2: "Fehler"}

# Parameter-Rueckmeldung vom Teensy (2 Hz): was haelt er tatsaechlich?
PARAM_ACK_MAGIC        = 0xACC0_FEED
PARAM_ACK_HEADER_BYTES = 20
PARAM_ACK_PACKET_BYTES = (PARAM_ACK_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4
                          + PARAM_SLOW_BOOL_COUNT + PARAM_FAST_FLOAT_COUNT * 4)   # 290

# Systemzustand des Pi-Zero-Nodes selbst (1 Hz)
NODE_STATUS_MAGIC        = 0x0DE5_7A75
NODE_STATUS_STRUCT       = "<IBBHffffIIII"
NODE_STATUS_PACKET_BYTES = 40
NODE_STATUS_FLAG_TEENSY  = 0x01
NODE_STATUS_FLAG_WIFI    = 0x02
NODE_STATUS_FLAG_UNICAST = 0x04

# Wie viele Ereignisse/Logzeilen das Logbuch der GUI vorhaelt.
EVENT_LOG_MAXLEN = 500

# ── Param-Downlink: Konfigurations- & Persistenzdateien ────────────────────────
from pathlib import Path as _Path
PARAM_CONFIG_PATH      = _Path(__file__).parent / "param_config.json"
PARAM_DEFAULTS_H_PATH  = _Path(__file__).parent / "param_defaults.h"
CONTROLLER_CONFIG_PATH = _Path(__file__).parent / "controller_config.json"

# ── Vom Teensy uebernommene Konfiguration (reboot-fest) ───────────────────────
#  Der Teensy ist die Quelle der Wahrheit fuer Kanalnamen, Parameter-Widgets
#  und Overlays. Was im Deskriptor ankommt, wird HIER dauerhaft abgelegt —
#  je Node getrennt, weil die beiden Roboter unterschiedliche Firmware haben
#  koennen. Nach einem Neustart des Pi steht damit sofort wieder alles da,
#  auch ohne eingeschalteten Roboter.
#
#  Die Dateien im Repository (param_config.json, visuals_overlays.json)
#  bleiben die Vorlage/der Rueckfall und werden NIE ueberschrieben — so
#  nimmt ein `git pull` einem nichts weg, und ein Zuruecksetzen ist ein
#  simples Loeschen des runtime_config-Ordners.
RUNTIME_CONFIG_DIR = _Path(__file__).parent / "runtime_config"


def runtime_config_path(node_id: int, name: str) -> "_Path":
    """Pfad einer node-spezifischen, dauerhaft gespeicherten Konfigurationsdatei."""
    return RUNTIME_CONFIG_DIR / f"node{int(node_id)}" / name


# Oberflaechen-Einstellungen (Theme, Schriftgroesse, Akku-Warnung, ...).
# Nicht node-spezifisch — das ist die Einstellung des Bedieners, nicht des
# Roboters.
UI_SETTINGS_PATH = RUNTIME_CONFIG_DIR / "ui_settings.json"

# Startwerte der Akku-Warnung (C3). Kanal -1 = aus; ueber den Tab
# "Diagnose" zur Laufzeit einstellbar und in UI_SETTINGS_PATH gespeichert.
BATTERY_ALARM_DEFAULTS = {
    "enabled": False,
    "channel": -1,
    "warn_below": 11.5,
    "critical_below": 10.8,
    # So lange muss der Wert am Stueck darunter liegen, bevor gewarnt wird.
    # Ohne das loest jeder Anlaufstrom-Einbruch eines Motors Alarm aus.
    "hold_seconds": 2.0,
}

# ── Paket-Format ──────────────────────────────────────────────────────────────
# MAX_FLOATS ist Wire-Format und muss mit teensy_firmware/src/PDS.cpp
# (MAX_FLOATS) und rpi_zero_node/uart_receiver.py (MAX_FLOATS) übereinstimmen.
PACKET_HEADER_MAGIC = 0xDEADBEEF    # Muss mit Teensy übereinstimmen
HEADER_SIZE         = 8              # uint32 magic + uint32 timestamp
MAX_FLOATS          = 200           # Maximale Anzahl float32 pro Paket
PACKET_SIZE_BYTES   = HEADER_SIZE + MAX_FLOATS * 4   # 808 Bytes
DUMMY_VALUE         = 9898.0         # Füllwert für inaktive Kanäle

# ── Netzwerk-Worker Performance ───────────────────────────────────────────────
UDP_RECV_BUFFER     = 1024 * 1024    # 1 MB Kernel-Empfangspuffer
DATA_QUEUE_MAXSIZE  = 300            # Maximale Queue-Tiefe (dann: Drop älteste)

# ── GUI Timing ────────────────────────────────────────────────────────────────
GUI_FPS             = 20
GUI_TIMER_MS        = 1000 // GUI_FPS        # 50 ms

# Nach dieser Zeit ohne empfangenes Telemetriepaket gilt ein Node als
# getrennt (Verbindungs-LED in der StatusBar, siehe app_bridge.py).
NODE_TIMEOUT_SEC    = 1.5

# ── Plotter ───────────────────────────────────────────────────────────────────
PLOT_HISTORY_SEC    = 10              # Sekunden sichtbarer Verlauf
PLOT_SAMPLE_RATE    = 100            # Erwartete Pakete/s vom Teensy
PLOT_BUFFER_SIZE    = PLOT_HISTORY_SEC * PLOT_SAMPLE_RATE   # 500 Samples

# ── Variablen-Mapping ─────────────────────────────────────────────────────────
# Index → lesbarer Name. Standardmäßig generisch.
# Für RoboCup: spezifische Namen hier eintragen, z. B.:
#   VARIABLE_NAMES[0]  = "Motor_L_Speed"
#   VARIABLE_NAMES[1]  = "Motor_R_Speed"
#   VARIABLE_NAMES[2]  = "Compass_Heading"
#   VARIABLE_NAMES[3]  = "Ball_X"
#   VARIABLE_NAMES[4]  = "Ball_Y"
#   VARIABLE_NAMES[10] = "Akku_Spannung"

VARIABLE_NAMES: dict[int, str] = {
    i: f"Var_{i:03d}" for i in range(MAX_FLOATS)
}
