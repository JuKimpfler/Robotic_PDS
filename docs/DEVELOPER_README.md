# Power Debug System — Entwickler-Dokumentation

> **Zielgruppe:** Entwickler, die das System erweitern, debuggen oder in neue Hardware integrieren wollen.  
> **Stand:** Version 1.0 — Phase 1 abgeschlossen

---

## Inhaltsverzeichnis

1. [Architekturübersicht](#1-architekturübersicht)
2. [Datenpipeline & Datenfluss](#2-datenpipeline--datenfluss)
3. [Protokolldefinition](#3-protokolldefinition)
4. [Codebasis-Überblick](#4-codebasis-überblick)
5. [Konfiguration anpassen](#5-konfiguration-anpassen)
6. [GUI erweitern](#6-gui-erweitern)
7. [Phase-2-Features implementieren](#7-phase-2-features-implementieren)
8. [Neue Hardware integrieren](#8-neue-hardware-integrieren)
9. [Testing & Simulation](#9-testing--simulation)
10. [Performance-Profiling](#10-performance-profiling)
11. [Deployment & Updates](#11-deployment--updates)
12. [Bekannte Einschränkungen & TODOs](#12-bekannte-einschränkungen--todos)
13. [Roadmap](#13-roadmap)

---

## 1. Architekturübersicht

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Entwicklungs-PC                            │
│  upload_firmware.py  oder  Power Debug Monitor GUI                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ USB-C OTG (RNDIS / CDC-Ethernet)
                               │ 192.168.7.0/24
┌──────────────────────────────┴──────────────────────────────────────┐
│                   Raspberry Pi 5  (192.168.42.1)                    │
│                                                                     │
│  GUI-Prozess (Hauptprozess):          Netzwerk-Prozesse:            │
│  ┌─────────────────────────┐          ┌──────────────────┐          │
│  │ PyQt6 MainWindow        │◄──Queue──│ UDP Receiver 1   │  ←UDP    │
│  │  ├─ Tab1: Tabelle       │◄──Queue──│ UDP Receiver 2   │  ←UDP    │
│  │  ├─ Tab2: Plotter       │          └──────────────────┘          │
│  │  ├─ Tab3: Visuals (P2)  │          ┌──────────────────┐          │
│  │  └─ Tab4: Params  (P2)  │──Thread──│ TCP Flash-Router │  →TCP    │
│  └─────────────────────────┘          └──────────────────┘          │
│             ↕ QTimer 33ms                                           │
│  ┌──────────────────────────┐                                       │
│  │ NetworkManager (WLAN-AP) │  SSID: PowerDebugAP / 192.168.42.1   │
│  └──────────────────────────┘                                       │
└──────────────┬──────────────────────────────┬───────────────────────┘
               │ WiFi UDP/TCP                  │ WiFi UDP/TCP
               │ 192.168.42.11                 │ 192.168.42.12
┌──────────────┴───────────┐   ┌───────────────┴──────────────────────┐
│  RPi Zero W — Node 1     │   │  RPi Zero W — Node 2                 │
│  uart_receiver.py        │   │  uart_receiver.py                    │
│  flash_daemon.py         │   │  flash_daemon.py                     │
│  status_leds.py          │   │  status_leds.py                      │
└──────────────┬───────────┘   └───────────────┬──────────────────────┘
               │ UART (4 Mbps / Serial1)         │ UART (4 Mbps / Serial1)
┌──────────────┴───────────┐   ┌───────────────┴──────────────────────┐
│     Teensy 4.0 (1)       │   │     Teensy 4.0 (2)                   │
│     main.cpp             │   │     main.cpp                         │
└──────────────────────────┘   └──────────────────────────────────────┘
```

### Prozessmodell

Das System verwendet bewusst **zwei Parallelisierungsstrategien**:

| Technologie | Wo eingesetzt | Warum |
|---|---|---|
| `multiprocessing.Process` | UDP-Empfänger | Umgeht Python-GIL; verhindert GUI-Blockierung bei ~400 KB/s Nettodaten |
| `threading.Thread` | TCP-Flash-Router, LED-Controller, Netzwerk-Monitor | Ausreichend für I/O-bound Tasks; teilen GUI-Prozess-Speicher |
| `QTimer` (33 ms) | GUI-Daten-Poll | Entkoppelt Netzwerk-Rate (~100 Hz) von Render-Rate (~30 Hz) |

---

## 2. Datenpipeline & Datenfluss

```
Teensy (C++)                RPi Zero (Python)           RPi 5 (Python)
────────────────            ─────────────────           ─────────────────────────────
buildPacket()               UART DMA (async)           GUI-Timer (33 ms)
  │                           │ _read_exactly(1608 B)     │
  │ pack: magic+ts+floats[400]   │                        │  poll_data()
  ▼                           ▼                           │    queue.get_nowait() × N
Serial1.write(1608 B)      bytes via /dev/ttyAMA0        │    → batch[] sammeln
                            → raw bytes (4008 B)          │
                           sock.sendto(raw, RPi5:5001)   │  latest = batch[-1]
                            → UDP Datagramm              │    tab_table.update_data(latest)
                                        │                │    tab_plotter.append_data(v)
                                        ▼                │
                                   udp_receiver_process()│
                                     validate_header()   │
                                     np.frombuffer()     │
                                     filter(!=9898)      │
                                     queue.put_nowait()──┘
```

### Queue-Design

```python
# multiprocessing.Queue: Prozessübergreifend (Shared Memory via OS Pipes)
queue_node1: mp.Queue[Tuple[int, int, np.ndarray]]  # (node_id, timestamp, values)
queue_node2: mp.Queue[Tuple[int, int, np.ndarray]]

# Größe: DATA_QUEUE_MAXSIZE = 300 Einträge
# Bei 100 Pkt/s = 3 Sekunden Puffer
# Bei vollem Puffer: put_nowait() → Exception → Paket verworfen (kein Blockieren!)
```

---

## 3. Protokolldefinition

### Binärpaket (Teensy → RPi Zero → RPi 5)

```
Offset  Größe  Typ       Beschreibung
──────────────────────────────────────────────────────────
0       4 B    uint32_t  Magic: 0xDEADBEEF (Little-Endian)
4       4 B    uint32_t  Timestamp: micros() des Teensy
8       1600 B float32[] Datenwerte [400 × 4 Bytes]
──────────────────────────────────────────────────────────
Gesamt: 4008 Bytes
```

**Magic-Wert:** `0xDEADBEEF` — Paketvalidierung auf dem RPi 5.  
**Dummy-Wert:** `9898.0f` — Füllt inaktive Kanäle; wird per NumPy-Filterung entfernt.

```python
# Python: Deserialisierung (zero-copy view auf Byte-Buffer)
import numpy as np, struct
magic, timestamp = struct.unpack_from("<II", raw, 0)
payload = np.frombuffer(raw, dtype=np.float32, offset=8)
valid   = payload[payload != 9898.0]    # Vektorisierte Filterung
```

```c
// C++ (Teensy): Serialisierung
struct Packet {
    uint32_t magic;          // 0xDEADBEEF
    uint32_t timestamp_us;   // micros()
    float    data[400];      // Telemetriedaten (max. 400 Kanäle)
};
```

### TCP Flash-Protokoll (RPi 5 → RPi Zero)

```
Sender (RPi 5):
  1. uint32_t (Big-Endian): Dateigröße in Bytes
  2. N Bytes: .hex-Dateiinhalt (Intel HEX Format)

Empfänger (RPi Zero) antwortet:
  OK          → Flash erfolgreich
  ERR:<msg>   → Fehler (max. 200 Zeichen)
```

---

## 4. Codebasis-Überblick

### RPi 5 — Zentraler Monitor

```
/opt/power_debug_monitor/
├── main.py              Einstiegspunkt; startet NetworkManager + QApplication
│                        → --simulate Flag für Testbetrieb
├── network_worker.py    Netzwerk-Backend
│   ├── udp_receiver_process()   Multiprocessing-Worker (UDP-Empfang)
│   ├── flash_nodes()            TCP-Flash-Routing (Threading)
│   ├── _send_hex_to_node()      Einzelner Flash-Transfer
│   └── NetworkManager           Klasse: verwaltet Prozesse + Queues
├── config.py            EINZIGE Stelle für alle Konstanten (IPs, Ports, Paketformat)
└── gui/
    ├── __init__.py
    ├── main_window.py   Hauptfenster + QTimer-Loop + Flash-Signalbridge
    ├── tab_table.py     QAbstractTableModel + QTableView (O(1)-Updates)
    ├── tab_plotter.py   PyQtGraph PlotWidget + Freeze-Modus
    ├── tab_visuals.py   Platzhalter Phase 2
    └── tab_params.py    Platzhalter Phase 2
```

### RPi Zero W — Node

```
~/power_debug/
├── uart_receiver.py  UART-Receiver → UDP-Forwarder + LED-Integration
├── flash_daemon.py   TCP-Flash-Server + LED-Integration
└── status_leds.py    GPIO LED-Controller (SharedLib für beide Dienste)
```

### Teensy 4.0

```
teensy_firmware/src/
└── main.cpp   UART-Sender (Serial1) + TX-Buffer + 100 Hz Paketrate
```

---

## 5. Konfiguration anpassen

**Alle systemweiten Parameter** sind in `config.py` zentralisiert:

```python
# config.py — die wichtigsten Anpassungsschrauben

# Variablen umbenennen (Index → lesbarer Name)
VARIABLE_NAMES[0]  = "Motor_L_Speed"
VARIABLE_NAMES[1]  = "Motor_R_Speed"
VARIABLE_NAMES[2]  = "Compass_Heading"
VARIABLE_NAMES[10] = "Akku_Spannung_V"

# Paketgröße anpassen (Teensy-Firmware muss übereinstimmen!)
MAX_FLOATS = 500          # Weniger Kanäle = kleinere Pakete

# GUI-Framerate
GUI_FPS = 60              # 60 Hz statt 30 Hz (mehr CPU-Last)

# Plot-History
PLOT_HISTORY_SEC = 10     # 10 Sekunden Verlauf statt 5

# Queue-Tiefe
DATA_QUEUE_MAXSIZE = 500  # Mehr Puffer bei schlechtem WLAN
```

> ⚠️ Änderungen an `MAX_FLOATS` und `PACKET_HEADER_MAGIC` müssen in `config.py` **und** `main.cpp` (Teensy) synchron erfolgen.

---

## 6. GUI erweitern

### Neuen Tab hinzufügen

1. **Widget-Datei anlegen:** `gui/tab_myfeature.py`

```python
# gui/tab_myfeature.py — Minimalstruktur
from PyQt6.QtWidgets import QWidget, QVBoxLayout

class MyFeatureWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        # ... eigene Widgets hier

    def update_data(self, values: np.ndarray) -> None:
        """Wird vom GUI-Timer aufgerufen (~30 Hz)."""
        pass
```

2. **In `main_window.py` einbinden:**

```python
# Importieren
from gui.tab_myfeature import MyFeatureWidget

# In _build_tabs():
self._tab_myfeature = MyFeatureWidget()
tabs.addTab(self._tab_myfeature, "🔧  Mein Feature")

# In _poll_data():
self._tab_myfeature.update_data(latest)
```

### Neues Qt-Signal für Thread-Kommunikation

Für Callbacks aus Threads (z.B. Netzwerk-Events):

```python
class _MySignalBridge(QObject):
    my_event = pyqtSignal(str, int)   # Typen definieren

# In MainWindow.__init__:
self._my_bridge = _MySignalBridge()
self._my_bridge.my_event.connect(self._on_my_event)

# Aus einem Thread heraus (thread-sicher!):
self._my_bridge.my_event.emit("Wert", 42)

# Slot (immer im GUI-Thread ausgeführt):
def _on_my_event(self, text: str, value: int) -> None:
    self._sb.showMessage(f"{text}: {value}")
```

---

## 7. Phase-2-Features implementieren

### Tab 3 — Grafisches System-Overlay

**Ziel:** Roboter-Schemazeichnung mit Live-Telemetrie-Overlays.

**Empfohlene Vorgehensweise:**

```python
# gui/tab_visuals.py — Implementierungsgerüst
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtGui import QPixmap

class SystemVisualsWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # Roboter-Bild laden
        self._scene = pg.GraphicsLayoutWidget()
        self._view  = self._scene.addViewBox(lockAspect=True)

        img = pg.ImageItem(QPixmap("robot_schema.png").toImage())
        self._view.addItem(img)

        # Overlay-Region für z.B. Motor-Temperatur
        self._overlay_motor_l = pg.ROI([50, 100], [30, 30], pen="r")
        self._view.addItem(self._overlay_motor_l)

        layout.addWidget(self._scene)

    def update_data(self, values: np.ndarray) -> None:
        # Farbe basierend auf Motorstrom
        temp = float(values[0]) if len(values) > 0 else 0.0
        color = "#ff0000" if abs(temp) > 3.0 else "#00ff00"
        self._overlay_motor_l.setPen(color)
```

### Tab 4 — Parameter-Editor

**Ziel:** 100–200 editierbare Parameter per TCP an den Roboter senden.

**Datenmodell-Entwurf:**

```python
# config_schema.py — Parameter-Schema
PARAMS = {
    "Motor_Max_PWM":    {"default": 255, "min": 0,   "max": 255, "type": int},
    "PID_Drive_Kp":     {"default": 1.2, "min": 0.0, "max": 10.0, "type": float},
    "Ball_Threshold":   {"default": 50,  "min": 0,   "max": 100,  "type": int},
    # ...
}
```

**TCP-Protokoll für Parameter (Port 7001):**

```
Senden: JSON-Blob { "params": { "Motor_Max_PWM": 200, ... } }
        Größe (4B uint32) + JSON-Bytes
Antwort: "OK" oder "ERR:<msg>"
```

---

## 8. Neue Hardware integrieren

### Mehr als 2 Nodes unterstützen

1. In `config.py` neue IPs/Ports definieren:
```python
NODE3_IP = "192.168.42.13"
UDP_PORT_NODE3 = 5003
TCP_FLASH_PORT_NODE3 = 6003
```

2. In `NetworkManager.__init__()`:
```python
self.queue_node3: mp.Queue = mp.Queue(maxsize=DATA_QUEUE_MAXSIZE)
self._proc3 = mp.Process(
    target=udp_receiver_process,
    args=(UDP_PORT_NODE3, 3, self.queue_node3, self._stop_event),
    daemon=True, name="UDP-Node3",
)
```

3. Node-Selektor in `main_window.py` um Node 3 erweitern.

### Anderen Mikrocontroller als Teensy verwenden

1. **Paketformat beibehalten** (Magic + Timestamp + float32[])
2. In `flash_daemon.py` den MCU-Typ anpassen:
```python
MCU = "TEENSY41"           # oder "uno", "mega2560", etc.
TEENSY_CLI = "avrdude"     # für Arduino-Boards
```
3. `teensy_loader_cli`-Argumente in `flash_daemon.py → _handle_client()` anpassen.

### Höhere Baudrate

Der Teensy 4.0 und der RPi Zero W PL011-UART unterstützen bis zu 8 Mbps.
Beide Seiten müssen exakt denselben Wert haben:

```python
# uart_receiver.py — RPi Zero W
UART_BAUD = 8_000_000   # 8 Mbps (experimentell — Kabel < 20 cm empfohlen)
```

```cpp
// main.cpp (Teensy)
static constexpr uint32_t UART_BAUD = 8'000'000UL;  // muss mit RPi übereinstimmen
// Serial1.begin() in setup() verwendet UART_BAUD automatisch
```

> ⚠️ Bei > 4 Mbps: kurze, direkte Kabel verwenden. Sync-Verluste in den Logs
> (`journalctl -u uart-receiver`) signalisieren zu hohe Baudrate.

> **Achtung:** Leitungslängen über ~10 cm können bei höheren Frequenzen zu Übertragungsfehlern führen. Ferritperlen und 22-Ω-Reihenwiderstände können helfen.

---

## 9. Testing & Simulation

### Simulatormodus (kein Hardware nötig)

```bash
# Startet beide UDP-Streams simultan auf localhost
python3 main.py --simulate
```

Der `_udp_simulator_process` in `main.py` sendet 100 Hz Sinuswellenpakete für beide Nodes. Er nutzt denselben `stop_event` wie der `NetworkManager` und wird automatisch mit beendet.

### Unit-Tests (Vorschlag für zukünftige Tests)

```python
# tests/test_network_worker.py
import numpy as np, struct, socket, threading, time
from network_worker import udp_receiver_process
import multiprocessing as mp

def test_packet_filtering():
    """Testet, ob Dummy-Werte (9898) korrekt gefiltert werden."""
    q = mp.Queue()
    ev = mp.Event()
    magic = 0xDEADBEEF
    data = np.zeros(400, dtype=np.float32)
    data[500:] = 9898.0   # Hälfte Dummy

    raw = struct.pack("<II", magic, 1234) + data.tobytes()

    # ... UDP-Paket an Port 15001 senden und Queue prüfen
    result = q.get(timeout=1.0)
    node_id, ts, values = result
    assert len(values) == 500    # Nur echte Werte
    assert 9898.0 not in values
```

### Netzwerk-Performance messen

```bash
# Paketrate auf RPi 5 messen
sudo tcpdump -i wlan0 udp port 5001 -q 2>/dev/null | \
    awk '{count++} NR%100==0 {print count/100 " pkt/s"; count=0}'

# Latenz messen (UART → UDP → RPi5)
# Timestamp im Paket nutzen: packet[4:8] = Teensy-micros()
# Differenz zu RPi-5-Empfangszeit = Gesamtlatenz
```

---

## 10. Performance-Profiling

### Bottleneck-Analyse

| Komponente | Typischer Verbrauch | Engpass? |
|---|---|---|
| UDP-Empfänger (pro Node) | ~1–3 % CPU (RPi 5) | ❌ Nein |
| NumPy-Filterung | Nahezu 0 (vektorisiert) | ❌ Nein |
| GUI-Timer (33 ms) | ~5–15 % CPU | Abhängig von Kanalzahl |
| PyQtGraph Plot-Render | ~10–20 % | ⚠️ Bei vielen Punkten |
| Queue-Transfer | ~< 1 ms Latenz | ❌ Nein |

### GUI-Optimierungen

```python
# tab_plotter.py: Antialiasing deaktivieren (Standard, bereits gesetzt)
pg.setConfigOptions(antialias=False, useOpenGL=False)

# Weniger Datenpunkte rendern
self._spin_pts.setValue(100)   # Statt 200+

# Update-Rate reduzieren (wenn 30 Hz zu viel)
# In config.py:
GUI_FPS = 20   # 50 ms statt 33 ms
```

### Speicher-Profiling

```python
# Ringbuffer-Größe überwachen
import sys
buf_mb = sys.getsizeof(list(self._buffer)) / 1024 / 1024
print(f"Plot-Buffer: {buf_mb:.2f} MB")
# PLOT_BUFFER_SIZE = 500 Samples → ~2 KB pro Variable (unkritisch)
```

---

## 11. Deployment & Updates

### Anwendung aktualisieren (RPi 5)

```bash
# Neue Dateien ins Installationsverzeichnis kopieren
sudo cp main.py network_worker.py /opt/power_debug_monitor/
sudo cp gui/*.py /opt/power_debug_monitor/gui/
sudo chown -R pi:pi /opt/power_debug_monitor/

# Anwendung neu starten
pkill -f "python3 main.py"   # GUI beenden
power-debug-monitor &         # Neu starten
```

### Node-Dienste aktualisieren

```bash
# Neue Dateien auf den Node kopieren
scp uart_receiver.py flash_daemon.py status_leds.py pi@192.168.42.11:~/power_debug/

# Dienste neu starten
ssh pi@192.168.42.11 "sudo systemctl restart uart-receiver flash-daemon"
```

### Über-die-Luft (OTA) Update via RPi 5

Da der RPi 5 ein vollständiges Linux-System ist, kann ein Update-Skript per USB-Gadget-Verbindung eingespielt werden:

```bash
# Auf dem Entwicklungs-PC:
rsync -avz --exclude='.git' power_debug_system/ pi@192.168.7.1:~/power_debug_update/
ssh pi@192.168.7.1 "sudo bash ~/power_debug_update/setup_rpi5.sh /opt/power_debug_monitor"
```

---

## 12. Bekannte Einschränkungen & TODOs

### Aktuell bekannte Einschränkungen

| # | Problem | Priorität | Workaround |
|---|---|---|---|
| 1 | LED-Netzwerk-Status wird alle 15 s geprüft — kein Echtzeit-Disconnect | Niedrig | Heartbeat-Timeout in Phase 2 |
| 2 | GUI-LED-Anzeige (⬤ rot/grün) basiert auf Paket-Empfang, kein Heartbeat | Mittel | Flash-Verbindungstest als Proxy |
| 3 | Bei vollem Queue: älteste Pakete werden still verworfen (kein GUI-Feedback) | Niedrig | `pkt_drop`-Counter in Statusleiste zeigen |
| 4 | Keine TLS/Verschlüsselung bei der Firmware-Übertragung | Niedrig | WLAN-AP ist isoliertes Netzwerk |
| 5 | `main_window.py`: LED-Timeout für inaktiven Node nach 3 s noch nicht implementiert | Mittel | Siehe TODO-Kommentar in `_update_statusbar()` |
| 6 | Tab 3 + Tab 4 sind Platzhalter | Geplant | Phase-2-Implementation |

### TODOs im Code

```bash
# Alle TODOs und Platzhalter finden:
grep -rn "TODO\|Phase 2\|Zukunft\|HIER\|FIXME" /opt/power_debug_monitor/
```

---

## 13. Roadmap

### Phase 1 — Abgeschlossen ✅
- [x] Teensy UART-Sender (Serial1, 4 Mbps, non-blocking TX)
- [x] RPi Zero UART→UDP Forwarder mit Magic-Header-Synchronisation
- [x] RPi 5 UDP-Empfänger (Multiprocessing, NumPy-Filterung)
- [x] PyQt6 GUI mit Live-Tabelle und Plotter
- [x] Freeze-Modus für Plotter
- [x] TCP Flash-Routing (Node 1, Node 2, Beide)
- [x] USB-C Gadget Mode (PC ↔ RPi 5)
- [x] Status-LEDs für RPi Zero Nodes
- [x] Setup-Skripte für RPi 5 und RPi Zero W
- [x] Autostart / systemd Services
- [x] Simulator-Modus (--simulate)

### Phase 2 — Geplant 🔲
- [ ] **Tab 3:** Grafisches System-Overlay mit Roboter-Schema
  - QGraphicsView / pyqtgraph.ImageItem
  - Farb-Overlays per Telemetrie-Grenzwerte
  - Alarm-Markierungen bei kritischen Werten
- [ ] **Tab 4:** Parameter-Editor
  - QDataWidgetMapper + JSON-Backing-Store
  - Validierung mit Min/Max-Grenzen
  - TCP-Übertragung an aktiven Node (Port 7001)
- [ ] **Heartbeat-Protokoll:** Periodische Ping-Pakete Node→RPi5 für Verbindungsüberwachung
- [ ] **LED-Timeout:** GUI-LEDs nach 3 s ohne Paket auf Rot/Grau setzen
- [ ] **Pkt/s Anzeige pro Node:** Separate Counters in der Statusleiste
- [ ] **CSV-Export:** Telemetrie-Aufzeichnung in Datei speichern
- [ ] **Replay-Modus:** Aufgezeichnete Daten abspielen

### Phase 3 — Ideen 💡
- [ ] Web-Interface für Zugriff vom PC ohne USB-Gadget
- [ ] Alarmierung per akustischem Signal bei Grenzwertüberschreitung
- [ ] Multi-Roboter (>2 Nodes) mit automatischer Node-Discovery
- [ ] Integration Kamera-Feed (RPi Zero → MJPEG-Stream)
- [ ] Automatisches Logging bei Spielbeginn / Spielende (RoboCup)
