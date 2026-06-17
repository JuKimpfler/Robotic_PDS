"""
config.py — Zentrale Konfiguration des Power Debug Monitors
=============================================================
Alle IPs, Ports, Paket-Parameter und GUI-Konstanten
an einem einzigen Ort.
"""

import platform

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
TCP_FLASH_PORT_NODE1 = 6001
TCP_FLASH_PORT_NODE2 = 6002
TCP_PARAM_PORT      = 7001   # Zukunft: Parameter-Übertragung

# ── Paket-Format ──────────────────────────────────────────────────────────────
PACKET_HEADER_MAGIC = 0xDEADBEEF    # Muss mit Teensy übereinstimmen
HEADER_SIZE         = 8              # uint32 magic + uint32 timestamp
MAX_FLOATS          = 200           # Maximale Anzahl float32 pro Paket
PACKET_SIZE_BYTES   = HEADER_SIZE + MAX_FLOATS * 4   # 4008 Bytes
DUMMY_VALUE         = 9898.0         # Füllwert für inaktive Kanäle

# ── Netzwerk-Worker Performance ───────────────────────────────────────────────
UDP_RECV_BUFFER     = 1024 * 1024    # 1 MB Kernel-Empfangspuffer
DATA_QUEUE_MAXSIZE  = 300            # Maximale Queue-Tiefe (dann: Drop älteste)

# ── GUI Timing ────────────────────────────────────────────────────────────────
GUI_FPS             = 30
GUI_TIMER_MS        = 1000 // GUI_FPS        # 33 ms

# ── Plotter ───────────────────────────────────────────────────────────────────
PLOT_HISTORY_SEC    = 5              # Sekunden sichtbarer Verlauf
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
