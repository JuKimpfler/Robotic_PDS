# Architektur und Wire-Format

Wie die drei Teile — Teensy, Node, Oberfläche — miteinander reden. Für das
Einrichten siehe [`Setup_und_Update.md`](Setup_und_Update.md), für den
Funktionsumfang [`../FEATURES.md`](../FEATURES.md).

```
┌────────────────────────────┐   UDP (Downlink, an den aktiven Node)   ┌──────────────────────────┐
│ Haupt-Pi / PC (GUI)        │ ──────────────────────────────────────▶ │ Pi Zero 2 W (Node)       │
│  main_qml.py               │   Slow   2 Hz   7001/7002               │  uart_receiver.py        │
│  Empfänger je Port in      │   Fast 100 Hz   7011/7012               │  status_leds.py          │
│  eigenen Prozessen         │   Namen anfordern 7021/7022             │  bt_flash_receiver.py    │
│                            │   Discovery 1 Hz 7031/7032 (an beide)   └────────────┬─────────────┘
└────────────────────────────┘                                                     │ UART 1 Mbit/s
              ▲  UDP (Uplink)                                                       ▼
              │  Telemetrie 5001/5002 · Deskriptor 5011/5012 · Aux 5021/5022  ┌──────────────────────────┐
              └────────────────────────────────────────────────────────────── │ Teensy 4.0 (PDS-Lib)     │
                                                                              └──────────────────────────┘
```

Ports: Node 1 / Node 2. Alle Magic-Zahlen, Paketgrößen und Ports stehen
dreimal — `teensy_firmware/src/params.h`, `rpi_zero_node/uart_receiver.py`,
`rpi5_monitor/64Bit_Version/config.py` — und werden von
`tools/check_wire_format.py` gegeneinander geprüft.

---

## 1. Telemetrie (Teensy → Node → GUI)

* Der Teensy schickt mit 100 Hz ein Paket über `UART_DBG` (Standard
  `Serial3`, 1 Mbit/s): `0xDEADBEEF`, `micros()`, 200 × `float32` =
  **808 Byte**. Das sind 80,8 kB/s von 100 kB/s, die die Leitung hergibt.
* Höchstens ein Paket je `PDS.update()`. Ist der TX-Puffer voll, wird das
  Paket verworfen und gezählt (`txDropCount()`), statt die Regelschleife
  warten zu lassen.
* Der Node setzt die Pakete aus dem UART-Strom zusammen und schickt jedes per
  UDP weiter. Fehlen Bytes (UART-Überlauf), wird das Paket verworfen statt
  mit dem Anfang des nächsten aufgefüllt.
* **Adressierung**: Der Node lernt die Adresse der GUI aus deren Paketen und
  sendet **Unicast**. Bis dahin — und wenn die GUI länger als 10 s schweigt —
  Broadcast. Broadcast ist bewusst nicht der Normalfall: WLAN schickt
  Broadcast mit der niedrigsten Grundrate, ohne Aggregation und ohne
  Bestätigung; bei 80 kB/s kostete das so viel Funkzeit, dass die
  Fernsteuerung träge wurde ([`Latenz_Fernsteuerung.md`](Latenz_Fernsteuerung.md)).
  Erzwingen lässt sich beides auf dem Node: `PDS_TELEMETRY_DEST=<ip>` bzw.
  `PDS_TELEMETRY_BROADCAST=1`.
* Die GUI empfängt in eigenen Prozessen, schneidet nachlaufende Füllwerte
  (`9898.0`) ab und holt die Pakete mit 25 Hz in den GUI-Thread.

## 2. Parameter und Fernsteuerung (GUI → Node → Teensy)

| Kanal | Inhalt | Takt | Magic | Größe |
|---|---|---|---|---|
| Slow | 50 Floats + 50 Bools | 2 Hz | `0xCAFEFEED` | 258 B |
| Fast | 5 Floats (Joystick/Controller) | 100 Hz | `0xFA57DA7A` | 28 B |
| Namen anfordern | — | auf Anfrage | `0xDE5C00F0` | 4 B |
| Discovery | Nummer + Sendezeit | 1 Hz, an **beide** Nodes | `0xD15C0BE5` | 12 B |

* Gesendet wird nur an den **aktiven** Node. Discovery geht an beide, damit
  auch der inaktive die Adresse der GUI kennt und nicht dauerhaft
  broadcastet; es trägt keine Parameter und wird nie an den Teensy
  weitergeleitet. Der Node spiegelt es zurück (`0xD15CEC40`) — daraus kommt
  die Round-Trip-Zeit im Diagnose-Tab.
* Der Node schiebt vom Fast- und Slow-Kanal nur den **neuesten** Stand über
  die UART; überholte Pakete werden verworfen.
* Die GUI sendet aus einem eigenen Thread mit fester 10-ms-Periode
  (Controller lesen → Tastatur → packen → senden), unabhängig vom Renderer.
* Der Teensy setzt die Pakete mit einem Schiebefenster zusammen; ein
  abgebrochenes Paket setzt den Parser nach 50 ms zurück.
  Details: [`Param_Implementierung.md`](Param_Implementierung.md).

## 3. Deskriptor: Namen, Einheiten, Konfiguration (Teensy → GUI)

Der Teensy ist die Quelle der Wahrheit für Kanalnamen, Einheiten, den
Aufbau des Parameter-Tabs, die Overlays der Systemansicht und — optional —
die Einstellungen der Oberfläche. Er baut daraus ein JSON und schickt es in
Stücken (`0xDE5C0001`, bis 250 Byte Nutzlast, ein Stück je 20 ms) über
denselben Weg wie die Telemetrie.

| Was neu gestartet hat | Wie die Namen zurückkommen |
|---|---|
| Teensy (GUI läuft) | Firmware sendet beim Start; die GUI erkennt zusätzlich den `micros()`-Sprung und fragt nach |
| GUI oder Node (Teensy läuft) | Firmware erkennt, dass die Verbindung wieder steht, und sendet |
| Teensy vor GUI/Node gestartet | Firmware wiederholt die Meldung in Ruhe mit wachsendem Abstand |

Die GUI speichert alles **je Node** unter `runtime_config/nodeN/` — nach
einem Neustart steht es sofort wieder da, auch ohne eingeschalteten Roboter.
Konflikt zwischen Teensy und lokaler Bearbeitung: ein Fingerabdruck
entscheidet — neue Firmware setzt sich durch, sonst bleibt die Handarbeit.
Details: [`Kanalnamen_Implementierung.md`](Kanalnamen_Implementierung.md),
[`Teensy_Einstellungen.md`](Teensy_Einstellungen.md).

## 4. Aux-Uplink: Ereignisse, Rückmeldung, Node-Status (→ GUI)

Drei kleine Ströme teilen sich einen Port (5021/5022); die GUI trennt sie am
Magic.

| Strom | Magic | Takt | Inhalt |
|---|---|---|---|
| Ereignis / Logzeile | `0xE7E5C0DE` | ≤ 20/s | `PDS.event()` → Marke im Plotter, `PDS.log/warn/error()` → Logbuch |
| Parameter-Rückmeldung | `0xACC0FEED` | 2 Hz | was der Teensy wirklich hält (Soll/Ist im Parameter-Tab) |
| Node-Status | `0x0DE57A75` | 1 Hz | Temperatur, Last, Speicher, WLAN, Uptime, UART-Zähler des Nodes |

Alles vom Teensy ist rate-begrenzt und wird nur geschrieben, wenn im
TX-Puffer zusätzlich ein komplettes Telemetriepaket Platz hat — es kann die
Telemetrie also nie verdrängen.

## 5. Firmware per Bluetooth (PC → Node → Teensy)

```
Windows-PC ──Bluetooth (RFCOMM/SPP)──▶ Pi Zero 2 W ──USB──▶ Teensy 4.0
 bt_flash_sender.py                    bt_flash_receiver.py   (teensy_loader_cli)
```

Unabhängig vom WLAN. Der Node prüft Auth-Token und SHA-256, versetzt den
Teensy erst nach vollständiger Übertragung per Software in den Bootloader und
flasht. Details: [`Flash_Implementierung.md`](Flash_Implementierung.md),
[`../pc_flash_tool/README.md`](../pc_flash_tool/README.md).

## 6. Versionen und gemeinsam zu ändernde Konstanten

* `PDS_WIRE_VERSION` (`params.h`, gespiegelt in Node und GUI) steigt bei
  jeder inkompatiblen Formatänderung — dann müssen Teensy, Node und GUI
  zusammen aktualisiert werden. Siehe [`../CHANGELOG.md`](../CHANGELOG.md).
* `MAX_FLOATS = 200` (Paketgröße) steht in `PDS.cpp`, `uart_receiver.py`
  und `config.py` und muss überall gleich sein — sonst verwirft der Node
  jedes Paket wortlos.
* Baudrate: `UART_DBG_BAUD` in `params.h` = `UART_BAUD` in
  `uart_receiver.py`.
* `ACTIVE_CHANNELS` (Build-Flag) bestimmt nur, wie viele Kanäle Namen tragen
  können, nicht die Paketgröße.

`python tools/check_wire_format.py` prüft alles davon und rechnet die
UART-Auslastung aus.
