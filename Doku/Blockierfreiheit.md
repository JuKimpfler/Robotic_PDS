# Blockierfreiheit der Teensy-Bibliothek

> **Zusage:** `PDS.update()` hält den Roboter unter keinen Umständen an.
> Nicht ohne GUI, nicht wenn die Gegenstelle mitten im Satz abstürzt, nicht
> bei Müll auf der Leitung — und auch nicht, wenn in dieser Bibliothek selbst
> etwas kaputt ist.

Bis PDS 2.1 war das eine Eigenschaft des *Normalbetriebs*, keine zugesicherte
Eigenschaft der Bibliothek. Solange die Gegenstelle sauber mit 100 Hz sendete,
fiel das nicht auf. Dieses Dokument beschreibt, woran es lag, was sich geändert
hat und wie man es nachmisst.

---

## Der gemeldete Fehler

> „Das PDS legt den ganzen Teensy lahm, sobald es **ohne angeschlossenen
> PS4-Controller** gestartet wird. Ist der Controller einmal eingesteckt,
> läuft alles wieder — auch wenn man ihn danach wieder abzieht."

Dass ausgerechnet ein Eingabegerät am *Raspberry Pi* über das Verhalten des
*Teensy* entscheidet, klingt zunächst unsinnig. Es ist aber genau die Spur:
der Controller verändert nicht den Teensy, sondern den **Takt**, in dem er
bedient wird — und der Teensy reagierte darauf empfindlich.

### Was der fehlende Controller auf der Pi-Seite auslöste

`ControllerBridge.poll()` läuft mit 100 Hz im Sende-Thread, unmittelbar bevor
das Fast-Paket gepackt wird (siehe
[PS4_Controller_Implementierung.md](PS4_Controller_Implementierung.md) und
[Latenz_Fernsteuerung.md](Latenz_Fernsteuerung.md)). Die Hot-Plug-Erkennung
sollte dabei ausdrücklich nur alle 500 ms laufen — geschrieben war sie so:

```python
if self._joystick is None or (now - self._last_count_check) >= 0.5:
    self._count_cache = pygame.joystick.get_count()
```

Ohne angeschlossenen Controller ist `_joystick` **immer** `None`. Die
Drosselung hob sich also ausgerechnet in dem Fall auf, für den sie gedacht
war: `get_count()` lief mit vollen 100 Hz statt mit 2 Hz. SDL geht dabei über
die Geräteliste — im selben Thread, der 10 ms später das nächste Fast-Paket
verschicken soll. Der 100-Hz-Takt der Fernsteuerung wurde unregelmäßig.

Nach dem ersten Einstecken war `_joystick` nicht mehr `None`, und auch nach
dem Abziehen blieb der Prozess in einem Zustand, in dem SDL die Geräteliste
bereits aufgebaut hatte — der Takt blieb sauber. Genau das beschreibt die
Beobachtung „einmal eingesteckt, dann geht es".

### Was der unregelmäßige Takt auf dem Teensy auslöste

Vier Stellen in der Bibliothek waren **nicht nach oben begrenzt**. Jede
einzelne war für sich harmlos, zusammen ergaben sie einen Roboter, der
sekundenlang nicht mehr regelte.

#### 1. Der Namens-Deskriptor entstand in einem Zug

`buildDescriptorJson()` schrieb bis zu 24 kB JSON in einem einzigen Aufruf —
über 1500 `vsnprintf`-Aufrufe, mitten in `update()`, also mitten in der
Regelschleife. Und ausgerechnet **ohne** GUI passierte das regelmäßig: in
Ruhe wird der Deskriptor alle 5 s wiederholt, damit eine später gestartete
GUI die Kanalnamen von allein findet.

#### 2. Eine zappelnde Verbindung startete den Versand immer wieder neu

`linkOk()` wird aus dem Alter des letzten Fast-Pakets gebildet (150 ms
Schwelle). Kam die Fernsteuerung unregelmäßig, wechselte der Zustand mehrmals
pro Sekunde — und **jede** steigende Flanke löste einen kompletten
Deskriptor-Versand aus (24 Chunks bei 6 kB), bei Bedarf mit Neubau.

Dazu kam ein Verstärker: `setName()` erklärte den Deskriptor bei **jedem**
Aufruf für ungültig, auch wenn sich der Name gar nicht geändert hatte.
`PDS.Channel(12, wert, "Name")` in der Regelschleife ist ein völlig üblicher
Aufruf — und landete damit 100-mal pro Sekunde hier. Jeder Versand baute die
24 kB neu auf.

#### 3. Der Param-Parser blieb an einem abgebrochenen Paket hängen

Brach die Gegenstelle mitten im Paket ab (Absturz der GUI, Neustart des Node,
Wackelkontakt), wartete der Parser **unbegrenzt** auf die fehlenden Bytes.
Traf danach ein neues Paket ein, verfütterte er dessen erste Hälfte als
vermeintliche Nutzlast an das abgebrochene.

Das Ergebnis war nicht etwa ein leerer Wert, sondern ein **Zufallswert in
`fastParam()`** — zusammengesetzt aus der Mitte eines fremden Pakets. Und
`_lastFastRxMs` wurde dabei gesetzt, `linkOk()` meldete also „alles in
Ordnung". Bei einem Joystick- oder Gas-Kanal fährt der Roboter damit davon.
Das ist der ernsteste Einzelbefund dieser Runde.

#### 4. `Serial.print()` durfte warten

`pdsWarn()` prüfte nur, **ob** ein USB-Terminal offen ist — nicht, ob dessen
Puffer die Zeile auch aufnimmt. Auf dem Teensy 4 wartet `Serial.print()` in
diesem Fall bis zu **120 ms**; ein offenes, weggescrolltes Terminalfenster
genügt dafür. `printStatus()` hatte gar keine Prüfung, und der Beispiel-Sketch
ruft es einmal pro Sekunde auf.

---

## Was jetzt gilt

Vier eingebaute Grenzen, alle über Build-Flags **und** zur Laufzeit
einstellbar:

| | Was | Standard | Zur Laufzeit |
|---|---|---|---|
| **Zeitbudget** | Alles außer Telemetrie und Param-Empfang läuft nur, solange vom Budget etwas übrig ist. Der Rest wartet auf den nächsten Aufruf. | 400 µs | `setUpdateBudget(us)` |
| **RX-Budget** | Der Parser liest höchstens so viele Bytes je Aufruf. Ein Dauerstrom kann die Schleife nicht festhalten. | 1024 B | `setRxByteBudget(n)` |
| **Scheiben** | Der Deskriptor wird über viele `update()` hinweg zusammengesetzt — eine Zustandsmaschine über die Abschnitte (`_descStage`/`_descIdx`). | 12 Einträge | `PDS_DESC_BUILD_STEP` |
| **Notbremse** | Dauert ein `update()` trotzdem länger als das Panik-Limit, fällt zuerst der Deskriptor weg und danach PDS ganz. | 5 ms, 5 Verstöße | `setPanicLimit(us, n)` |

Dazu:

* **Resync-Timeout** (`PDS_RX_PACKET_TIMEOUT_MS`, 50 ms): ein Paket ohne
  Fortschritt setzt den Parser zurück, statt das nächste zu vergiften.
  `PDS.rxResyncCount()` zählt, wie oft das nötig war.
* **Mindestabstand** zwischen zwei Deskriptor-Versänden
  (`PDS_DESC_MIN_GAP_MS`, 1 s). Eine ausdrückliche Anfrage der GUI übergeht
  ihn — sie kommt ja nicht alle 100 ms.
* **`setName()` prüft auf Gleichheit**, bevor es den Deskriptor für ungültig
  erklärt.
* **Serial-Ausgaben prüfen `availableForWrite()`** und fallen lieber aus, als
  zu warten. `PDS.setSerialDiagnostics(false)` schaltet sie ganz ab.

### Die Reihenfolge in `update()`

```
1. Watchdog füttern      immer — auch wenn PDS abgeschaltet oder in der
                         Notbremse ist. Wer ihn eingeschaltet hat, verlässt
                         sich darauf.
2. Param-Downlink lesen  mit Byte-Budget; vor dem Senden, damit fastParam()
                         direkt nach update() den frischesten Stand liefert.
3. Telemetrie senden     der 100-Hz-Takt, Vorrang vor allem anderen, schreibt
                         nie blockierend (availableForWrite).
4. Alles Übrige          Ereignisse, Rückmeldung, Deskriptor — nur mit
                         Restbudget. Was nicht drankommt, kommt beim nächsten
                         Aufruf dran.
5. Selbstmessung         noteUpdateDuration(): Budget-Überschreitungen zählen,
                         Panik-Limit auswerten.
```

Die Notbremse schaltet in **zwei** Stufen ab, und die Reihenfolge ist
Absicht: zuerst fällt der Deskriptor weg (der einzige Weg, der überhaupt
nennenswert Zeit brauchen *kann*), Telemetrie und Fernsteuerung bleiben. Erst
wenn auch das nicht reicht, schaltet sich PDS ganz ab — der Roboter fährt
dann blind weiter, statt stehenzubleiben. `PDS.enable(true)` hebt beide
Stufen wieder auf.

---

## Nachmessen

```cpp
PDS.printStatus();
// [PDS 2.2 fw 1.4.2] TX=12043 (drop 0) | Slow=241 Fast=12041 | Alter=3 ms |
// Sync-Verluste=0 (Resync 0) | Kanaele=14 | Ereignisse=7 (verworfen 0) |
// update 41/312 us | WDT
```

| Methode | Bedeutung |
|---|---|
| `lastUpdateMicros()` / `maxUpdateMicros()` | Dauer des letzten / längsten `update()` |
| `budgetOverruns()` | wie oft das Zeitbudget nicht reichte (harmlos, aber ein Hinweis) |
| `panicCount()` | wie oft das Panik-Limit gerissen wurde |
| `degraded()` | Notbremse Stufe 1: Deskriptor aus |
| `enabled()` | `false` = Notbremse Stufe 2: PDS aus |
| `rxResyncCount()` | abgebrochene Pakete auf der Leitung |
| `resetUpdateStats()` | Maximum und Zähler zurücksetzen |

`PDS.enableSelfDiagnostics()` legt die wichtigsten davon auf Kanäle — dann
sieht man sie im Plotter der GUI statt nur über USB-Serial.

---

## Wie das geprüft wird

`tools/desc_json_check.py` übersetzt `PDS.cpp` mit einer Arduino-Attrappe für
den PC (`tools/hostsim/`) und **führt sie aus**. Für diese Runde kann die
Attrappe zwei Dinge mehr:

* **Bytes in den Empfänger legen** (`Serial3.feed(...)`) — damit lässt sich
  ein abgebrochenes Downlink-Paket wirklich nachstellen.
* **Die Uhr während eines `update()` weiterlaufen lassen**
  (`pds_sim_micros_step`) — ohne vergehende Zeit wäre nie ein Zeitbudget
  aufgebraucht, und der scheibenweise Bau bliebe ungetestet.

Damit prüft die CI vier Zusagen wirklich ausgeführt:

| Prüfung | Vorher |
|---|---|
| Deskriptor wird über **mehrere** `update()` gebaut | 1 Aufruf, mehrere Millisekunden |
| ein abgebrochenes Paket setzt den Parser zurück | Parser blieb hängen |
| das nächste Paket kommt mit dem **richtigen** Wert an | Zufallswert aus der Paketmitte |
| die Notbremse greift und lässt sich wieder aufheben | gab es nicht |

Dazu 21 neue Prüfungen in `tools/selftest.py` (Abschnitt 17) für die
Einstellungen, die der Teensy vorgibt — siehe
[Teensy_Einstellungen.md](Teensy_Einstellungen.md).

---

## Was das **nicht** abdeckt

* **Den Roboter-Code selbst.** Bleibt `loop()` an einer blockierenden
  I2C-Lesung oder einer Endlosschleife hängen, hilft nur der Hardware-
  Watchdog: `PDS.enableWatchdog(2000)`.
* **Einen verirrten Zeiger aus `bind()`/`track()`.** Zeigt eine Bindung auf
  Speicher, der nicht mehr existiert, liest `sampleBoundChannels()` ihn
  trotzdem. Dagegen hilft keine Zeitmessung, sondern nur, den Zeiger am Leben
  zu halten — gebundene Variablen gehören auf Dateiebene, nicht auf den Stack
  einer Funktion.
* **Die Funkstrecke.** `linkOk()` bleibt das Not-Aus-Kriterium im
  Roboter-Code:

  ```cpp
  if (!PDS.linkOk()) { motorenStopp(); }
  ```
