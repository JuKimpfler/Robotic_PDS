# Netzwerk-Einrichtung — Power Debug System

## Übersicht der Adressen

| Gerät              | IP             | Rolle                   |
|--------------------|----------------|-------------------------|
| Raspberry Pi 5     | 192.168.42.1   | WLAN-Hotspot + Monitor  |
| RPi Zero W Node 1  | 192.168.42.11  | SPI→UDP Forwarder       |
| RPi Zero W Node 2  | 192.168.42.12  | SPI→UDP Forwarder       |
| Entwicklungs-PC    | 192.168.7.2    | Firmware-Upload via USB |

---

## 1. RPi 5 als WLAN-Access-Point

```bash
# Hotspot mit NetworkManager erstellen
sudo nmcli device wifi hotspot \
    ifname wlan0 \
    ssid  PowerDebugAP \
    password HighSpeedDebug123

# Feste IP für den AP setzen
sudo nmcli connection modify Hotspot \
    ipv4.addresses 192.168.42.1/24 \
    ipv4.method    manual

# Aktivieren und beim Booten starten
sudo nmcli connection up Hotspot
sudo nmcli connection modify Hotspot connection.autoconnect yes
```

Prüfen ob der Hotspot läuft:
```bash
nmcli connection show Hotspot
ip addr show wlan0
```

---

## 2. RPi 5 als USB-C-Gadget (RNDIS / CDC-Ethernet)

Der PC sieht den RPi 5 als USB-Netzwerkkarte. Firmware-Uploads
laufen über diese Verbindung.

### A. Kernel-Module aktivieren

Trage in `/boot/firmware/config.txt` ein:
```
dtoverlay=dwc2,dr_mode=peripheral
```

Füge in `/boot/firmware/cmdline.txt` **hinter** `rootwait` ein
(alles in einer Zeile!):
```
modules-load=dwc2,g_ether
```

### B. Feste IP für die USB-Gadget-Schnittstelle

```bash
sudo nmcli connection add \
    type ethernet \
    con-name  usb-gadget \
    ifname    usb0 \
    ipv4.addresses  192.168.7.1/24 \
    ipv4.method     manual \
    connection.autoconnect yes
```

### C. PC-Seite

Windows: RNDIS-Treiber installieren (Gerätemanager → USB-RNDIS).
Linux  : Automatisch über usb_network / cdc_ether.
macOS  : Automatisch über RNDIS.

PC erhält automatisch eine IP im Bereich 192.168.7.x.
Der RPi 5 ist dann unter **192.168.7.1** erreichbar.

---

## 3. Firmware-Upload vom PC

Ein einfaches Python-Upload-Skript (auf dem PC ausführen):

```python
# upload_firmware.py  (PC-Seite)
import socket, struct, sys

def upload(hex_path: str, rpi5_ip: str = "192.168.7.1",
           node1: bool = True, node2: bool = False):
    """Sendet die .hex-Datei an den RPi 5 Flash-Verteiler."""
    # Port 6001 → Node 1, Port 6002 → Node 2
    targets = []
    if node1: targets.append(6001)
    if node2: targets.append(6002)

    with open(hex_path, "rb") as f:
        data = f.read()

    for port in targets:
        with socket.create_connection((rpi5_ip, port), timeout=90) as s:
            s.sendall(struct.pack(">I", len(data)))
            s.sendall(data)
            resp = s.recv(256).decode()
            print(f"Port {port}: {resp}")

if __name__ == "__main__":
    upload(sys.argv[1])
```

---

## 4. Nodes vorbereiten

Auf jedem RPi Zero W (einmalig):
```bash
# Skripte auf den Node kopieren
scp rpi_zero_node/*.py pi@192.168.42.11:~/power_debug/

# Setup-Skript ausführen (Node 1)
ssh pi@192.168.42.11 "sudo bash ~/power_debug/setup_node.sh 1"

# Neustart
ssh pi@192.168.42.11 "sudo reboot"
```

Nach dem Neustart prüfen:
```bash
ssh pi@192.168.42.11 "systemctl status spi-receiver flash-daemon"
```

---

## 5. Pinbelegung SPI1 (Teensy ↔ RPi Zero W)

| Signal       | Teensy Pin (SPI1) | RPi Zero GPIO (BCM) | RPi Zero Pin |
|--------------|:-----------------:|:-------------------:|:------------:|
| SCK          | 27                | 11 (SPI_CLK)        | 23           |
| MOSI         | 26                | 10 (SPI_MOSI)       | 19           |
| MISO         | 1                 | 9  (SPI_MISO)       | 21           |
| CS           | 30                | 8  (SPI_CE0)        | 24           |
| DATA_READY   | 9                 | 17 (GPIO17)         | 11           |
| GND          | GND               | GND                 | 6            |

> **Wichtig:** Teensy 4.0 arbeitet mit 3,3 V — Pegel kompatibel mit RPi Zero W. ✓  
> **SPI1 / LPSPI3:** Der Teensy verwendet den zweiten SPI-Bus (SPI1). Pin 30 dient als
> alternativer Chip-Select anstelle des Standard-CS (Pin 0).

---

## 6. Schnelltest

```bash
# Auf dem RPi 5 — Simulator starten (kein Teensy nötig)
python rpi5_monitor/main.py --simulate

# Netzwerk-Empfang prüfen (auf RPi 5)
sudo tcpdump -i wlan0 udp port 5001 -c 20

# Flash-Daemon prüfen (auf RPi Zero)
journalctl -u flash-daemon -f
```
