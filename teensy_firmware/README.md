# PDS — Teensy-Bibliothek

Telemetrie und Fernsteuerung fuer Teensy 4.x, Gegenstelle zum Power Debug
Monitor (RPi 5 / PC). 200 Kanaele mit 100 Hz raus, 50+50+5 Parameter rein —
**ohne dass man sich um Kanalnummern kuemmern muss.**

---

## In 30 Sekunden

```cpp
#include "PDS.h"

float speed = 0;

void setup() {
    PDS.begin();
}

void loop() {
    speed = PDS.fastParam(0);      // Wert vom Joystick / PS4-Controller
    PDS.plot("Speed", speed);      // taucht in der GUI als "Speed" auf
    PDS.update();                  // genau 1x pro loop()
}
```

Mehr ist nicht noetig. `PDS` ist eine fertige globale Instanz — kein eigenes
Objekt anlegen, kein `init()`-Ritual, keine Kanaltabelle pflegen.

---

## Einbau in ein bestehendes Roboter-Projekt

**Variante A — Dateien kopieren (am einfachsten):**
`src/PDS.h`, `src/PDS.cpp`, `src/params.h` und `src/channel_config.h` in den
`src/`-Ordner des Roboter-Projekts kopieren. Fertig.

**Variante B — als PlatformIO-Library einbinden:**
```ini
lib_deps = symlink://../Robotic_PDS/teensy_firmware
```
`library.json` sorgt dafuer, dass nur `PDS.cpp` mitkompiliert wird (nicht der
Beispiel-Sketch `main.cpp`).

`channel_config.h` ist **optional** — fehlt sie, laeuft alles unveraendert,
nur ohne vorbelegte Namen und Overlays.

---

## Die vier Wege, einen Wert in die GUI zu bekommen

| Weg | Wann |
|---|---|
| `PDS.plot("Ball_X", ballX);` | Normalfall. Kanal wird beim ersten Aufruf automatisch vergeben, der Name geht an die GUI. |
| `PDS.track("Akku", &akkuVolt);` | Einmal in `setup()`. Der Wert wird danach 100x/s automatisch abgeholt — im `loop()` ist nichts mehr zu tun. |
| `PDS.bind("Akku", &akkuVolt, 12);` | Wie `track()`, aber auf einer **festen** Kanalnummer — noetig, wenn ein Overlay in der GUI genau auf diesen Kanal zeigt. |
| `PDS.Channel(12, wert);` | Fester Kanal, klassisch, ohne Bindung. |

`plot()`, `track()` und `bind()` funktionieren mit **jedem** Zahlentyp:
`float`, `double`, `bool` und alle Ganzzahltypen (`int`, `long`, `short`,
`uint8_t`, `size_t`, …). Ein nicht unterstuetzter Typ erzeugt eine
Fehlermeldung in Klartext, keine seitenlange Kandidatenliste.

Fuer sehr heisse Schleifen (mehrere kHz) gibt es `PDS_PLOT("Name", wert)` —
identisch zu `plot()`, loest die Kanalnummer aber nur einmalig auf.

### Einheiten

```cpp
PDS.plot("Akku", volt, "V");        // beim Schreiben
PDS.track("Ball_X", &x, "cm");      // beim Binden
PDS.setUnit("Heading", "°");        // nachtraeglich
```

Die Einheit erscheint in der Kanaltabelle und in der Plotter-Legende. Sie ist
reine Anzeige und veraendert nie einen Wert.

---

## Ereignisse und Logzeilen

```cpp
PDS.event("Ball verloren");          // senkrechte Marke im Plotter
PDS.event("Schuss", staerke);        // mit Zahlenwert
PDS.log("Kalibrierung fertig");      // Zeile im Logbuch der GUI
PDS.warn("Akku schwach: %.1f V", v); // gelb
PDS.error("IMU antwortet nicht");    // rot, wird in der Tab-Beschriftung gezaehlt
```

Beides ist **nicht blockierend**: die Meldung wandert in eine kleine
Warteschlange und geht im naechsten `update()` raus, sobald die Leitung Platz
hat. Hoechstens 20 Meldungen pro Sekunde verlassen den Teensy
(`PDS_EVENT_MAX_PER_SEC`) — eine Endlosschleife mit `log()` kann den
100-Hz-Telemetrietakt also nicht verdraengen. Was darueber hinausgeht, zaehlt
`PDS.eventDropCount()`.

Bei vollem Puffer gewinnt bewusst der **aeltere** Eintrag: eine Fehlermeldung
soll nicht von nachfolgendem Rauschen verdraengt werden.

---

## Watchdog

```cpp
void setup() {
    PDS.begin();
    PDS.enableWatchdog(2000);   // Reset, wenn 2 s lang kein update() kommt
}
```

`update()` fuettert den Watchdog selbst — mehr ist nicht zu tun. Bleibt
`loop()` haengen (blockierende I2C-Lesung, Endlosschleife), startet der
Teensy neu, statt bewegungslos mit laufenden Motoren stehenzubleiben. Beim
naechsten Start meldet die Bibliothek den Grund als Fehler ins Logbuch der
GUI — bei einem unerklaerlichen Neustart im Spiel ist das die wichtigste
Einzelinformation.

Wenn im Roboter-Code absichtlich laenger nicht `update()` laeuft (z. B.
waehrend einer Kalibrierfahrt), zwischendurch `PDS.feedWatchdog()` aufrufen.

> Nur Teensy 4.x (Hardware-WDOG1). Aufloesung 0,5 s, Bereich 500…128000 ms.
> Der Watchdog laesst sich per Hardware **nicht wieder abschalten** — genau
> das macht ihn verlaesslich.

---

## Firmware-Version

```cpp
PDS.setFirmwareVersion("1.4.2");    // oder -DPDS_FW_VERSION='"1.4.2"'
```

Erscheint in der Fusszeile der GUI und im Diagnose-Tab. Ohne Angabe meldet
der Teensy seinen Compilier-Zeitpunkt, was fuer die Frage "laeuft auf beiden
Robotern derselbe Stand?" meistens schon reicht.

---

## Werte von der GUI lesen

```cpp
float x   = PDS.fastParam(0);     // 5 Floats, 100 Hz  (Joystick/Controller)
float kp  = PDS.param(3);         // 50 Floats, 2 Hz   (Tuning)
bool  aus = PDS.paramBool(0);     // 50 Bools,  2 Hz   (Schalter)

// … oder per Name, sobald channel_config.h ausgefuellt ist:
float kp2 = PDS.param("Kp_Heading");
```

**Not-Aus:** `PDS.linkOk()` ist `false`, sobald die GUI laenger nicht mehr
sendet. Genau das gehoert in jeden Roboter-Loop:

```cpp
if (!PDS.linkOk()) { motorenStopp(); }
```

---

## Die GUI-Konfiguration: `channel_config.h`

Der Teensy ist die Quelle der Wahrheit fuer die komplette Oberflaeche. In
dieser einen Datei stehen:

* **Parameter** — Name, Bedienelement, Wertebereich, Schrittweite und Gruppe.
  Die GUI baut den Parameter-Tab exakt danach auf.
* **Joysticks** — je zwei Parameter zu einem Pad gebuendelt.
* **Overlays** — Gauges, Feldansicht, Tabellen und Textbloecke der
  Systemansicht.
* Optional feste **Kanalnamen und Einheiten** fuer Kanaele, die tief in
  fremdem Library-Code geschrieben werden.

Debug-Kanaele benennt man dagegen bequemer direkt im Sketch mit
`plot()`/`track()`/`bind()`.

Die GUI **speichert alles dauerhaft** auf dem Raspberry Pi (je Node getrennt)
— nach einem Neustart steht sofort wieder alles da, auch ohne eingeschalteten
Roboter. Aendert man `channel_config.h` und flasht neu, setzt sich die neue
Fassung durch; sonst bleiben Anpassungen erhalten, die in der GUI selbst
gemacht wurden.

Der Teensy schickt die Namen automatisch an die GUI:

* beim Boot,
* alle 5 s, solange die GUI noch nicht antwortet (`PDS_DESC_REPEAT_MS`),
* sofort, wenn die Verbindung zur GUI (wieder) zustande kommt,
* auf Knopfdruck ("Kanalnamen anfordern" in der GUI).

Ein Neustart von Teensy, Node **oder** GUI ist damit unkritisch — die Namen
finden sich von allein wieder ein.

---

## Diagnose

```cpp
PDS.enableSelfDiagnostics();   // in setup(): 6 Zaehler auf die letzten Kanaele
PDS.printStatus();             // eine Klartext-Zeile auf USB-Serial
```

| Methode | Bedeutung |
|---|---|
| `PDS.fastParamAgeMs()` | Alter des letzten Fast-Pakets in ms (normal 0…10) |
| `PDS.txPacketCount()` / `txDropCount()` | gesendete / wegen vollem Puffer verworfene Pakete |
| `PDS.paramSyncLosses()` | verlorene Bytes auf der RX-Leitung (Verkabelung/Baudrate) |
| `PDS.usedChannels()` | wie viele Kanaele die Auto-Vergabe schon belegt hat |
| `PDS.eventSentCount()` / `eventDropCount()` | gesendete / verworfene Ereignisse |
| `PDS.watchdogResetOccurred()` | kam der letzte Reset vom Watchdog? |
| `PDS.descriptorTruncated()` | passte die Konfiguration nicht in den Puffer? |

Die GUI zeigt ausserdem von sich aus **Paketverlust**, **Round-Trip-Zeit**
und den Systemzustand des Pi Zero im Diagnose-Tab an — dafuer ist im
Roboter-Code nichts zu tun.

---

## Build-Flags (`platformio.ini`)

| Flag | Default | Wirkung |
|---|---|---|
| `ACTIVE_CHANNELS` | 200 | Wie viele Kanaele Namen/Bindungen tragen koennen (≤ 200). |
| `PDS_AUTO_CHANNEL_BASE` | 0 | Ab welchem Kanal `plot()`/`track()` automatisch vergeben. |
| `PDS_DESC_REPEAT_MS` | 5000 | Wiederholrate der Namensmeldung ohne GUI (0 = aus). |
| `PDS_DESC_BUF_BYTES` | 24576 | Groesse des Deskriptor-Puffers (liegt auf Teensy 4.x im OCRAM). |
| `PDS_NAME_CACHE_SIZE` | 128 | Groesse des Namens-Caches (Zweierpotenz). |
| `PDS_MAX_UNITS` | 32 | Wie viele Kanaele eine Einheit tragen koennen. |
| `PDS_EVENT_QUEUE_SIZE` | 8 | Wie viele Ereignisse zwischengepuffert werden. |
| `PDS_FW_VERSION` | "" | Version der Roboter-Firmware, z. B. `-DPDS_FW_VERSION='"1.4.2"'`. |

Ob die Konfiguration in den Puffer passt, muss man nicht raten:
`python tools/desc_json_check.py` uebersetzt die Bibliothek fuer den PC,
fuehrt sie aus und meldet einen Ueberlauf.

---

## Verkabelung

```
Teensy Pin 14 (TX3) ──→ RPi Zero Pin 10 (GPIO15, UART RX)
Teensy Pin 15 (RX3) ←── RPi Zero Pin  8 (GPIO14, UART TX)   ← PFLICHT
Teensy GND          ─── RPi Zero Pin  6 (GND)
```

Die RX-Leitung ist **nicht optional** — ohne sie gibt es keinen
Parameter-/Joystick-Downlink. Andere UART-Instanz? Nur `UART_DBG` in
`params.h` aendern, der Rest folgt automatisch.
