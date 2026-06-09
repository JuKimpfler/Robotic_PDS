# Power Debugging & Flashing System (Multi-Node Ecosystem)
 
Dieses Repository enthält den vollständigen Implementierungsplan, die Architekturdefinition und die Softwarekomponenten für das drahtlose **High-Performance Power-Debugging-System**. Das System ist für die simultane Anbindung von zwei autonomen Nodes (jeweils bestehend aus einem Teensy 4.0 und einem Raspberry Pi Zero W) an einen zentralen Debug-Monitor (Raspberry Pi 5) ausgelegt.
 
---
 
## 1. Systemübersicht & Ziele
 
Das System ermöglicht das zeitkritische Erfassen, Filtern und Visualisieren von Telemetriedaten sowie das selektive oder parallele Flashen von Firmware über ein dediziertes WLAN-Netzwerk.
 
### Kernmetriken & Anforderungen
* **Datendurchsatz:** 500 bis 1.000 `float32`-Werte alle 10 Millisekunden pro Node (entspricht bis zu **100.000 Floats/Sekunde** oder ~400 KB/s Netto-Datenrate).
* **Echtzeit-Anzeigeverhalten:** Flüssige PyQt/PySide-GUI mit konstanter Framerate (~30–60 Hz) ohne Blockierung des UI-Threads durch den massiven Netzwerk-Stream.
* **Filterung:** Vektorisierte Eliminierung von Dummy-Werten (`9898`) direkt nach dem Paketempfang mittels NumPy.
* **Dual-Node-Fähigkeit:** Zwei Raspberry Pi Zero W sind permanent verbunden. Über die GUI kann dynamisch ausgewählt werden, von welchem Node die Debug-Daten visualisiert werden.
* **Targeted Flashing:** Empfang einer `.hex`-Datei vom PC über den USB-C Gadget-Modus des RPi 5. Die Datei kann wahlweise auf Node 1, Node 2 oder simultan auf beide Nodes übertragen und geflasht werden.
---
 
## 2. Systemarchitektur & Netzwerk-Topologie
 
Der Raspberry Pi 5 fungiert als zentraler Kommunikationsknotenpunkt (**Stand-alone Access Point**). Die Raspberry Pi Zero W Nodes verbinden sich automatisch beim Booten mit diesem Hotspot.
 
 
```
 
+-----------------------------------------------------------------------------+
|                                  Entwicklungs-PC                            |
+-----------------------------------------------------------------------------+
|
v (USB-C OTG Gadget Mode: TCP/IP Bridge)
+-----------------------------------------------------------------------------+
|                     Raspberry Pi 5 (Zentraler Debug-Monitor)               |
|  - Wi-Fi Hotspot (AP Mode)                                                  |
|  - PyQt6 / PyQtGraph GUI Dashboard                                          |
+-----------------------------------------------------------------------------+
/                                                       \
/ (Wi-Fi: UDP Data / TCP Flash)                           \ (Wi-Fi: UDP Data / TCP Flash)
v                                                           v
+-----------------------------+                             +-----------------------------+
|    Raspberry Pi Zero W (1)  |                             |    Raspberry Pi Zero W (2)  |
|  - SPI Receiver Backend     |                             |  - SPI Receiver Backend     |
|  - TCP Flash Daemon         |                             |  - TCP Flash Daemon         |
+-----------------------------+                             +-----------------------------+
|                                                           |
| (SPI Telemetry & USB Flash)                               | (SPI Telemetry & USB Flash)
v                                                           v
+-----------------------------+                             +-----------------------------+
|         Teensy 4.0 (1)      |                             |         Teensy 4.0 (2)      |
+-----------------------------+                             +-----------------------------+
 
```
 
### Netzwerk-Konfiguration
* **Zentraler AP (RPi 5):** IP `192.168.42.1`
* **Node 1 (RPi Zero W #1):** Statische IP `192.168.42.11`
* **Node 2 (RPi Zero W #2):** Statische IP `192.168.42.12`
### Port-Zuweisungen
| Port | Protokoll | Richtung | Beschreibung |
| :--- | :--- | :--- | :--- |
| `5001` | UDP | Node -> RPi 5 | Telemetrie-Stream von Node 1 |
| `5002` | UDP | Node -> RPi 5 | Telemetrie-Stream von Node 2 |
| `6001` | TCP | RPi 5 -> Node 1 | Firmware-Übertragung & Flash-Trigger für Node 1 |
| `6002` | TCP | RPi 5 -> Node 2 | Firmware-Übertragung & Flash-Trigger für Node 2 |
| `7001` | TCP | RPi 5 -> Active Node | Parameter-Konfiguration (Zukunft) |
 
---
 
## 3. Daten-Pipeline & Performance-Optimierung
 
Um Python-seitig die geforderte Performance ohne Frame-Drops in der GUI zu erreichen, wird strikt das Prinzip der **Prozesstrennung (Multiprocessing)** angewendet.
 
### 1. Datenkompression & Binär-Streaming (Teensy & RPi Zero)
Die Daten werden auf dem Teensy nicht als Text (JSON/CSV) formatiert, sondern als nativer Binärblock via SPI übertragen.
* **Paket-Struktur (C++ / Python Struct):** `[Header: uint32_t] [Timestamp: uint32_t] [Data: float32_t * 1000]`
* Der RPi Zero verarbeitet die Daten nicht, sondern leitet die rohen Byte-Blöcke per UDP direkt an die IP des RPi 5 weiter, um CPU-Zyklen zu sparen.
### 2. High-Speed Empfänger auf dem RPi 5 (Netzwerk-Prozess)
Ein dedizierter, vom GUI-Thread isolierter `multiprocessing.Process` lauscht auf den UDP-Ports. 
 
```python
# Konzept des hocheffizienten Empfangs- und Filter-Workers
import socket
import numpy as np
import multiprocessing
 
def udp_receiver_process(port, shared_queue):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024) # 1MB Buffer
    
    while True:
        data, _ = sock.recvfrom(4100) # Grober Buffer für Header + Floats
        # Schnelles Entpacken mit NumPy direkt aus dem Byte-Buffer
        payload = np.frombuffer(data, dtype=np.float32, offset=8) 
        
        # Hochoptimierte Filterung der Dummy-Werte (9898) via Vektorisierung
        filtered_data = payload[payload != 9898.0]
        
        if filtered_data.size > 0:
            shared_queue.put(filtered_data)
 
```
 
### 3. GUI-Thread-Entkopplung via Shared Ringbuffer
 
Die GUI greift nicht bei jedem Paket auf die Queue zu, sondern liest mittels eines `QTimer` alle **33 ms (~30 Hz)** gesammelt alle aufgelaufenen Datenpunkte aus der Queue, transformiert sie in globale NumPy-Arrays für den Plotter und aktualisiert die Tabelle. Das reduziert die Qt-Layout-Berechnungen drastisch.
 
---
 
## 4. USB-C Gadget Mode & Flashing-Infrastruktur
 
### 1. RPi 5 als USB-Gadget (PC zu RPi 5)
 
Der RPi 5 wird über das Linux-Kernel-Modul `g_ether` so konfiguriert, dass er am PC als USB-Netzwerkkarte (RNDIS/CDC-Ethernet) erkannt wird. Der PC sieht den RPi 5 unter einer festen IP-Adresse (z. B. `192.168.7.1`). Über ein Web-Interface oder ein Python-Upload-Skript sendet der PC die neue `.hex`-Datei an das Steuerungsskript auf dem RPi 5.
 
### 2. Selektiver Flash-Verteiler (Routing)
 
In der GUI des RPi 5 befindet sich ein Kontrollzentrum für den Flash-Vorgang. Je nach Nutzerauswahl wird die Datei weitergeleitet:
 
```
                  [ PC (.hex-Datei) ]
                           |
                           v (USB-C Gadget Network)
                   [ RPi 5 Control ]
                  /        |        \\
                 /         |         \\  (GUI-Auswahl)
                v          v          v
          [ Nur Node 1 ] [ Beide ] [ Nur Node 2 ]
                |          | |          |
        +-------+          | |          +-------+
        |                  | |                  |
        v                  v v                  v
(TCP -> RPi Zero 1) <------+ +------> (TCP -> RPi Zero 2)
 
```
 
### 3. Lokales Flashing auf dem RPi Zero
 
Sobald ein RPi Zero W die Datei vollständig über den TCP-Port empfangen hat, führt er das native Kommandozeilentool `teensy_loader_cli` aus:
 
```bash
teensy_loader_cli --mcu=TEENSY40 -w -v firmware.hex
 
```
 
Der Hardware-Reboot des Teensy wird dabei automatisch vom Loader über die USB-Verbindung zwischen RPi Zero und Teensy initiiert.
 
---
 
## 5. GUI Architektur & Layout (PyQt / PySide)
 
Das Frontend ist modular über ein `QTabWidget` aufgebaut. Alle Widgets nutzen performante Ansichten (`QTableView` statt `QTableWidget`), um Speicher- und Render-Overhead zu minimieren.
 
### Globale Steuerungsleiste (Über den Tabs platziert)
 
* **Node-Selektor (Dropdown/RadioButtons):** `[ Aktiver Debug-Knoten: Node 1 | Node 2 ]`
* Schaltet dynamisch um, welche UDP-Queue an den Live-Plotter und die Tabelle gekoppelt ist. Die Daten des inaktiven Knotens werden im Hintergrund verworfen oder optional gecached, belasten aber nicht das Rendering.
* **Flash-Management-Zone:**
* Status-LEDs für Verbindungszustand von Node 1 und Node 2.
* Ziel-Auswahl für Upload: `Checkbox Node 1` | `Checkbox Node 2`.
* Button: `[ Firmware (.hex) hochladen & flashen ]`.
### Tab-Struktur
 
#### Tab 1: Live-Telemetrie Tabelle
 
* **Technik:** Nutzt ein Custom `QAbstractTableModel`.
* **Funktion:** Zeigt alle Variablen-IDs, den aktuellen Wert sowie die akkumulierten `Min` und `Max`-Werte.
* **Optimierung:** Die Berechnung von Min/Max erfolgt über `np.amin()` und `np.amax()` auf dem Daten-Array, bevor die Tabelle aktualisiert wird.
#### Tab 2: High-Rate Live-Plotter
 
* **Technik:** `pyqtgraph.PlotWidget` mit deaktiviertem Antialiasing für maximale Rendergeschwindigkeit.
* **Funktion:** * Dropdown-Menü zur Auswahl der zu plottenden Variablen-ID.
* **Freeze-Modus (Pause-Button):** Entkoppelt den Plotter temporär vom Live-Datenstrom. Die UI stoppt das Scrollen, sodass der Nutzer den Graph via Maus-Pan und Zoom präzise analysieren kann. Im Hintergrund läuft die Daten-Queue weiter, Datenverlust wird vermieden.
#### Tab 3: Grafische Systemansicht (Vorbereitet für Phase 2)
 
* **Technik:** `QGraphicsView` / `pg.ImageItem`.
* **Ziel:** Laden eines schematischen Bildes des Roboters/Systems. Dynamische Overlays werden in Abhängigkeit der Live-Werte Bildbereiche farblich erhellen, abdunkeln oder Text-Callouts einblenden.
#### Tab 4: Parameter-Konfiguration (Vorbereitet für Phase 2)
 
* **Technik:** `QDataWidgetMapper` gekoppelt an eine Konfigurationsdatei.
* **Ziel:** Modifizieren von 100–200 Systemparametern. Ein Button "Parameter an Roboter übertragen" sendet das gesamte Parametersatz-Paket per gesicherter TCP-Verbindung an den aktuell ausgewählten Node.
---
 
## 6. Verzeichnisstruktur des Projekts
 
```
power_debug_system/
│
├── rpi5_monitor/               # Code für den zentralen Raspberry Pi 5
│   ├── main.py                 # Applikations-Einstiegspunkt & GUI-Thread
│   ├── network_worker.py       # Multiprocessing UDP-Empfänger & TCP-Flasher
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # Hauptfenster-Layout & Globale Steuerung
│   │   ├── tab_table.py        # Tab 1: Tabellenansicht (QAbstractTableModel)
│   │   ├── tab_plotter.py      # Tab 2: PyQtGraph Live-Plotter mit Freeze-Option
│   │   ├── tab_visuals.py      # Tab 3: Platzhalter für Grafische Overlays
│   │   └── tab_params.py       # Tab 4: Platzhalter für Parameter-Editor
│   └── config.py               # IP-Adressen, Ports und Variablen-Mappings
│
├── rpi_zero_node/              # Code für die Raspberry Pi Zero W Nodes
│   ├── spi_receiver.py         # Liest SPI-Daten vom Teensy und streamt per UDP
│   ├── flash_daemon.py         # TCP-Server, wartet auf .hex-Dateien & ruft teensy_loader auf
│   └── setup_node.sh           # Automatisches Setup-Skript für Hostnamen/IPs
│
├── teensy_firmware/            # C++ Code für die Teensy 4.0 Controller
│   ├── src/
│   │   └── main.cpp            # High-Speed SPI Data Packer & Sende-Loop
│   └── platformio.ini          # Konfiguration für PlatformIO
│
└── docs/
    └── network_setup.md        # Anleitung zur Konfiguration des RPi 5 AP Mode
 
```
 
---
 
## 7. Installations- & Schnelleinrichtungsanleitung
 
### 1. Vorbereitung des Raspberry Pi 5 (Access Point & Gadget Mode)
 
#### A. Wi-Fi Access Point einrichten (mittels NetworkManager)
 
```bash
sudo nmcli device wifi hotspot ifname wlan0 ssid PowerDebugAP password "HighSpeedDebug123"
sudo nmcli connection modify Hotspot ipv4.addresses 192.168.42.1/24
sudo nmcli connection up Hotspot
 
```
 
#### B. USB-C Gadget Mode aktivieren
 
Trage folgende Zeile in `/boot/firmware/config.txt` ein:
 
```text
dtoverlay=dwc2,dr_mode=peripheral
 
```
 
Füge in `/boot/firmware/cmdline.txt` nach `rootwait` folgendes hinzu:
 
```text
modules-load=dwc2,g_ether
 
```
 
### 2. Vorbereitung der Raspberry Pi Zero W Nodes
 
Verbinde die Zeros mit dem WLAN `PowerDebugAP` und weise ihnen über `/etc/dhcpcd.conf` oder `NetworkManager` die statischen IPs `192.168.42.11` (Node 1) und `192.168.42.12` (Node 2) zu.
 
Installiere die benötigten Pakete für das Flashing:
 
```bash
sudo apt-get update
sudo apt-get install teensy-loader-cli spidev
 
```
 
### 3. Abhängigkeiten auf dem RPi 5 installieren
 
```bash
pip install numpy pyqtgraph PyQt6
 
```
 
### 4. System starten
 
1. Starte den `flash_daemon.py` und `spi_receiver.py` auf beiden RPi Zeros (idealerweise als `systemd`-Service).
2. Starte die Haupt-GUI auf dem RPi 5:
```bash
python rpi5_monitor/main.py
 
```
 
 
 
---
 
## 8. Entwicklungs-Roadmap
 
* [ ] **Meilenstein 1:** Implementierung des C++ SPI-Packers auf dem Teensy und der UDP-Weiterleitung auf dem RPi Zero.
* [ ] **Meilenstein 2:** Aufbau des RPi 5 Netzwerk-Workers mit NumPy-Filterung (`9898`-Erkennung) und Benchmarking der Transferrate.
* [ ] **Meilenstein 3:** Finalisierung der PyQt6-Grundstruktur (Tabelle und PyQtGraph-Plotter mit Freeze-Funktion).
* [ ] **Meilenstein 4:** Implementierung des USB-C Gadget Empfängers auf dem RPi 5 und der TCP-Routing-Logik für das selektive Flashen der Nodes.
* [ ] **Meilenstein 5 (Zukunft):** Integration des grafischen Overlay-Tabs und des Parameter-Editors.