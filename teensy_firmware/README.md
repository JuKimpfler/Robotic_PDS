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

## Die drei Wege, einen Wert in die GUI zu bekommen

| Weg | Wann |
|---|---|
| `PDS.plot("Ball_X", ballX);` | Normalfall. Kanal wird beim ersten Aufruf automatisch vergeben, der Name geht an die GUI. |
| `PDS.track("Akku", &akkuVolt);` | Einmal in `setup()`. Der Wert wird danach 100x/s automatisch abgeholt — im `loop()` ist nichts mehr zu tun. |
| `PDS.Channel(12, wert);` | Wenn eine feste Kanalnummer gewuenscht ist (klassisches Verhalten). |

`plot()`/`track()` funktionieren mit jedem Zahlentyp (`float`, `double`,
`int`, `bool`, `uint32_t`, …).

Fuer sehr heisse Schleifen (mehrere kHz) gibt es `PDS_PLOT("Name", wert)` —
identisch zu `plot()`, loest die Kanalnummer aber nur einmalig auf.

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

## Kanalnamen und Overlays: `channel_config.h`

Dort stehen die Namen der **Parameter** (die kommen von der GUI und koennen
im Sketch nicht "beim Schreiben" benannt werden) und die **Overlays**
(Gauges, Feldansicht, Tabellen). Debug-Kanaele benennt man dagegen bequemer
direkt im Sketch mit `plot()`/`track()`.

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

---

## Build-Flags (`platformio.ini`)

| Flag | Default | Wirkung |
|---|---|---|
| `ACTIVE_CHANNELS` | 200 | Wie viele Kanaele Namen/Bindungen tragen koennen (≤ 200). |
| `PDS_AUTO_CHANNEL_BASE` | 0 | Ab welchem Kanal `plot()`/`track()` automatisch vergeben. |
| `PDS_DESC_REPEAT_MS` | 5000 | Wiederholrate der Namensmeldung ohne GUI (0 = aus). |
| `PDS_DESC_BUF_BYTES` | 12288 | Groesse des Deskriptor-Puffers (liegt auf Teensy 4.x im OCRAM). |
| `PDS_NAME_CACHE_SIZE` | 128 | Groesse des Namens-Caches (Zweierpotenz). |

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
