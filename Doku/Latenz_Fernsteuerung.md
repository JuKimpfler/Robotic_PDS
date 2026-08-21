# Latenz der Fernsteuerung (Fast-Kanal / PS4-Controller)

Dieses Dokument beschreibt, **woraus sich die Reaktionszeit zwischen einer
Stickbewegung am PS4-Controller und der Reaktion des Roboters zusammensetzt**,
welche Fehler in dieser Kette gefunden und behoben wurden, und wie man das
Ganze nachmisst, falls es wieder träge wird.

Betroffener Pfad (der „Fast-Kanal“, 5 Floats, 100 Hz):

```
PS4-Controller ─USB─▶ RPi 5 / PC (GUI) ─WLAN/UDP :7011─▶ RPi Zero 2 W ─UART─▶ Teensy 4.0
                      controller_bridge     param_bridge      uart_receiver        PDS.cpp
```

---

## 1. Was die Verzögerung verursacht hat

Es war **nicht ein** Fehler, sondern fünf, die sich addiert und gegenseitig
verstärkt haben. Nach Wirkung sortiert:

### 1.1 Der Teensy hat jedes zweite Paket weggeworfen  (schwerwiegend)

`PowerDebugger::pollParamUart()` sucht mit einem 4-Byte-Schiebefenster nach
dem Magic-Header eines Pakets. Der Vergleich stand hinter dieser Zeile:

```cpp
buf[0] = buf[1]; buf[1] = buf[2]; buf[2] = buf[3]; buf[3] = b;
if (fill < 4) { fill++; continue; }     // <- übersprang den Vergleich
```

Nach jedem fertig geparsten Paket wird `fill` auf 0 gesetzt. Die vier
folgenden Bytes sind der Magic des nächsten Pakets — beim vierten steht er
vollständig im Fenster, aber `fill` ist da noch 3, also griff `continue` und
der Vergleich fand nie statt. Ab dem fünften Byte war der Magic bereits aus
dem Fenster herausgeschoben. **Ergebnis: der Magic des unmittelbar folgenden
Pakets wurde systematisch übersehen, das Paket komplett verworfen, und erst
das übernächste wieder erkannt.**

Effektive Rate am Teensy:

| Kanal | gesendet | angekommen (vorher) | angekommen (jetzt) |
|---|---|---|---|
| Fast (Joystick/Controller) | 100 Hz | **50 Hz** | 100 Hz |
| Slow (Parameter) | 2 Hz | **1 Hz** | 2 Hz |

Nachgewiesen mit einem Nachbau beider Parser-Varianten: bei 100 gesendeten
Fast-Paketen kamen mit der alten Fassung exakt 50 an, mit der neuen 100 —
ebenso nach Byte-Müll auf der Leitung und nach einem Deskriptor-Request.

### 1.2 Der UART-Empfangspuffer des Teensy war 64 Byte groß  (schwerwiegend)

`init()` hat nur `addMemoryForWrite()` aufgerufen, nie `addMemoryForRead()`.
Der Teensy-Core legt dann den Default-Puffer von **64 Byte** an.

Ein Slow-Paket ist 258 Byte lang und trifft bei 1 Mbps als 2.6-ms-Salve ein.
Damit dabei nichts verloren geht, hätte `update()` alle ~0,6 ms laufen
müssen. Real läuft ein Roboter-Hauptprogramm mit ein paar Millisekunden
Zykluszeit — **jedes Slow-Paket (also 2× pro Sekunde) hat den Puffer
überlaufen lassen.**

Der Folgeschaden ist gravierender als der Verlust selbst: fehlen mitten im
Paket Bytes, wartet der Parser weiter auf die angekündigte Gesamtlänge und
verarbeitet die *nachfolgenden Fast-Pakete als Nutzlast des kaputten
Slow-Pakets*. Bei 258 erwarteten Bytes verschluckt er so rund sieben
Fast-Pakete am Stück — **zweimal pro Sekunde ein Aussetzer von ~70 ms.**

Behoben durch einen 2 KB großen RX-Puffer (`addMemoryForRead`), der ~600 ms
Downlink puffert und den Empfang damit von der Zykluszeit des
Hauptprogramms entkoppelt.

### 1.3 Die Telemetrie wurde per WLAN-Broadcast verschickt  (schwerwiegend)

Der Node hat jedes Telemetriepaket (808 B, 100 Hz = **80,8 kB/s**) an
`255.255.255.255` geschickt.

WLAN behandelt Broadcast/Multicast grundlegend anders als Unicast:

| | Broadcast | Unicast |
|---|---|---|
| Sendrate | niedrigste Basisrate des BSS (1–6 Mbit/s) | ausgehandelte MCS-Rate (bis zu 100×) |
| Frame-Aggregation | nein | ja |
| MAC-Level-ACK/Retry | nein | ja |

Bei 6 Mbit/s Basisrate belegt ein Node damit grob 10–15 % der Funkzeit, bei
1 Mbit/s ein Vielfaches. Mit **zwei** Nodes ist der Kanal praktisch dicht.
Die 28-Byte-Fast-Pakete in der Gegenrichtung stehen dann in der
Sendewarteschlange an und kommen verzögert und stoßweise an — das typische
„Steuerung reagiert träge und ruckelig“.

Der Node lernt jetzt die Adresse der GUI aus den eingehenden Param-Paketen
und sendet danach per Unicast. Solange nichts gelernt wurde (und wenn länger
als 10 s nichts mehr von der GUI kam), bleibt es beim Broadcast — das
Verhalten ist also **nie schlechter als vorher**, siehe `TelemetryTarget`
in `rpi_zero_node/uart_receiver.py`.

### 1.4 Zwei ungekoppelte 10-ms-Timer in der GUI  (mittel)

`ControllerBridge` hatte einen eigenen `QTimer` mit 10 ms, `ParamBridge`
einen zweiten mit 10 ms für den Versand. Zwei gleich schnelle, aber nicht
gekoppelte Timer haben eine zufällige, über die Laufzeit driftende
Phasenlage. Im ungünstigen Fall schreibt der Controller-Timer den neuen
Stand unmittelbar *nachdem* der Sende-Timer das Paket gepackt hat — der Wert
wartet dann volle 10 ms auf den nächsten Slot.

**Kosten: im Mittel 5 ms, im Maximum 10 ms — und zwar schwankend.** Jitter
wird subjektiv deutlich schlimmer wahrgenommen als eine gleichbleibende
Verzögerung.

Jetzt ruft `ParamBridge._send_fast_tick()` direkt vor dem Packen
`controller.poll()` auf. Der gesendete Stand ist damit garantiert der zuletzt
gelesene, und es läuft nur noch ein 100-Hz-Timer im GUI-Thread statt zwei.
Der Timer ist zusätzlich als `Qt.TimerType.PreciseTimer` markiert, damit Qt
ihn nicht mit anderen zusammenlegt.

### 1.5 Kleinere Beiträge  (jeweils gering, in Summe spürbar)

| Ursache | Wirkung | Behebung |
|---|---|---|
| `valuesChanged` wurde 100×/s an QML gemeldet | jede Meldung wertet alle daran hängenden Bindings neu aus, im selben Thread, der den 10-ms-Timer bedienen muss | auf 25 Hz gedrosselt (`CONTROLLER_UI_NOTIFY_MS`), Store weiterhin mit 100 Hz |
| SDL-Event-Queue wurde nie geleert | `pygame.event.pump()` füllte sie mit ~1000 Events/s, die niemand abholt | `pygame.event.clear()` nach jedem Pump |
| blockierender UDP-Socket in der GUI | `sendto()` blockiert bei voller Treiber-Queue (ENOBUFS) und friert damit die komplette Oberfläche ein | `setblocking(False)`, verworfene Pakete werden gezählt statt zu blockieren |
| Node hat gestapelte Fast-Pakete alle weitergereicht | der Teensy arbeitete veraltete Joystick-Stände ab, bevor er beim aktuellen ankam | nur noch das jeweils neueste Paket geht auf die UART |
| Node forkte alle 15 s `ip addr show wlan0` | Prozess-Fork auf dem RPi Zero 2 W = Aussetzer mitten im 100-Hz-Betrieb | `ioctl(SIOCGIFADDR)` statt `subprocess` |
| `sampleBoundChannels()` lief in jeder `update()`-Iteration | 200 Kanäle × Schleifenfrequenz statt × 100 Hz | nur noch direkt vor `buildPacket()` |

---

## 2. Latenzbudget nach den Korrekturen

| Abschnitt | typisch | maximal |
|---|---|---|
| USB-HID-Report des Controllers | 4 ms | 8 ms |
| GUI: Poll → Paket gepackt | 0 ms | 0 ms *(gleicher Timer-Tick)* |
| GUI: Sendetakt (Warten auf den nächsten Slot) | 5 ms | 10 ms |
| WLAN (Unicast, freier Kanal) | 2–5 ms | ~20 ms |
| Node: select → UART-Write | < 1 ms | 1 ms |
| UART 28 B @ 1 Mbps | 0,3 ms | 0,3 ms |
| Teensy: `pollParamUart()` im nächsten Zyklus | halbe Zykluszeit | eine Zykluszeit |
| **Summe (bei 5 ms Roboter-Zykluszeit)** | **~15 ms** | **~40 ms** |

Zum Vergleich der Zustand vorher: allein 1.1 verdoppelte die effektive
Paketperiode auf 20 ms, 1.4 legte im Mittel 5 ms drauf, 1.2 erzeugte 2×/s
Aussetzer von ~70 ms und 1.3 unter Last WLAN-Verzögerungen im
Hundert-Millisekunden-Bereich.

---

## 3. Nachmessen, wenn es wieder klemmt

### 3.1 Auf dem Teensy

`PowerDebugger` stellt seit dieser Änderung Diagnose-Zähler bereit. Einfach
auf freie Debug-Kanäle legen, dann sind sie in der Live-Tabelle sichtbar:

```cpp
pds.Channel(190, pds.fastPacketCount(),  "Fast Pakete");
pds.Channel(191, pds.fastParamAgeMs(),   "Fast Alter ms");   // Latenzanzeige
pds.Channel(192, pds.slowPacketCount(),  "Slow Pakete");
pds.Channel(193, pds.paramSyncLosses(),  "Sync Verluste");
```

Sollwerte im Normalbetrieb:

* `Fast Pakete` steigt um **100 pro Sekunde**. Steigt er um 50, ist der
  Parser-Bug aus 1.1 wieder da (oder es kommt nur jedes zweite Paket an).
* `Fast Alter ms` bleibt **zwischen 0 und 10**. Springt der Wert regelmäßig
  auf 70–100, ist der RX-Puffer wieder zu klein (1.2) oder die
  Hauptschleife blockiert irgendwo.
* `Sync Verluste` steigt **nicht** (bzw. nur einmalig beim Start). Ein
  stetiges Wachstum heißt: Bytes gehen auf der UART verloren — Verkabelung,
  Baudrate oder Puffergröße prüfen.

### 3.2 Auf dem RPi Zero

```bash
journalctl -u uart-receiver -f
```

Die Statuszeile kommt alle 4 s:

```
Telemetrie -> 192.168.42.1: 100.0 Pkt/s | 78.9 KB/s | Sync-Verluste: 0 | Sendefehler: 0 ||
Param-Downlink: Slow=8 Fast=400 (100.0 Pkt/s) überholt=0 ungültig=0 || ...
```

* **`Telemetrie -> 192.168.42.1`** — steht hier `255.255.255.255`, läuft der
  Uplink noch als Broadcast (1.3). Der Node hat dann noch kein Param-Paket
  von der GUI gesehen: Ist „Übertragung aktiv“ in der GUI eingeschaltet?
  Stimmt die Node-IP im Parameter-Tab?
* **`Fast=... (100.0 Pkt/s)`** — kommt hier deutlich weniger an, liegt das
  Problem vor dem Node (GUI oder WLAN), nicht dahinter.
* **`überholt=`** — Anzahl der Fast-Pakete, die verworfen wurden, weil beim
  Auslesen bereits ein neueres im Puffer lag. Einstellige Werte sind normal;
  dauerhaft hohe Werte bedeuten, dass das WLAN die Pakete gebündelt
  ausliefert (Kanal überlastet oder schlechter Empfang).
* **`Sync-Verluste`** — sollte 0 sein. Steigt der Wert, verliert die
  UART-Strecke *vom Teensy* Bytes.

### 3.3 In der GUI

Die Statuszeile im Parameter-Tab zeigt jetzt zusätzlich `Verworfen: N`
(nicht absetzbare UDP-Pakete) und `🎮 Controller`, wenn ein Controller aktiv
ist. Ein wachsendes `Verworfen` bedeutet einen überlasteten oder gestörten
Funkkanal.

Rohwerte des Controllers prüfen (Achsen-/Button-Zuordnung, siehe
[PS4_Controller_Implementierung.md](PS4_Controller_Implementierung.md)):

```bash
PDS_LOGLEVEL=DEBUG python3 main_qml.py
```

---

## 4. Wenn es trotzdem träge bleibt

In dieser Reihenfolge prüfen — von „kostet nichts“ zu „kostet Aufwand“:

1. **Funkkanal.** 2,4 GHz ist auf Wettbewerben regelmäßig komplett belegt.
   Falls die Hardware es hergibt, den AP auf 5 GHz stellen; sonst mit
   `iwlist wlan0 scan` einen freien Kanal suchen und in `hostapd.conf`
   eintragen.
2. **Steht in der Node-Statuszeile `-> 255.255.255.255`?** Dann greift 1.3
   noch. Notfalls im systemd-Unit `PDS_TELEMETRY_DEST=<IP der GUI>` setzen.
3. **Telemetrierate senken.** 100 Hz × 808 B ist der mit Abstand größte
   Funk-Verbraucher im System. Für reines Fahren reichen 25–50 Hz locker:
   `SAMPLE_PERIOD_MS` in `PDS.cpp` auf 20 oder 40 setzen. Das ist der
   wirksamste einzelne Hebel, wenn der Funkkanal das Nadelöhr ist.
4. **Zykluszeit des Roboter-Hauptprogramms.** `pollParamUart()` läuft nur so
   oft, wie `pds.update()` aufgerufen wird. Blockiert die Hauptschleife
   irgendwo (`delay()`, langsame I2C-Sensoren), wirkt sich das 1:1 auf die
   Reaktionszeit aus.
5. **Baudrate erhöhen.** `UART_DBG_BAUD` in `params.h` und `UART_BAUD` in
   `uart_receiver.py` **gemeinsam** auf 2 Mbps. Der Uplink liegt bei 1 Mbps
   schon bei ~81 % Auslastung; darüber gibt es keine Reserve mehr für die
   Deskriptor-Chunks.

---

## 5. Geänderte Dateien

| Datei | Änderung |
|---|---|
| `teensy_firmware/src/PDS.cpp` | Parser-Fix (1.1), RX-Puffer (1.2), `sampleBoundChannels()` nur noch vor dem Packen, Deskriptor-Chunk nur bei freiem TX-Puffer, Bereichsprüfung in `DBG()`, Überlauf-Fix im JSON-Bau |
| `teensy_firmware/src/PDS.h` | Diagnose-Zähler + `fastParamAgeMs()`, korrigierter Kopfkommentar (808 statt 1608 Byte), `enum.h` optional |
| `bridge/param_bridge.py` (v7) | **Discovery-Paket an BEIDE Nodes (1 Hz, 4 Byte, Magic `0xD15C0BE5`, Port 7031/7032)**: der inaktive Node hatte vorher nie eine Zieladresse gelernt und seine kompletten 80 kB/s dauerhaft gebroadcastet — das hat den Funkkanal auch fuer den aktiven Node belastet. Das Paket enthaelt keine Parameter und wird vom Node nicht an den Teensy weitergeleitet. |
| `rpi_zero_node/uart_receiver.py` | Unicast-Ziel (1.3), Coalescing überholter Pakete, `ioctl` statt `subprocess`, Teilschreib-Erkennung, Deskriptor-Assembler ohne Dauerkopieren |
| `.../bridge/controller_bridge.py` | kein eigener Timer mehr (1.4), UI-Drosselung, Event-Queue leeren, Warmup gegen Trigger-Fehlstand, konfigurierbares Mapping |
| `.../bridge/param_bridge.py` | Poll+Senden im selben Tick (1.4), `PreciseTimer`, nicht-blockierender Socket, Drop-Zähler |
| `.../bridge/app_bridge.py` | beide Node-Queues leeren, LED-Timeout |
| `.../config.py` | `NODE_TIMEOUT_SEC`, `CONTROLLER_UI_NOTIFY_MS`, `CONTROLLER_CONFIG_PATH` |
