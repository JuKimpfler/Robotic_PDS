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

## Blockierfreiheit — `update()` wartet auf nichts

Die wichtigste Zusage dieser Bibliothek: **`PDS.update()` haelt den Roboter
unter keinen Umstaenden an.** Nicht ohne GUI, nicht wenn die Gegenstelle
mitten im Satz abstuerzt, nicht bei Muell auf der Leitung — und auch nicht,
wenn in dieser Bibliothek selbst etwas kaputt ist.

Das ist keine Eigenschaft des Normalbetriebs, sondern vier eingebaute
Grenzen:

| | Was | Standard | Zur Laufzeit |
|---|---|---|---|
| **Zeitbudget** | Alles ausser Telemetrie und Param-Empfang laeuft nur, solange vom Budget etwas uebrig ist. Der Rest wartet auf den naechsten Aufruf. | 400 µs | `setUpdateBudget(us)` |
| **RX-Budget** | Der Param-Parser liest hoechstens so viele Bytes je Aufruf. Ein Dauerstrom auf der Leitung kann die Schleife nicht festhalten. | 1024 B | `setRxByteBudget(n)` |
| **Scheiben** | Der Namens-Deskriptor (bis 24 kB JSON) wird ueber viele `update()` hinweg zusammengesetzt statt in einem Rutsch. | 12 Eintraege/Aufruf | `PDS_DESC_BUILD_STEP` |
| **Notbremse** | Dauert ein `update()` trotzdem laenger als das Panik-Limit, faellt zuerst der Deskriptor weg und danach PDS ganz. Telemetrie und Fernsteuerung bleiben so lange wie moeglich. | 5 ms, 5 Verstoesse | `setPanicLimit(us, n)` |

Dazu kommen ein **Resync-Timeout** im Parser (50 ms) gegen abgebrochene
Pakete und ein **Mindestabstand** zwischen zwei Deskriptor-Versaenden (1 s),
damit eine zappelnde Verbindung keinen Dauerversand ausloest.

`Serial`-Ausgaben der Bibliothek pruefen vorher `availableForWrite()` und
fallen lieber aus, als zu warten: auf dem Teensy 4 wartet `Serial.print()`
bis zu **120 ms**, wenn der Host die Schnittstelle offen hat, sie aber nicht
leerliest — ein weggescrolltes Terminalfenster reicht dafuer.
`PDS.setSerialDiagnostics(false)` schaltet sie ganz ab.

Nachmessen statt hoffen:

```cpp
PDS.printStatus();          // ... | update 41/312 us | ...
PDS.maxUpdateMicros();      // laengster Aufruf seit dem Start
PDS.lastUpdateMicros();
PDS.budgetOverruns();       // wie oft das Budget nicht reichte
PDS.degraded();             // true = Notbremse hat den Deskriptor abgeschaltet
PDS.enabled();              // false = Notbremse hat PDS abgeschaltet
PDS.enable(true);           // hebt beides wieder auf
```

Nicht dazu gehoert der Roboter-Code selbst: bleibt `loop()` an anderer Stelle
haengen, hilft nur der Watchdog (siehe oben).

---

## Die Oberflaeche vom Roboter aus einstellen

Alles, was in der `settings.json` der GUI steht, laesst sich aus der Firmware
vorgeben — mit demselben Punktpfad:

```cpp
void setup() {
    PDS.begin();
    PDS.setting("ui.dark", true);                       // Wahrheitswert
    PDS.setting("ui.fontScale", 1.2f);                  // Zahl
    PDS.setting("plotter.historySeconds", 20);          // ganze Zahl
    PDS.setting("theme.colors.dark.accentGreen", "#00ff88");   // Farbe
}
```

Der Typ ergibt sich aus dem geschriebenen Wert. Fuer die haeufigsten Faelle
gibt es benannte Abkuerzungen:

```cpp
PDS.guiDarkMode(true);
PDS.guiFontScale(1.2f);
PDS.guiKiosk(true);
PDS.guiStartTab(2);                            // 2 = Systemansicht
PDS.guiBatteryWarning(10, 11.5f, 10.8f);       // Kanal, Warnung, Alarm
PDS.guiPlotter(20, 500, 8);                    // Sekunden, Punkte, Kurven
PDS.guiCurveColor(0, "#00ff88");
PDS.guiColor("accentGreen", "#00ff88");        // Theme-Farbe (dunkel)
```

Statt im Sketch geht auch die Tabelle `GUI_SETTINGS[]` in
`channel_config.h` — dieselbe Wirkung, nur an einer Stelle. Im Sketch
gesetzte Werte gewinnen (sie laufen nach `begin()`).

Die Werte reisen im Namens-Deskriptor mit, werden auf dem Raspberry Pi **je
Node** gespeichert und gelten damit auch beim naechsten Start ohne
eingeschalteten Roboter. Es gilt dieselbe Konfliktregel wie fuer Kanalnamen
und Overlays: **unveraenderte Firmware ueberschreibt keine Handarbeit,
geaenderte Firmware setzt sich durch.**

Und dasselbe Fehlerprinzip wie fuer die Datei selbst — ein unsinniger Wert
kostet hoechstens sein eigenes Feld:

| Fall | Folge |
|---|---|
| Pfad gibt es nicht | verworfen, steht im Logbuch der GUI |
| Typ passt nicht (`"ja"` an einem Schalter) | verworfen, der lokale Wert bleibt |
| Pfad zeigt auf einen ganzen Abschnitt | verworfen |
| Wert ausserhalb seines Bereichs | hineingelegt (`ranges` in settings.json) |
| `network.*` | **grundsaetzlich** verworfen |

`network.*` ist bewusst gesperrt: eine falsche IP in der Firmware wuerde
genau die Leitung kappen, ueber die man sie korrigieren muesste. Der Roboter
darf sein Aussehen bestimmen, nicht den Weg zu sich selbst.

Im Diagnose-Tab steht dafuer ein eigener Schalter neben „Konfiguration vom
Teensy uebernehmen": die Kanalnamen will man praktisch immer vom Roboter, das
Aussehen des eigenen Tablets nicht unbedingt.

Weitere Methoden: `PDS.removeSetting("ui.dark")`, `PDS.clearSettings()`,
`PDS.settingCount()`. Nach einer Aenderung zur Laufzeit meldet
`PDS.announceChannelNames()` den neuen Stand.

---

## Die Bibliothek zur Laufzeit einstellen

Was frueher nur als Build-Flag ging, geht auch im Sketch. Alle Setter
**begrenzen** ihren Wert, statt ihn zu verwerfen oder blind zu uebernehmen —
ein Tippfehler kostet nie mehr als diese eine Einstellung.

```cpp
PDS.setTelemetryRate(50);        // 1..1000 Hz; 50 Hz halbiert die Leitungslast
PDS.enableTelemetry(false);      // Kanaele weiter pflegen, nichts senden
PDS.setParamAckInterval(1000);   // Rueckmeldung seltener (100..10000 ms)
PDS.enableParamAck(false);
PDS.setEventRateLimit(5);        // hoechstens 5 Meldungen/s (1..200)
PDS.enableEvents(false);
PDS.setDescriptorRepeat(10000);  // Namensmeldung ohne GUI alle 10 s (0 = aus)
PDS.enableDescriptor(false);
PDS.setFastTimeout(200);         // Schwellen fuer linkOk()
PDS.setSlowTimeout(2000);
PDS.setAutoChannelBase(50);      // ab hier vergibt plot()/track()
PDS.setSerialDiagnostics(false); // keine Klartextmeldungen ueber USB
PDS.enable(false);               // PDS ganz stilllegen (update() kostet dann nichts)
```

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
| `PDS.rxResyncCount()` | wie oft ein abgebrochenes Paket den Parser zurueckgesetzt hat |
| `PDS.lastUpdateMicros()` / `maxUpdateMicros()` | Dauer des letzten / laengsten `update()` |
| `PDS.budgetOverruns()` / `panicCount()` | wie oft Zeitbudget bzw. Panik-Limit gerissen wurden |
| `PDS.degraded()` / `enabled()` | hat die Notbremse zugeschlagen? |
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
| `PDS_MAX_SETTINGS` | 32 | Wie viele Oberflaechen-Einstellungen der Teensy vorgeben kann. |
| `PDS_UPDATE_BUDGET_US` | 400 | Zeitbudget je `update()` fuer alles ausser Telemetrie/Empfang. |
| `PDS_UPDATE_PANIC_US` | 5000 | Ab dieser Dauer gilt ein `update()` als Fehlfunktion. |
| `PDS_UPDATE_PANIC_STRIKES` | 5 | So oft, bevor die Notbremse greift (0 = aus). |
| `PDS_RX_BYTE_BUDGET` | 1024 | Hoechstens so viele empfangene Bytes je `update()`. |
| `PDS_RX_PACKET_TIMEOUT_MS` | 50 | Nach dieser Ruhe faengt der Parser von vorn an (0 = aus). |
| `PDS_DESC_MIN_GAP_MS` | 1000 | Mindestabstand zwischen zwei Deskriptor-Versaenden. |
| `PDS_DESC_BUILD_STEP` | 12 | Eintraege je `update()` beim Bauen des Deskriptors. |

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
