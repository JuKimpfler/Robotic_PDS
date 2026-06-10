# Power Debug System — Setup & Bedienungsanleitung

> **Version:** 1.0  |  **Zielplattform:** RPi 5 + 2× RPi Zero W + 2× Teensy 4.0  
> **Anwendungsfall:** RoboCup Junior Soccer — drahtloses Echtzeit-Debugging & Firmware-Flashing

---

## Inhaltsverzeichnis

1. [Hardware-Voraussetzungen & Stückliste](#1-hardware-voraussetzungen--stückliste)
2. [Verdrahtung](#2-verdrahtung)
   - 2.1 [Teensy 4.0 ↔ RPi Zero W (SPI)](#21-teensy-40--rpi-zero-w-spi)
   - 2.2 [Status-LEDs am RPi Zero W](#22-status-leds-am-rpi-zero-w)
3. [Raspberry Pi 5 einrichten](#3-raspberry-pi-5-einrichten)
   - 3.1 [Betriebssystem installieren](#31-betriebssystem-installieren)
   - 3.2 [Setup-Skript ausführen](#32-setup-skript-ausführen)
   - 3.3 [Verifizierung](#33-verifizierung)
4. [Raspberry Pi Zero W Nodes einrichten](#4-raspberry-pi-zero-w-nodes-einrichten)
   - 4.1 [Betriebssystem installieren](#41-betriebssystem-installieren)
   - 4.2 [Setup-Skript ausführen](#42-setup-skript-ausführen)
   - 4.3 [LED-Statusanzeige verstehen](#43-led-statusanzeige-verstehen)
5. [Entwicklungs-PC vorbereiten](#5-entwicklungs-pc-vorbereiten)
6. [Erster Start & Systemtest](#6-erster-start--systemtest)
7. [GUI-Bedienung](#7-gui-bedienung)
   - 7.1 [Steuerungsleiste](#71-steuerungsleiste)
   - 7.2 [Tab 1 — Live-Tabelle](#72-tab-1--live-tabelle)
   - 7.3 [Tab 2 — Live-Plotter](#73-tab-2--live-plotter)
   - 7.4 [Firmware flashen](#74-firmware-flashen)
8. [Simulator-Modus](#8-simulator-modus-kein-teensy-nötig)
9. [Netzwerk-Referenz](#9-netzwerk-referenz)
10. [Troubleshooting](#10-troubleshooting)
11. [Logs & Diagnose](#11-logs--diagnose)

---

## 1. Hardware-Voraussetzungen & Stückliste

### Pflichtkomponenten

| Anzahl | Komponente | Hinweis |
|:---:|---|---|
| 1 | **Raspberry Pi 5** (4 GB oder 8 GB) | Zentraler Debug-Monitor |
| 1 | MicroSD-Karte ≥ 16 GB (Class 10 / A1) | Für RPi 5 |
| 2 | **Raspberry Pi Zero W** | Nodes (einer pro Roboter) |
| 2 | MicroSD-Karte ≥ 8 GB | Für RPi Zero W |
| 2 | **Teensy 4.0** | Mikrokontroller auf dem Roboter |
| 1 | USB-C Kabel (Daten, nicht nur Ladekabel) | PC ↔ RPi 5 |
| 2 | Micro-USB Kabel | RPi Zero W ↔ Teensy (Stromversorgung + Flash) |
| 1 | Monitor, Maus, Tastatur | Für die RPi-5-Ersteinrichtung |

### Optionale Komponenten (LEDs)

| Anzahl | Komponente | Hinweis |
|:---:|---|---|
| 8 | LED 5 mm (2× Grün, 2× Blau, 2× Gelb, 2× Rot) | 4 LEDs pro Node |
| 8 | Widerstand 330 Ω | 1 pro LED |
| 2 | Lochrasterplatine oder Breadboard | Zum Montieren der LEDs |
| — | Jumper-Kabel (Female-Female) | GPIO ↔ LED-Platine |

---

## 2. Verdrahtung

### 2.1 Teensy 4.0 ↔ RPi Zero W (SPI1)

Die Verbindung erfolgt über den zweiten Hardware-SPI-Bus (SPI1 / LPSPI3). Der RPi Zero W ist **SPI-Master**, der Teensy ist **SPI-Slave**.

```
Teensy 4.0  (SPI1 / LPSPI3)        RPi Zero W
──────────────────────────────────────────────────────────
Pin 27  (SCK1)  ──────────────────  Pin 23  (GPIO11, SCLK)
Pin 26  (MOSI1) ──────────────────  Pin 19  (GPIO10, MOSI)
Pin  1  (MISO1) ──────────────────  Pin 21  (GPIO 9, MISO)
Pin 30  (CS)    ──────────────────  Pin 24  (GPIO 8, CE0)
Pin  9  (DTRDY) ──────────────────  Pin 11  (GPIO17)       ← DATA_READY Signal
GND             ──────────────────  Pin  6  (GND)
3,3 V           ──────────────────  Pin  1  (3,3 V)        ← Optional (nur wenn nötig)
```

> ⚠️ **Wichtig:** Teensy 4.0 arbeitet mit 3,3 V Logikpegel — kompatibel mit dem RPi Zero W. Kein Pegelwandler nötig.  
> **SPI1 (LPSPI3):** Pin 30 dient als alternativer Chip-Select anstelle des Standard-CS (Pin 0).

### 2.2 Status-LEDs am RPi Zero W

Jeder Node hat 4 Status-LEDs. Schaltung pro LED (Reihenschaltung):

```
GPIO-Pin (3,3 V) ──[330 Ω]──[>|]── GND
                              LED
                              Anode (+) zum Widerstand
                              Kathode (–) zu GND
```

#### Pin-Belegung (BCM-Nummerierung)

| LED | Farbe | GPIO (BCM) | Physischer Pin | Bedeutung |
|-----|-------|:---:|:---:|---|
| Heartbeat | 🟢 Grün | GPIO 27 | Pin 13 | Blinkt 1 Hz = System läuft |
| Netzwerk | 🔵 Blau | GPIO 22 | Pin 15 | AN = WLAN verbunden |
| Daten | 🟡 Gelb | GPIO 24 | Pin 18 | Blinkt = Teensy sendet Pakete |
| Flash/Fehler | 🔴 Rot | GPIO 25 | Pin 22 | AN = Flash läuft |

#### RPi Zero W Pinout (relevante Pins)

```
         3V3  [ 1] [ 2]  5V
       GPIO2  [ 3] [ 4]  5V
       GPIO3  [ 5] [ 6]  GND   ← GND für LEDs
       GPIO4  [ 7] [ 8]  GPIO14
         GND  [ 9] [10]  GPIO15
      GPIO17  [11] [12]  GPIO18   ← GPIO17 = DATA_READY (Teensy)
      GPIO27  [13] [14]  GND      ← GPIO27 = Heartbeat LED 🟢
      GPIO22  [15] [16]  GPIO23   ← GPIO22 = Netzwerk LED 🔵
         3V3  [17] [18]  GPIO24   ← GPIO24 = Daten LED 🟡
GPIO10/MOSI   [19] [20]  GND
 GPIO9/MISO   [21] [22]  GPIO25   ← GPIO25 = Flash/Fehler LED 🔴
GPIO11/SCLK   [23] [24]  GPIO8/CE0
         GND  [25] [26]  GPIO7
```

---

## 3. Raspberry Pi 5 einrichten

### 3.1 Betriebssystem installieren

1. **Raspberry Pi Imager** herunterladen: https://www.raspberrypi.com/software/
2. OS wählen: **Raspberry Pi OS (64-bit)** mit Desktop
3. Vor dem Schreiben (Zahnrad-Symbol): SSH aktivieren, Benutzername `pi` setzen
4. MicroSD beschreiben und in den RPi 5 einsetzen
5. RPi 5 mit Monitor, Tastatur und Maus verbinden und starten
6. Ersteinrichtung abschließen (Land, Sprache, Passwort)

### 3.2 Setup-Skript ausführen

```bash
# Projektdateien auf den RPi 5 kopieren
# Option A: Via USB-Stick
cp -r /media/pi/USB_STICK/power_debug_system ~/

# Option B: Git (falls Netzwerk verfügbar)
git clone https://github.com/dein-repo/power_debug_system.git ~/power_debug_system

# Ins Projektverzeichnis wechseln
cd ~/power_debug_system

# Setup-Skript ausführen
sudo bash setup_rpi5.sh
```

Das Skript führt folgende Schritte automatisch durch:

| Schritt | Aktion |
|---|---|
| 1 | Hostname → `power-debug-monitor` |
| 2 | Systempakete installieren (PyQt6, XCB-Libs) |
| 3 | Python-Pakete installieren (pyqtgraph, numpy) |
| 4 | Anwendung → `/opt/power_debug_monitor/` |
| 5 | WLAN-AP `PowerDebugAP` einrichten (192.168.42.1) |
| 6 | USB-C Gadget Mode aktivieren (g_ether) |
| 7 | Launcher `/usr/local/bin/power-debug-monitor` |
| 8 | Autostart (XDG + LXDE + labwc + systemd) |
| 9 | Desktop-Autologin aktivieren |

**Neustart nach Abschluss:**
```bash
sudo reboot
```

### 3.3 Verifizierung

Nach dem Neustart sollte der RPi 5:

```bash
# 1. WLAN-AP läuft?
nmcli connection show PowerDebugAP | grep -E "STATE|ipv4"
# Erwartet: ipv4.addresses: 192.168.42.1/24

# 2. IP-Adresse korrekt?
ip addr show wlan0 | grep inet
# Erwartet: inet 192.168.42.1/24

# 3. GUI ist gestartet?
# → Fenster "Power Debug Monitor" sollte auf dem Desktop zu sehen sein

# 4. Manueller Start zum Testen:
power-debug-monitor --simulate
```

---

## 4. Raspberry Pi Zero W Nodes einrichten

> Diese Schritte **für jeden Node einzeln** durchführen (Node 1 und Node 2).

### 4.1 Betriebssystem installieren

1. **Raspberry Pi Imager** öffnen
2. OS wählen: **Raspberry Pi OS Lite (64-bit)** — kein Desktop nötig
3. Vor dem Schreiben **SSH aktivieren** und WLAN temporär konfigurieren (für die Ersteinrichtung)
4. MicroSD beschreiben, in RPi Zero W einsetzen und starten
5. Per SSH verbinden (z.B. `ssh pi@raspberrypi.local`)

### 4.2 Setup-Skript ausführen

```bash
# Projektdateien auf den Node kopieren (von einem PC oder RPi 5 aus)
scp -r power_debug_system/ pi@raspberrypi.local:~/

# SSH-Verbindung
ssh pi@raspberrypi.local

# Setup ausführen (1 für Node 1, 2 für Node 2)
cd ~/power_debug_system
sudo bash setup_node.sh 1    # für Node 1
# ODER
sudo bash setup_node.sh 2    # für Node 2

# Neustart
sudo reboot
```

Nach dem Neustart verbindet sich der RPi Zero W automatisch mit `PowerDebugAP` und startet die Dienste.

**Node nach dem Neustart verifizieren:**
```bash
# Per SSH über den AP (RPi 5 muss laufen)
ssh pi@192.168.42.11   # Node 1
ssh pi@192.168.42.12   # Node 2

# Dienststatus prüfen
systemctl status spi-receiver
systemctl status flash-daemon

# Live-Logs
journalctl -u spi-receiver -f
```

### 4.3 LED-Statusanzeige verstehen

Die LEDs geben jederzeit Auskunft über den Node-Zustand — ohne SSH oder Monitor:

| LED | Muster | Bedeutung |
|---|---|---|
| 🟢 **Grün** | Alle 3× kurz aufblinken | Boot-Sequenz abgeschlossen, Dienste bereit |
| 🟢 **Grün** | Blinkt 1× pro Sekunde | System läuft normal |
| 🟢 **Grün** | Dauerhaft AN | System startet noch (Boot läuft) |
| 🟢 **Grün** | Aus | Dienst abgestürzt oder System aus |
| 🔵 **Blau** | Dauerhaft AN | WLAN-Verbindung zum RPi 5 aktiv |
| 🔵 **Blau** | 4× schnell blinken | WLAN-Verbindungsaufbau läuft |
| 🔵 **Blau** | Aus | Kein WLAN (RPi 5 nicht erreichbar) |
| 🟡 **Gelb** | Blinkt ~2× pro Sek. | Teensy sendet Daten (SPI→UDP aktiv) |
| 🟡 **Gelb** | Aus | Kein Signal vom Teensy (Kabel prüfen) |
| 🔴 **Rot** | Dauerhaft AN | Flash-Datei wird empfangen / Teensy wird geflasht |
| 🔴 **Rot** | 3× langsam blinken | Flash erfolgreich ✅ |
| 🔴 **Rot** | 10× schnell blinken | Flash-Fehler ❌ |
| 🔴 **Rot** | Aus | Kein Flash-Vorgang (Normalzustand) |

---

## 5. Entwicklungs-PC vorbereiten

Der PC verbindet sich per USB-C mit dem RPi 5 und kann Firmware-Dateien hochladen.

### Windows

1. **RNDIS-Treiber installieren:** Gerätemanager → Unbekanntes Gerät → Treiber aktualisieren → "USB RNDIS Adapter" oder Datei `rndis.inf` verwenden
2. **Netzwerkkarte konfigurieren:** IPv4 Adresse automatisch (DHCP) — PC bekommt IP im Bereich 192.168.7.x
3. **RPi 5 ist erreichbar unter:** `192.168.7.1`

### macOS / Linux

- Automatisch erkannt über `cdc_ether` / `RNDIS`
- Linux: RPi 5 erscheint als `usb0`
- macOS: RPi 5 erscheint als `en5` (o.ä.)

### Python Upload-Skript (optional)

Für das direkte Senden einer `.hex`-Datei an die Nodes:

```python
# upload_firmware.py — auf dem PC ausführen
import socket, struct, sys

def upload(hex_path, rpi5_ip="192.168.7.1", node1=True, node2=False):
    """Sendet .hex-Datei direkt an Flash-Daemons der Nodes."""
    ports = []
    if node1: ports.append(6001)
    if node2: ports.append(6002)

    with open(hex_path, "rb") as f:
        data = f.read()

    for port in ports:
        print(f"Sende {len(data):,} Bytes an Port {port}...")
        with socket.create_connection((rpi5_ip, port), timeout=90) as s:
            s.sendall(struct.pack(">I", len(data)))
            s.sendall(data)
            resp = s.recv(256).decode()
            print(f"  Antwort Port {port}: {resp}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Aufruf: python upload_firmware.py <datei.hex> [--both]")
        sys.exit(1)
    both = "--both" in sys.argv
    upload(sys.argv[1], node1=True, node2=both)
```

---

## 6. Erster Start & Systemtest

### Empfohlene Boot-Reihenfolge

```
1. RPi 5 starten  (WLAN-AP muss zuerst aktiv sein)
          ↓
2. Node 1 (RPi Zero W) starten
3. Node 2 (RPi Zero W) starten
          ↓
4. Teensy 4.0 (per Roboter-Stromversorgung) aktivieren
          ↓
5. GUI auf RPi 5 → Daten sollten nach ~5 Sek. eintreffen
```

### Systemtest ohne Hardware (Simulator-Modus)

```bash
# Auf dem RPi 5 — keine Nodes oder Teensys nötig
power-debug-monitor --simulate
```

Der Simulator erzeugt synthetische Sinuswellen-Daten für beide Nodes und sendet sie an `localhost`. Damit kann die komplette GUI-Funktionalität getestet werden.

### Konnektivitätstest

```bash
# RPi 5: Sind die Nodes verbunden?
ping 192.168.42.11   # Node 1
ping 192.168.42.12   # Node 2

# Kommt UDP-Daten an? (auf RPi 5)
sudo tcpdump -i wlan0 udp port 5001 -c 10 -q
sudo tcpdump -i wlan0 udp port 5002 -c 10 -q

# Flash-Daemon erreichbar? (TCP-Verbindungstest)
nc -zv 192.168.42.11 6001 && echo "Node 1 Flash-Port OK"
nc -zv 192.168.42.12 6002 && echo "Node 2 Flash-Port OK"
```

---

## 7. GUI-Bedienung

Nach dem Start zeigt die GUI das Hauptfenster mit einer Steuerungsleiste oben und vier Tabs.

### 7.1 Steuerungsleiste

```
┌────────────────────────────────────────────────────────────────────────┐
│  Aktiver Debug-Knoten                 Flash-Management                  │
│  ○ Node 1 (192.168.42.11)    ⬤ Node 1  ⬤ Node 2                       │
│  ● Node 2 (192.168.42.12)    Ziel: ☑ Node 1  ☐ Node 2                  │
│                              [⚡ Firmware flashen…]                     │
└────────────────────────────────────────────────────────────────────────┘
```

#### Node-Selektor (links)
- **Node 1 / Node 2:** Wählt, welcher Datenstrom in der Tabelle und im Plotter angezeigt wird
- Der Wechsel **löscht Min/Max-Statistiken** und den Plot-Buffer (Neustart der Anzeige)
- Der inaktive Node bleibt empfangsbereit — keine Datenpakete gehen verloren

#### Status-LEDs (Flash-Management, Mitte)
- **⬤ Grün:** Node verbunden und sendet Daten
- **⬤ Rot:** Node nicht erreichbar / keine Daten

#### Flash-Ziel (rechts)
- Checkboxen wählen, welche Nodes die Firmware erhalten sollen
- **Node 1 und Node 2 gleichzeitig:** Paralleles Flashen in separaten Threads

### 7.2 Tab 1 — Live-Tabelle

Zeigt alle aktiven Kanäle mit aktuellen und statistischen Werten.

| Spalte | Beschreibung |
|---|---|
| **Variable** | Kanalname (aus `config.py → VARIABLE_NAMES`) |
| **Aktuell** | Letzter empfangener Wert (grün = positiv, rot = negativ) |
| **Min** | Kleinstwert seit Start oder letztem Reset |
| **Max** | Größtwert seit Start oder letztem Reset |
| **Δ (Range)** | Max − Min (Wertebereich) |

**Button „↺ Min/Max zurücksetzen":** Setzt Statistiken zurück (z.B. nach dem Aufwärmen des Roboters).

> **Tipp:** Variablennamen können in `/opt/power_debug_monitor/config.py` unter `VARIABLE_NAMES` angepasst werden, z.B. `VARIABLE_NAMES[0] = "Motor_L_Speed"`.

### 7.3 Tab 2 — Live-Plotter

Visualisiert einen ausgewählten Kanal in Echtzeit.

| Bedienelement | Funktion |
|---|---|
| **Variable (Dropdown)** | Wählt den anzuzeigenden Kanal |
| **Punkte (SpinBox)** | Anzahl sichtbarer Datenpunkte (50–500) |
| **⏸ Einfrieren** | Stoppt den Live-Scroll; Maus-Pan/Zoom möglich |
| **▶ Weiter** | Setzt Live-Anzeige fort (Buffer läuft weiter) |
| **🗑 Löschen** | Leert den Plot-Buffer |

**Statuszeile:** `Min: ... | Max: ... | Aktuell: ... | σ: ...` (Standardabweichung)

#### Freeze-Modus

Im eingefrierenen Zustand:
- Die **gelbe gestrichelte Kurve** zeigt den Snapshot zum Zeitpunkt des Einfrierens
- Die **Live-Queue** läuft weiter — keine Datenverluste
- Maus-Scroll zum Zoomen, Maus-Drag zum Verschieben (Pan)
- Drücke **▶ Weiter** um zur Live-Ansicht zurückzukehren

### 7.4 Firmware flashen

1. **Ziel wählen:** Checkboxen `☑ Node 1` und/oder `☑ Node 2` in der Steuerungsleiste
2. **Button drücken:** `⚡ Firmware flashen…`
3. **Datei auswählen:** Datei-Dialog öffnet sich → `.hex`-Datei wählen
4. **Warten:** Statusleiste zeigt Fortschritt (`Flashe Node 1 + Node 2…`)
5. **Ergebnis:** `✅ Node 1 Flash: OK` oder `❌ Node 2 Flash: ERR:<Fehlermeldung>`

**Typische Flash-Dauer:** 10–30 Sekunden pro Node (abhängig von Firmware-Größe)

> **Hinweis:** Während des Flashens läuft der Telemetrie-Empfang weiter. Die GUI bleibt vollständig bedienbar.

---

## 8. Simulator-Modus (kein Teensy nötig)

```bash
power-debug-monitor --simulate
```

Der Simulator generiert für beide Nodes synthetische Daten:
- **500 aktive Kanäle** mit Sinuswellen unterschiedlicher Frequenz
- **500 Dummy-Kanäle** (9898,0 — werden herausgefiltert)
- **100 Hz Paketrate** (10 ms Intervall)
- **Node-Offset:** Node 2 hat +1,0 V Offset zum Unterscheiden

---

## 9. Netzwerk-Referenz

### IP-Adressen & Ports

| Gerät | IP-Adresse | Rolle |
|---|---|---|
| Raspberry Pi 5 (WLAN) | `192.168.42.1` | WLAN Access Point |
| Raspberry Pi 5 (USB) | `192.168.7.1` | USB-Gadget (PC-Verbindung) |
| RPi Zero W Node 1 | `192.168.42.11` | Telemetrie-Node 1 |
| RPi Zero W Node 2 | `192.168.42.12` | Telemetrie-Node 2 |
| Entwicklungs-PC | `192.168.7.x` | Firmware-Upload (DHCP) |

| Port | Protokoll | Richtung | Zweck |
|:---:|---|---|---|
| `5001` | UDP | Node 1 → RPi 5 | Telemetrie-Datenstrom Node 1 |
| `5002` | UDP | Node 2 → RPi 5 | Telemetrie-Datenstrom Node 2 |
| `6001` | TCP | RPi 5 → Node 1 | Firmware-Upload & Flash-Trigger |
| `6002` | TCP | RPi 5 → Node 2 | Firmware-Upload & Flash-Trigger |
| `7001` | TCP | — | Parameter-Konfiguration (Phase 2) |

### WLAN-Zugangsdaten

| Parameter | Wert |
|---|---|
| SSID | `PowerDebugAP` |
| Passwort | `HighSpeedDebug123` |
| Kanal | 6 (2,4 GHz) |
| Verschlüsselung | WPA2-PSK |

---

## 10. Troubleshooting

### GUI startet nicht nach Reboot

```bash
# Manuell starten und Fehler sehen
power-debug-monitor

# Oder aus dem Installationsverzeichnis
cd /opt/power_debug_monitor && python3 main.py

# Qt-Plattform-Problem?
export QT_QPA_PLATFORM=xcb
python3 /opt/power_debug_monitor/main.py

# pyqtgraph nicht installiert?
pip3 install --break-system-packages pyqtgraph
```

### Node verbindet sich nicht mit AP

```bash
# Auf dem Node (via USB-Seriell oder direktem HDMI):
ip addr show wlan0              # Keine IP → WLAN fehlgeschlagen

# WLAN-Log
journalctl -u wpa_supplicant -n 30
# oder
nmcli connection show PowerDebugAP

# Manuell verbinden
nmcli connection up PowerDebugAP

# AP auf RPi 5 aktiv?
# Auf dem RPi 5:
nmcli connection show PowerDebugAP | grep STATE
```

### Keine Daten in der GUI (Tabelle leer)

```bash
# 1. Teensy läuft und sendet DATA_READY-Signal?
#    → LED am Teensy sollte blinken

# 2. SPI-Receiver läuft auf dem Node?
ssh pi@192.168.42.11
journalctl -u spi-receiver -f
# Erwartet: "Throughput: X Pkt/s | Y KB/s"

# 3. UDP-Pakete kommen am RPi 5 an?
sudo tcpdump -i wlan0 udp port 5001 -c 5 -q

# 4. SPI-Verbindung korrekt? GPIO17 (DATA_READY) verbunden?
#    Gelbe LED am Node sollte blinken wenn Teensy läuft
```

### Flash schlägt fehl

```bash
# Auf dem Node: Flash-Daemon-Log
journalctl -u flash-daemon -f

# teensy_loader_cli verfügbar?
ssh pi@192.168.42.11 "which teensy_loader_cli"

# USB-Verbindung Teensy ↔ RPi Zero?
ssh pi@192.168.42.11 "lsusb | grep -i teensy"

# Manueller Flash-Test auf dem Node
ssh pi@192.168.42.11
teensy_loader_cli --mcu=TEENSY40 -w -v /tmp/node1_fw.hex
```

### USB-Gadget nicht erkannt (PC sieht RPi 5 nicht)

```bash
# Auf dem RPi 5: Ist g_ether geladen?
lsmod | grep g_ether
# Falls leer:
sudo modprobe g_ether

# cmdline.txt korrekt?
cat /boot/firmware/cmdline.txt
# Muss enthalten: modules-load=dwc2,g_ether

# config.txt korrekt?
grep dwc2 /boot/firmware/config.txt
# Muss enthalten: dtoverlay=dwc2,dr_mode=peripheral
```

---

## 11. Logs & Diagnose

### Alle relevanten Log-Quellen

| Was | Befehl |
|---|---|
| SPI-Receiver (Node 1) | `ssh pi@192.168.42.11 "journalctl -u spi-receiver -f"` |
| SPI-Receiver (Node 2) | `ssh pi@192.168.42.12 "journalctl -u spi-receiver -f"` |
| Flash-Daemon (Node 1) | `ssh pi@192.168.42.11 "journalctl -u flash-daemon -f"` |
| Flash-Daemon (Node 2) | `ssh pi@192.168.42.12 "journalctl -u flash-daemon -f"` |
| GUI auf RPi 5 | `journalctl --user -u power-debug-monitor -f` |
| WLAN-AP Status | `nmcli connection show PowerDebugAP` |
| Netzwerk-Traffic | `sudo tcpdump -i wlan0 -q` |

### Schnelldiagnose auf dem RPi 5

```bash
# Kompletter Systemstatus
echo "=== AP ===" && nmcli connection show PowerDebugAP | grep -E "STATE|addr"
echo "=== Nodes ===" && for ip in 192.168.42.11 192.168.42.12; do
    ping -c 1 -W 1 $ip &>/dev/null && echo "$ip: ONLINE" || echo "$ip: OFFLINE"
done
echo "=== UDP-Traffic ===" && sudo timeout 3 tcpdump -i wlan0 udp -q 2>/dev/null | wc -l
```
