# Änderungsverlauf

Alle nennenswerten Änderungen am Power Debug System.

## Versionierung — welche Nummer bedeutet was

Es gibt bewusst **zwei** Nummern, und nur die zweite darf einem Sorgen machen:

| Nummer | Wo sie steht | Bedeutung |
|---|---|---|
| `PDS_VERSION` | `teensy_firmware/src/PDS.h` | Version der Bibliothek/GUI. Erscheint in der Fußzeile und in `PDS.printStatus()`. Rein informativ. |
| `PDS_WIRE_VERSION` | `teensy_firmware/src/params.h`, gespiegelt in `uart_receiver.py` und `config.py` | Version des **Wire-Formats**. Ändert sich sie, müssen Teensy, Node und GUI **gemeinsam** aktualisiert werden. |

`tools/check_wire_format.py` vergleicht beide Seiten automatisch und schlägt
fehl, sobald eine der drei Stellen nicht nachgezogen wurde.

Die Version der eigenen **Roboter-Firmware** ist davon unabhängig und wird im
Sketch gesetzt (`PDS.setFirmwareVersion("1.4.2")` oder Build-Flag
`-DPDS_FW_VERSION='"1.4.2"'`). Sie kommt im Deskriptor mit und steht in der
Fußzeile der GUI — damit ist auf einen Blick sichtbar, welcher Stand auf
welchem Roboter läuft.

---

## 2.7 — Der Plotter richtet sich nach der Hardware, statt umzukippen

Version 2.6 hat die großen Posten beseitigt. Übrig blieb ein Verhalten, das
auf schwacher Hardware nur zwei Zustände kannte: **volle 12 Bilder pro
Sekunde — oder der Watchdog schaltet den Plotter komplett ab.** Genau das
ist jetzt anders. Dazu kommt ein Messwerkzeug, denn zwei der Annahmen aus
dem Plan haben die Messung nicht überlebt (siehe unten).

### Zuerst: gemessen wird jetzt das Richtige

`note_render()` bekam bisher nur die Dauer von `get_plot_arrays()` +
`setData()` gemeldet. Der Aufruf stand **vor** `_render_to_pixmap()` — und
genau dort rastert Qt das komplette Widget in das Pixmap. Der Wächter hat
also ein Budget von 80 ms überwacht, von dem er den größten Posten nie
gesehen hat. Das Messfenster umfasst jetzt den ganzen Durchlauf.

### Geändert

* **Der Bildtakt richtet sich nach der gemessenen Bilddauer.** `maxFps` ist
  nur noch die Obergrenze; der Takt ergibt sich aus
  `clamp(fpsBudgetFactor × Bilddauer, 1000/maxFps, 1000/minFps)`. Der Faktor
  (Vorgabe 4,0) sagt, wie viel Luft bleiben soll: der Plotter darf höchstens
  ein Viertel der Zeit des GUI-Threads verbrauchen — der hält auch den
  100-Hz-Sendetakt der Fernsteuerung, und **das** ist die eigentliche
  Anforderung.

  | Bilddauer | 2 ms | 30 ms | 45 ms | 60 ms |
  |---|---|---|---|---|
  | Takt | 12,0 fps | 8,3 fps | 5,6 fps | 4,2 fps |

  15 % Hysterese, damit der Takt bei kleinen Lastwechseln nicht springt; am
  Anschlag ohne Hysterese, sonst bliebe er nach einer Lastspitze für immer
  knapp unter `maxFps` stehen.
* **Der Wächter schaltet nicht mehr wegen eines einzigen teuren Durchlaufs
  ab**, sondern erst nach `renderDisableStreak` (3) in Folge. Ein einzelner
  teurer Durchlauf kommt beim Tabwechsel oder beim Ändern der Fenstergröße —
  und seit das Messfenster ehrlich ist, fällt er häufiger an. Anhaltende
  Last fängt jetzt der adaptive Takt ab.
* **Die Normierungsgrenzen kommen aus dem Statistik-Takt.**
  `get_plot_arrays()` rechnete min/max je Kurve **und Bild** — bei acht
  Kurven zwei volle Array-Durchläufe pro Bild, obwohl dieselben Zahlen alle
  200 ms ohnehin anfallen. Damit ein Signal, das zwischendurch auf ein
  Vielfaches seiner Spanne springt, nicht aus dem Bild geschoben wird,
  **wachsen** die gepufferten Grenzen mit jedem eintreffenden Block mit;
  geschrumpft wird nur im Statistik-Takt. Über 400 Blöcke mit Pegelsprüngen
  um den Faktor 10 gemessen: die Kurvenwerte bleiben in 0,000 … 1,000.
* **Bei gemeinsamer Skala steht die Y-Achse still.** Statt
  `enableAutoRange(Y)` nach jedem `setData` wird der Bereich auf glatte
  1-2-5-Schritte gerundet und nur bei echtem Bedarf geändert: wachsen
  sofort, schrumpfen erst, wenn der aktuelle Bereich mehr als doppelt so
  groß ist wie nötig. Gemessen: **91 → 7 Bereichswechsel je 200 Bilder.**
* **Statistik und Wächter kosten nichts mehr, wenn niemand hinsieht.**
  `_update_stats()` hing allein am Datenpfad — Legende und Statistikzeile
  wurden also auch dann fünfmal pro Sekunde über das ganze Fenster
  gerechnet, wenn man seit einer Stunde im Parameter-Tab arbeitet.
  Gemessen: 4 `statsChanged`/s sichtbar, **0/s bei weggeschaltetem Tab**,
  und genau eines sofort beim Zurückschalten. Der Wächter-Timer tickte
  außerdem ab Programmstart dauerhaft mit 4 Hz, auch wenn der Plotter-Tab
  nie geöffnet wurde; er läuft jetzt nur noch, solange der Plotter aktiv
  ist. Bewusst an die **Sichtbarkeit** gekoppelt und nicht daran, ob der
  Plotter eingeschaltet ist: bei Überlastung ist die Legende das Einzige,
  was noch Zahlen zeigt.
* **Die letzten Array-Zuteilungen im Datentakt sind weg.** `_stack()` legte
  je Poll-Durchlauf ein neues Block-Array an, die Flanken-Trigger hängten
  den Vorgängerwert per `np.concatenate` an jeden Block. Beides läuft jetzt
  in vorab angelegten Puffern. Nebenbei: `_snap_buf`, `_live_buf`, `_y_buf`
  und `_mask_buf` waren über die volle Ringgröße (1000 Spalten)
  dimensioniert, angezeigt werden aber höchstens 600 — 100 kB → 60 kB.

### Neu: `tools/plotter_bench.py`

Misst die drei Ebenen getrennt (Datenpfad, Rastern, QML-Legende) und
vergleicht Wert für Wert gegen unabhängige Referenzimplementierungen.
`python tools/plotter_bench.py --verify` läuft in der CI mit: Ringpuffer,
`_stack()`, Kurvenarrays und alle sechs Trigger-Bedingungen müssen dieselben
Zahlen liefern wie vorher.

### Zwei Annahmen, die die Messung nicht überlebt haben

Beides in dieser Umgebung gemessen (offscreen, 800 × 400) und auf dem
Zielgerät nachzumessen — aber deutlich genug, um den weiteren Plan zu
ändern:

1. **„Die Kurven zu rastern ist der teure Teil" stimmt so nicht.** Ein Bild
   mit **einer** Kurve über 250 Punkte kostet 31,9 ms, eines mit **acht**
   Kurven über 600 Punkte 46,7 ms. Der Grundbetrag — Hintergrund, Gitter,
   Achsen — dominiert also alles andere. Das stützt den geplanten
   statischen Hintergrund (M8 Stufe A) und entwertet die Idee, am
   Downsampling zu drehen (K4).
2. **Die QML-Legende ist kein Kostenpunkt.** Ein kompletter
   Delegate-Neuaufbau kostet bei acht Kurven **0,056 ms**, bei 5 Hz also
   0,28 ms pro Sekunde. Der geplante Umbau auf ein `QAbstractListModel`
   (M7) würde nichts Messbares sparen und ist damit vom Tisch.

**Korrektur zu einer Zahl in der Commit-Historie:** der Commit zum
quantisierten Y-Bereich nennt „rund 5 % weniger Rasterarbeit". Der saubere
A/B-Vergleich über sechs abwechselnde Durchläufe ergibt 31,7 ms
(autoRange) gegen 32,3 ms (quantisiert) bei einer Streuung von 2,7 ms
*innerhalb* einer Variante — der Zeitunterschied liegt damit im Rauschen.
Belegt ist nur, was sich zählen lässt: 91 gegen 7 Bereichswechsel. Der
Nutzen der Änderung ist vorerst die ruhige, ablesbare Achse.

### Nicht geändert

* **Darstellung und Bedienung.** Farben, Kurvenzahl, Trigger und Marken
  sind exakt, wie sie waren.
* **Alle neuen Kniffe haben einen Schalter** in `settings.json` →
  `plotter`: `adaptiveFps`, `minFps`, `fpsBudgetFactor`, `quantizeYRange`,
  `cacheNormBounds`, `renderDisableStreak`.

---

## 2.6 — Der Plotter kostet deutlich weniger Rechenzeit und Speicher

Der Live-Plotter lief zwar schon über NumPy und pyqtgraph, verhielt sich aber
so, als wäre Rechenzeit umsonst: er legte im Datentakt fortlaufend neue Arrays
an, ließ QML die Legende 20-mal pro Sekunde neu aufbauen und zeichnete auch
dann ein vollständiges Bild, wenn sich überhaupt nichts geändert hatte.

Eine Messung an acht Kurven mit je 500 Punkten zeigt, wo die Last wirklich
liegt: **rund 95 % gehen für das Rastern der Kurven drauf** (pyqtgraph zeichnet
Gitter, Achsen und alle Polylinien neu), nur etwa 5 % für die Datenaufbereitung.
Entsprechend setzt der größte Hebel am **Bildtakt** an, der Rest an Speicher
und unnötiger Arbeit.

### Geändert

* **Es wird nur noch gezeichnet, wenn es etwas Neues gibt.** Die Datenbrücke
  meldet über `bufferChanged` (und Einfrieren/Marken/Auswahl), dass sich etwas
  geändert hat; ohne solche Meldung überspringt der Takt den ganzen Durchlauf.
  Im eingefrorenen Bild oder bei abgerissener Telemetrie kostet der Plotter
  damit gar nichts mehr statt 20 vollständiger Neuzeichnungen pro Sekunde.
* **Ruhetakt statt Vollgas im Hintergrund.** Ist der Plotter nicht sichtbar
  (anderer Tab) oder abgeschaltet, läuft der Timer auf `plotter.idleFps`
  (Vorgabe 4) herunter, statt 20-mal pro Sekunde nur nachzusehen, ob er etwas
  tun darf.
* **`plotter.maxFps` steht jetzt auf 12 statt 20.** Weil das Rastern die Last
  dominiert, sind das gut 40 % weniger Rechenzeit — ein Trendverlauf läuft
  damit immer noch flüssig. Wer die Leistung hat, stellt in `settings.json`
  wieder 20 (oder mehr) ein.
* **Legende und Statistikzeile laufen gedrosselt** (`plotter.statsIntervalMs`,
  Vorgabe 200 ms) und werden in **einem** Durchlauf für alle Kurven berechnet.
  Vorher stieß jedes Paket ein `statsChanged` an, und QML baute daraufhin den
  Legenden-Repeater komplett neu auf — bei 20 Hz der teuerste einzelne Posten,
  obwohl niemand Zahlen 20-mal pro Sekunde liest. `curveInfo` rechnete dabei
  ein zweites Mal dasselbe. Gemessen: 100 Pakete brauchen statt 37,5 ms nur
  noch 3,4 ms.
* **Im Datentakt entstehen keine neuen Arrays mehr.** Ringpuffer, Fenster,
  Kurvenaufbereitung und Statistik arbeiten in vorab angelegten Puffern
  (zusammen rund 100 kB, einmalig). `get_plot_arrays()` liefert float32 statt
  float64. Kurzlebiger Speicher je Zeichendurchlauf: **45 kB → 2,5 kB**, also
  knapp ein Megabyte pro Sekunde weniger, das der Garbage Collector im
  GUI-Thread wieder einsammeln muss.
* **Der Image-Modus rendert in ein festes QPixmap.** `QWidget.grab()` legte bei
  jedem Bild ein neues an — bei 800×400 gut 1,2 MB, also rund 24 MB/s. Der
  gleichwertige direkte `QWidget.render()`-Aufruf ist pixelgleich, kommt ohne
  diese Zuteilung aus und war in der Messung nebenbei 23 % schneller.
  Zusätzlich `setOpaquePainting(true)`, damit Qt Quick den Hintergrund nicht
  vor jedem Bild sinnlos leert, und ein 1:1-Blitt statt eines skalierten.
* **Kleinkram, der sich im Takt summiert:** die x-Achse wird einmal angelegt
  statt je Bild; `setXRange` (löst ein volles Achsen-Layout aus) nur noch bei
  echter Änderung; Marken-Stifte einmal je Stufe statt je Marke und Bild;
  Markenlinien werden nur angefasst, wenn sich Position, Text oder Stufe
  geändert haben, und der Pool wird gar nicht erst angelegt, solange es keine
  Marken gibt (vorher immer mindestens acht Linien samt Textobjekt in der
  Szene).

### Nicht geändert

Die Darstellung, die Bedienung und das Verhalten bei Überlastung sind
unverändert. `tools/selftest.py` (214 Prüfungen), `check_qml_bindings.py` und
`qml_smoketest.py` laufen unverändert durch; Ringpufferinhalt, Kurvenwerte und
Legendenzahlen wurden zusätzlich Wert für Wert gegen die alte Rechenweise
verglichen.

---

## 2.5 — Alle Einstellungen in einer Datei, mehrere Einstellungssätze

Bis hierher war „einstellbar" eine Frage des Fundorts: die
Bedienereinstellungen lagen in `runtime_config/ui_settings.json`, Farben,
Abstände und Schriftgrößen fest verdrahtet in `qml/Theme.qml`, und die
**Grenzen** der Schieberegler und Drehfelder als Zahlenliteral direkt am
jeweiligen Bedienelement (`from: 0.8; to: 1.6; stepSize: 0.05`). Wer die
Schrift größer stellen können wollte als vorgesehen, musste eine `.qml`-Datei
ändern — und hatte die Änderung beim nächsten `git pull` im Weg.

### Neu

* **`settings.json` neben `main_qml.py`** (neu: `app_settings.py`) hält jetzt
  alles Einstellbare: Farbschema und Schriftgröße, sämtliche Farben für hell
  und dunkel, Abstände/Radien/Schriftgrößen, die **Grenzen aller
  Schieberegler und Drehfelder**, Fenstermaße, Akku-Warnung, Plotter-Puffer
  und Kurvenfarben, Node-Adressen, Poll-Takt und die Controller-Belegung.
  Die Datei wird beim ersten Start mit den Standardwerten angelegt und ist
  zum Bearbeiten von Hand gedacht; `app_settings.DEFAULTS` ist zugleich die
  vollständige Liste aller Schlüssel.
* **Mehrere Einstellungssätze.** Jede Datei `settings.<Name>.json` im selben
  Ordner ist ein Profil. Im Tab **Diagnose → Einstellungssätze** lässt sich
  der aktuelle Stand unter einem Namen ablegen, ein Profil laden oder löschen
  und alles auf die Standardwerte zurücksetzen — „Spiel" mit Kiosk-Modus und
  großer Schrift, „Werkstatt" mit hellem Schema und Tastatursteuerung. Ein
  Einstellungssatz ist bewusst eine Datei: kopieren, sichern und per USB-Stick
  auf den zweiten Pi bringen geht damit ohne die Oberfläche.
* **Start-Tab einstellbar.** Die Einstellung `startTab` gab es schon, benutzt
  hat sie niemand — die Oberfläche startete immer auf „Tabelle". Sie steht
  jetzt als Auswahl in den Einstellungen und wird beim Start angewandt (über
  `TabBar.setCurrentIndex()`, das die Zwei-Wege-Bindung zur SwipeView im
  Gegensatz zu einer Zuweisung stehen lässt).

### Geändert

* **`config.py`** trennt jetzt sichtbar zwei Sorten Konstanten: was zur
  Firmware passen muss (Ports, Magic-Zahlen, Paketgrößen — unverändert dort,
  von `tools/check_wire_format.py` geprüft) und was Geschmackssache ist. Das
  Zweite kommt aus `settings.json`.
* **`qml/Theme.qml`** enthält keine Farb- und Maßliterale mehr, sondern liest
  `appBridge.settings.theme`. Ein Profilwechsel stellt die komplette
  Oberfläche ohne Neustart um, weil alle Bindungen ohnehin durch dieses
  Singleton laufen.
* **`settings.json` und `settings.*.json` sind git-ignoriert** — dieselbe
  Überlegung wie bei `runtime_config/`: die Datei wird zur Laufzeit
  beschrieben, und ein `git pull` auf dem Pi soll nicht an lokal geänderten
  Einstellungen scheitern.
* **Übernahme des alten Standes:** eine vorhandene
  `runtime_config/ui_settings.json` wird beim ersten Start einmalig
  eingelesen, nach `settings.json` geschrieben und danach in
  `ui_settings.json.uebernommen` umbenannt. Erst schreiben, dann umbenennen —
  schlägt das Schreiben fehl, versucht es der nächste Start erneut.
* **Selbsttest**: 179 → 214 Prüfungen. Neuer Abschnitt 16 (`app_settings`):
  falsche Typen, kaputte Bereiche, Farben ohne `#`, Werte außerhalb ihres
  eigenen Bereichs, Profilnamen mit `../`, Speichern/Laden/Löschen eines
  Profils und die einmalige Übernahme der alten Datei.
* **`tools/qml_smoketest.py`** schaltet jetzt auch auf den Tab „Diagnose" und
  spielt dort einen Profil-Rundlauf durch (speichern → verstellen → laden →
  löschen). Der Tab war bis dahin der einzige, den der Smoketest nie
  aufgebaut hat — eine SwipeView erzeugt nicht besuchte Seiten gar nicht
  erst. Außerdem schreibt der Lauf seine Einstellungen jetzt in ein
  Wegwerf-Verzeichnis — wie schon bei `runtime_config/`. Vorher hat er die
  Schriftgröße des Geräts, auf dem er lief, dauerhaft auf 1.0 gezogen.

### Ein Tippfehler kostet höchstens ein Feld

`settings.json` ist von Hand editierbar, also gilt dieselbe Regel wie für
`controller_config.json`: fehlt ein Schlüssel oder steht Unsinn darin
(`"dark": "ja"`, eine Farbe ohne `#`, ein Bereich mit `max <= min`), gilt für
genau dieses Feld der Standardwert, es gibt eine Zeile im Log, und die
Oberfläche startet normal. Unbekannte Schlüssel bleiben erhalten, statt beim
nächsten Speichern still zu verschwinden. Werte außerhalb ihres eigenen
Bereichs werden hineingelegt — sonst zeigte ein Regler nach einer
Handkorrektur auf etwas, wohin er nie wieder zurückkäme.

Geschrieben wird atomar (`.tmp` + `os.replace`) wie bei `runtime_config.py`,
und angelegt wird die Datei ausdrücklich in `main_qml.main()` statt beim
Import: `config.py` wird auch in den Empfängerprozessen importiert, beim
ersten Start hätten sonst vier Prozesse gleichzeitig dieselbe Datei erzeugt.

---

## 2.4 — Kein einzelner kaputter Wert legt mehr etwas Ganzes lahm

Vier der fünf Funde dieser Runde sind dieselbe Sorte Fehler: ein
ungeschütztes `int()`/`float()` auf Daten, die über UART und WLAN kommen
oder aus einer von Hand editierbaren Datei stammen. Je nachdem, wo es
passierte, kostete das die komplette Konfiguration eines Roboters oder
gleich die ganze Oberfläche.

### Behoben

* **Ein einziger unbrauchbarer Wert im Teensy-Deskriptor kostete die
  komplette Parameter-Konfiguration.** `runtime_config._convert_entries()`
  verspricht im eigenen Docstring, einen unplausiblen Eintrag zu
  überspringen. Bei `min`/`max` tat es das auch — bei `default` und `step`
  stand dort ein ungeschütztes `float()`. Ein `"def": null` aus einer halb
  übertragenen Firmware warf damit bis in `_persist_registry` hoch; gefangen
  wurde es dort zwar, aber die Konfiguration des Roboters war weg und die
  GUI lief wortlos mit der Vorlage aus dem Repository weiter — also mit
  falschen Namen, Bereichen und Gruppen an den Reglern. Gleiches galt für
  einen unlesbaren Joystick-Bereich; der verwirft jetzt nur noch diesen
  einen Joystick.
* **„Teensy übernehmen" im Overlay-Editor konnte die Oberfläche beenden.**
  Die Overlay-Werte kommen über UART/WLAN und teilweise aus einem frei
  geschriebenen `extra`-String (`field_x_cm=…;body1_channel_x=…`).
  `channel_registry._teensy_overlay_to_entry()` rechnete sie ungeschützt um.
  Im Poll-Timer blieb davon nur ein Logeintrag übrig — die Anordnung des
  Teensy kam dann nie an, ohne erkennbaren Grund. Im Slot
  `applyPendingTeensyConfig` macht PyQt aus derselben Ausnahme dagegen ein
  `abort()`. Jedes Zahlenfeld fällt jetzt auf seinen Standardwert zurück.
* **Die Trigger-Marke im Plotter war unsichtbar.** `visible_markers()`
  rechnete gegen `self._total`, den Index des *nächsten* Samples; sichtbar
  sind aber die Samples bis `_total - 1`. Eine gerade gesetzte Marke landete
  damit auf Position `count/(count-1) > 1`, also rechts neben der
  Zeichenfläche. Dazu kam ein zweiter Fehler: die Trigger-Marke trug den
  Index nach dem ganzen Block statt die Auslösestelle — sie hätte, sichtbar,
  bis zu fünf Samples zu weit rechts gestanden. `add_marker()` nimmt die
  Stelle jetzt als Argument.
* **Der Overlay-Editor meldete Mängel, die keine waren.** Ein *optionaler*
  Kanal, der schlicht nicht gesetzt ist — ein Körper der Feldansicht braucht
  weder Winkel noch Durchmesser — lief in `problems()` auf `int(None)` und
  erschien als „keine gültige Kanalnummer". Ein tadelloser Eintrag hatte so
  vier Beanstandungen in der Liste. `summary()` und `problems()` laufen
  außerdem in `pyqtProperty`-Gettern: mit Text an einer Zahlenstelle warfen
  sie dort, mit demselben `abort()` als Folge.
* **Die Feldansicht stand in der Editor-Liste als `180x240 cm`**, während die
  Ansicht daneben 240 × 180 zeichnete — in `overlay_schema.summary()` waren
  die Rückfallwerte für x und y vertauscht. Die Erkennung des Altformats
  (`field_width`/`field_height`) läuft jetzt genau wie in
  `visuals_bridge._graphic_to_entry()` über den ganzen Eintrag statt je Achse.
* **Ein Tippfehler in `controller_config.json` verhinderte den Start der
  gesamten Oberfläche.** Die Datei ist ausdrücklich dafür da, eine abweichende
  SDL-Belegung „ohne Code zu ändern" anzupassen — ihr Inhalt wurde aber
  ungeprüft ins Mapping übernommen. `float(self._map["deadzone"])` im
  Konstruktor riss dann den Aufbau ControllerBridge → ParamBridge → AppBridge
  mit, und die GUI startete gar nicht mehr, mit einem rohen Traceback. Jetzt
  werden die Typen geprüft: ein unbrauchbares Feld behält seinen
  Standardwert (mit Warnung im Log), eine Achsennummer als Zeichenkette wird
  übernommen statt ignoriert, und eine Totzone außerhalb 0…0,9 wird
  verworfen — bei ≥ 1,0 teilte `_apply_deadzone()` zusätzlich durch null.
* **`tools/desc_json_check.py` ließ sich mit dem eigens empfohlenen
  Ersatz-Compiler nicht übersetzen.** Der Dateikopf nennt
  `CXX="python -m ziglang c++"` für Rechner ohne `g++`; zig macht aus
  `__DATE__`/`__TIME__` per Default einen **Fehler** (`-Wdate-time`). Die
  Makros sind der Build-Stempel, den der Deskriptor als `"build"` meldet und
  gehören dorthin — die Warnung wird jetzt abgeschaltet, g++ und clang++
  ignorieren die Option.

### Geändert

* **Selbsttest**: 151 → 179 Prüfungen. Neuer Abschnitt 15 (Plotter-Marken
  und Controller-Mapping, wird ohne PyQt6/numpy sauber übersprungen), dazu
  Regressionsprüfungen in den Abschnitten 6, 11 und 13. Jede davon schlägt
  ohne den zugehörigen Fix fehl — nachgeprüft, nicht nur behauptet.

---

## 2.3 — Spielfeld richtig herum, ehrlicher Paketzähler, Altlasten weg

### Behoben

* **Das Spielfeld war um 90° gedreht und tausendmal zu groß.** Zwei Fehler
  in derselben Umrechnung:
  1. `field_width`/`field_height` wurden als **Meter** gelesen und mit 100
     multipliziert. Die vorhandene Konfiguration sagt `240 × 180`, gemeint in
     Zentimetern — daraus wurde ein **240 × 180 Meter** großes Feld. Ein
     45-cm-Tor nahm darin 0,25 % einer Kante ein, der Mittelkreis war ein
     Punkt, und die Rasterlinien alle 30 cm verschmolzen zu einer Fläche.
     Deshalb wirkte an der Feldansicht scheinbar keine Änderung.
  2. Die Achsen waren vertauscht: gezeichnet wurde y waagerecht und x
     senkrecht. Die frühere Widgets-Oberfläche zeichnete **x nach rechts,
     y nach oben**, und alle Konfigurationen und Hintergrundbilder passen
     dazu. Genau so wird jetzt wieder gezeichnet.
* **Das Hintergrundbild der Feldansicht ist wieder an.** Es ist eine
  Aufnahme des Spielfeldes und passt — mit den korrigierten Maßen jetzt auch
  pixelgenau. Abschaltbar; dann zeichnet die GUI Tore, Mittellinie und
  Mittelkreis selbst. Mit Bild werden sie **nicht** gezeichnet, sonst lägen
  sie doppelt und versetzt über einem Foto, das sie schon zeigt.
* **Die Parameter-Statuszeile zählte gesendete Pakete hoch, auch ohne Node.**
  Ein UDP-`sendto()` an eine unerreichbare Gegenstelle gelingt lokal immer —
  gezählt wurde also „an den Socket übergeben" und gelesen als „angekommen".
  Ohne Verbindung steht dort jetzt eine Warnung in Bernstein statt einer
  grünen Erfolgsmeldung; die Zähler starten bei jedem Verbindungsaufbau neu.
* **`starter.bat`** enthielt mitten in einer Zeile ein verirrtes
  Carriage-Return-Byte (`..\..<CR>equirements.txt`). Die Fehlermeldung
  überschrieb sich dadurch selbst und nannte einen Pfad, den es nicht gibt.

* **Die GUI stürzte beim Beenden ab — auf dem Raspberry Pi, nicht hier.**
  `FastControlWorker` (Ableitung von `threading.Thread`) hatte ein Attribut
  `self._stop`. In Python bis einschließlich 3.12 ist `_stop` eine **interne
  Methode** von `threading.Thread`, die `join()` aufruft, sobald der Thread
  beendet ist. Das Attribut überdeckte sie, und `join()` lief in
  `TypeError: 'Event' object is not callable`. Der Absturz riss den
  Interpreter mit: QML baute anschließend auf eine halb abgeräumte Brücke ab,
  was vierzig Folgemeldungen und am Ende ein `SIGABRT` ergab.

  Auf dem Entwicklungsrechner fiel es nicht auf, weil Python 3.14 diese
  Methode nicht mehr hat. Der RPi läuft mit 3.11 — dort war der Fehler live.
  Der Selbsttest prüft jetzt **versionsunabhängig**, dass keine
  Thread-Ableitung ein Interna von `threading.Thread` überdeckt: die Liste
  der betroffenen Namen ist fest hinterlegt, ein Test gegen die eigene
  Laufzeit hätte auf 3.14 nichts gefunden.
* **`PlotCanvas.setPlotBridge`** greift beim Abbau nicht mehr auf eine bereits
  gelöschte Brücke zu. PyQt macht aus dem `RuntimeError` in einem Slot ein
  `abort()`.

* **`tools/desc_json_check.py` prüfte nie die echte `channel_config.h`.** Der
  Übersetzungsaufruf band `"-I tools/hostsim -I teensy_firmware/src"` ein, mit
  dem Kommentar „hostsim MUSS vor src stehen" — das stimmt bei
  spitzen Klammern, aber `PDS.cpp` bindet `channel_config.h` in
  **Anführungszeichen** ein, und dafür sucht der Präprozessor zuerst im
  Verzeichnis der einbindenden Datei selbst. Gewonnen hat also immer
  `teensy_firmware/src/channel_config.h` — die ausgelieferte Vorlage, in der
  jeder Eintrag auskommentiert ist. Der Deskriptor kam leer heraus, und
  vierzehn Einzelprüfungen schlugen fehl, obwohl es ein einziges Problem war.
  Jetzt kopiert das Skript alle Quellen in ein temporäres Verzeichnis, und
  eine neue Prüfung stellt fest, ob überhaupt die Testkonfiguration benutzt
  wurde — mit der Vorlage meldet sie das jetzt direkt statt vierzehn
  Folgefehlern.

  Zweiter Fund an derselben Stelle: `subprocess` las die Ausgabe in der
  Locale-Kodierung (`text=True`). Der Deskriptor ist UTF-8; unter Windows
  (cp1252) wurde daraus Zeichensalat, den der Test als Escaping-Fehler
  meldete, der keiner war. Jetzt ausdrücklich `encoding="utf-8"`.

  `desc_json_check.py` beachtet jetzt außerdem **`CXX`**. Ohne das ließ sich
  der Test auf einem Rechner ohne `g++` gar nicht ausführen — mit
  `pip install ziglang` und `CXX="python -m ziglang c++"` läuft er auch unter
  Windows.
* **Das Raster der Feldansicht war über dem Hintergrundbild unsichtbar** —
  blasses Blau auf gedämpftem Rasengrün. Über einem Bild jetzt weiß und
  kräftiger, die Abdunklung des Bildes dafür schwächer.
* **Der Smoketest prüfte Plotter und Systemansicht, ohne vorher dorthin zu
  wechseln.** Baut ein `SwipeView` (abhängig von Qt-Version und Puffergröße)
  nicht alle Seiten im Voraus auf, meldete die Prüfung „OverlayEditor: 0
  Instanzen", obwohl an der Oberfläche nichts falsch war. Der Test schaltet
  jetzt um, bevor er den jeweiligen Tab anfasst — das bildet zugleich ab, was
  ein Bediener tatsächlich tut.
* Die Layout-Prüfung des Smoketests („kein Positionierer flacher als sein
  höchstes Kind") arbeitet jetzt mit 8 Pixeln Toleranz — Schriftmetriken
  unterscheiden sich zwischen CI und Entwicklungsrechner, und ein, zwei Pixel
  Überstand sind normal. Der 16-Pixel-Fund, um den es ursprünglich ging, wird
  weiterhin erkannt.
* **CI**: `fonts-dejavu-core` ergänzt. Ohne eine einzige installierte
  Schriftart meldet Qt beim Aufbau jedes Textelements eine Warnung, die der
  Smoketest als Fehler wertet.

### Entfernt

* **Die alte PyQt6-Widgets-GUI** (`main.py` + `gui/`, 3748 Zeilen). Sie wurde
  von keinem Setup-Skript installiert, brauchte mit `pyqtgraph` eine
  zusätzliche Abhängigkeit und kannte weder PS4-Controller noch automatische
  Kanalnamen noch die Überwachung der Empfängerprozesse. Alle Verweise in
  README, Setup-Skript, CI und Doku sind nachgezogen.

  `pc_flash_tool/bt_flash_protocol.py` bleibt dagegen als bewusste Kopie von
  `shared/bt_flash_protocol.py` liegen: das Verzeichnis soll sich allein auf
  einen anderen PC kopieren lassen. Damit die beiden nicht stillschweigend
  auseinanderlaufen, prüft der Selbsttest sie jetzt Byte für Byte.

---

## 2.2 — Editor für die Systemansicht

Wire-Format unverändert (2). Die Teensy-Firmware muss **nicht** neu geflasht
werden.

### Neu

* **Editor in Tab 3.** „✎ Bearbeiten" macht die Textfelder im Bild ziehbar
  und blendet rechts ein Bedienfeld ein: Element anlegen (Text, Textraster,
  Zeiger, Drehanzeige, Vektor, Tabelle, Feldansicht), Formular je Element,
  Reihenfolge, Kopie, Löschen, Rückgängig über 50 Schritte, Gruppen anlegen,
  umbenennen und Hintergrundbild wählen.
* **Ein Textraster wird als Block gezogen.** Gezogen wird irgendeine Zelle,
  verschoben wird die linke obere Ecke des Blocks — und gespeichert bleibt es
  **ein** Eintrag.
* **Kanalauswahl mit Suche** über Nummer und Name, statt einer ComboBox mit
  200 Zeilen.
* **Warnhinweise** für Kanäle, die es nicht gibt, für Minimum ≥ Maximum und
  für leere Kanallisten. Sie sperren nichts — beim Umbauen der Firmware wäre
  ein Editor, der das Speichern verweigert, nur im Weg.
* **Rückfrage statt stillschweigendem Überschreiben:** wurde die Anordnung
  von Hand bearbeitet, ersetzt eine neue Firmware sie nicht mehr einfach.
  Es erscheint „Teensy übernehmen" / „Eigene behalten".
* Gespeichert wird je Node unter `runtime_config/nodeN/` und damit
  neustartfest.

### Spielfeld

* **Kein Gruppenbild mehr hinter dem Platz.** Die Feldansicht legte bisher
  das Bild der Gruppe — in aller Regel eine Platinenaufnahme — hinter das
  Spielfeld. Jetzt standardmäßig aus und im Editor einschaltbar.
* **Tore, Mittellinie, Mittelkreis und Anstoßpunkt** werden gezeichnet. Die
  Tore liegen an den Enden der langen Achse, quer dazu mittig, und sind als
  Nische nach innen gezeichnet. Toröffnung und Tortiefe sind einstellbar.
* Das Raster ist deutlich dezenter, der Platz hat eine gedämpfte Rasenfarbe.
* **Beschriftung `240 × 180 cm`** statt `180 × 240 cm` — in der Reihenfolge,
  in der man das Feld sieht (waagerecht × senkrecht).

### Entfernt

* **Der Stopp-Knopf in der Kopfzeile** ist auf Wunsch weg. Der Not-Aus liegt
  weiterhin auf der Leertaste.

### Behoben

* **Der Trigger-Kasten im Plotter fiel beim Einschalten zusammen** — von 192
  auf 16 Pixel, Schwelle, Modus und Nachlauf waren damit nicht mehr
  erreichbar. Zwei Fehler übereinander: eine Bindungsschleife zwischen der
  Höhe des Kastens und der seiner `Flow` (`anchors.fill` statt nur der
  Breite), und ein direktes Kind der `Flow` mit Ankern — dazu meldet Qt
  „Flow will not function" und ordnet danach gar nichts mehr an.
* **In der Parameter-Leiste ragten die Knöpfe aus ihrer Zeile heraus** und
  überlappten die Zeile darunter: `anchors.margins` liess der Zeile von 56
  Pixeln nur 40, während AppButton und AppSwitch 56 Pixel hoch sind.
* **Die Firmware-Version enthielt wörtlich `__DATE____TIME__`.**
  `-DBUILD_DATE=\"__DATE__\"` definiert die Zeichenkette `"__DATE__"` — der
  Präprozessor ersetzt Makros nicht innerhalb eines String-Literals.
  Zusätzlich war `_fwVersion[24]` zu klein für den zusammengesetzten Text
  und schnitt ihn nach `v0.0.1(Build vom Aug 22` ab; jetzt 48 Byte.
* **`tools/build_teensy_check.sh`** kannte die `-D`-Flags aus
  `platformio.ini` nicht und meldete einen Fehler in `main.cpp`, der keiner
  war. Es liest sie jetzt aus der `platformio.ini`, damit beide nicht mehr
  auseinanderlaufen können.
* **`tools/selftest.py`** liess die CI-Stufe `pyflakes` rot laufen: ein
  `import serial`, der nur die Frage „ist pyserial da?" beantwortete und
  einen ungenutzten Namen band. `# noqa` kennt pyflakes nicht — jetzt über
  `importlib.util.find_spec()`.
* **Kanäle ohne Daten zeigten in der Kanaltabelle keine Min/Max/Δ-Werte.**
  Das Modell liefert dafür `None`, was in QML als `undefined` ankommt — die
  Abfrage prüfte aber auf `null`. `undefined !== null` ist wahr, also lief
  `.toFixed()` auf `undefined`, und die drei Spalten blieben leer statt „—"
  anzuzeigen. Betraf jeden Kanal, den der Teensy nicht sendet.

### Prüfung

* `tools/qml_smoketest.py` spielt den Editor jetzt wirklich durch: alle
  sieben Element-Arten anlegen, im Bild ziehen, Formularfelder aller Typen
  setzen, Gruppen, Speichern und Verwerfen, Teensy-Rückfrage — 47 Schritte.
  Zusätzlich wird **nachgewiesen, dass der Editor überhaupt gezeichnet
  wurde**, und die **gespeicherte Datei nachgelesen**. Ohne diese beiden
  Prüfungen hätte der Test leer grün gemeldet.
* `tools/check_qml_bindings.py` reicht Brücken-Typen jetzt über die
  Verwendungsstelle in eigene Komponenten hinein: steht in `SystemView.qml`
  `OverlayEditor { visuals: root.visuals }`, gilt `visuals` auch in
  `OverlayEditor.qml` als `VisualsBridge`. Vorher blieb dort jeder Tippfehler
  ungeprüft, weil die Komponente selbst nur `property var visuals: null`
  deklariert.
* `tools/selftest.py`: 98 → 148 Prüfungen (Feldschema, Typumwandlung,
  Positionsgrenzen, Konfliktregel Teensy ↔ Handarbeit).
* Der Smoketest umschließt das **Herunterfahren** und meldet einen Fehler
  dort als Befund, statt daran zu sterben — genau dort saß der Absturz oben,
  und aus einer klaren Ursache wurden vierzig Folgemeldungen.
* `tools/desc_json_check.py` beachtet **CXX**. Ohne das ließ sich der
  Deskriptor-Test auf einem Rechner ohne `g++` gar nicht ausführen, und er
  lief erst in der CI zum ersten Mal — wo sich dann zeigte, dass er nie
  geprüft hatte, was er zu prüfen vorgibt (siehe oben). Mit
  `pip install ziglang` und `CXX="python -m ziglang c++"` läuft er auch unter
  Windows.
* Der Smoketest erzwingt jetzt eine **Layout-Runde** und prüft danach eine
  echte Invariante: *kein Positionierer darf flacher sein als sein höchstes
  Kind.* Offscreen rechnet Qt sonst gar kein Layout, und genau deshalb blieb
  der zusammenklappende Trigger-Kasten unbemerkt, obwohl der Test ihn
  angefasst hat. Bewusst keine Mindesthöhe in Pixeln — die Kurvenlegende des
  Plotters ist völlig zu Recht nur 13 Pixel hoch.

---

## 2.1 — Ereignisse, Diagnose und Konfiguration vom Teensy

**Wire-Format 1 → 2.** Teensy, Node und GUI müssen zusammen aktualisiert
werden. Der Node nimmt das alte 4-Byte-Discovery-Paket weiterhin an (dann
ohne Round-Trip-Messung), sonst gibt es keine Rückwärtskompatibilität.

### Teensy-Bibliothek

* **`PDS.bind("Name", &wert, 12)`** — feste Kanalnummer mit dem Namen zuerst,
  optional mit Einheit als viertem Argument.
* **`PDS.event("Ball verloren")`** setzt eine senkrechte Marke in den Plotter,
  **`PDS.log/logf/warn/error(...)`** schreiben ins Logbuch der GUI. Beides
  nicht blockierend, höchstens 20 Meldungen pro Sekunde.
* **Einheiten je Kanal**: `PDS.plot("Akku", v, "V")`, `PDS.setUnit(...)`.
  Erscheinen in Kanaltabelle und Plotter-Legende.
* **Watchdog**: `PDS.enableWatchdog(2000)`. `update()` füttert ihn selbst;
  bleibt `loop()` hängen, startet der Teensy neu und meldet das beim nächsten
  Start als Fehler ins Logbuch.
* **Parameter-Rückmeldung** (2 Hz): der Teensy schickt zurück, welche
  Parameter er wirklich hält. Die GUI zeigt Abweichungen an — der Downlink
  war bis hierher fire-and-forget.
* **Firmware-Version** im Deskriptor (`PDS.setFirmwareVersion`).
* `channel_config.h` beschreibt Parameter jetzt **vollständig** (`ParamDef`:
  Name, Bedienelement, Bereich, Schrittweite, Gruppe) statt nur über
  Namensarrays. Die Strukturen liegen in `params.h`, damit der
  `__has_include`-Fallback dieselben Definitionen benutzt.
* Deskriptor-Puffer 12 → 24 kB, ein Chunk je 20 ms statt 10 ms.

**Behoben:** `bind()`/`track()` liefen auf den Festbreiten-Aliasen
`int8_t`/`int16_t`/`int32_t`. Auf dem Teensy ist `int32_t` aber `long` — ein
ganz gewöhnliches `int heading; PDS.track("Heading", &heading);` hat deshalb
gar nicht übersetzt, sondern eine seitenlange Kandidatenliste erzeugt. Die
Überladungen laufen jetzt auf den fundamentalen Typen; ein
`static_assert`-Auffangnetz gibt für alles andere eine lesbare Meldung.

**Behoben:** Deskriptor, Ereignisse und Rückmeldung schreiben nur noch, wenn
im TX-Puffer zusätzlich ein komplettes Telemetriepaket Platz hat. Vorher
konnte eine Deskriptor-Übertragung einzelne Telemetriepakete verdrängen.

### Fernsteuerung

**Behoben — „die Joystick-Abfrage stockt":** Der 100-Hz-Takt der
Fernsteuerung lief im Qt-GUI-Thread. Ein `QTimer` feuert aber erst, wenn die
Ereignisschleife wieder drankommt — also nach dem Neuzeichnen von Plotter,
Tabelle und Oberfläche. Der Abtastzeitpunkt des Controllers ist dadurch
unregelmäßig gewandert. Die komplette Regelstrecke (Controller lesen,
Tastatur, Paket packen, senden, Discovery) läuft jetzt in einem **eigenen
Thread** mit fester Periode; der Wertespeicher ist mit einem Lock
abgesichert, das nie über ein `sendto()` gehalten wird. pygame/SDL wird in
demselben Thread auf- und abgebaut.

Zusätzlich: `pygame.joystick.get_count()` nur noch 2× statt 100× pro Sekunde,
und das doppelte Pumpen der SDL-Ereigniswarteschlange entfällt.

* **Tastatursteuerung**: WASD fahren, Q/E drehen, Shift schneller, R/F
  Dribbler, Leertaste Not-Aus. Ein Controller hat weiterhin Vorrang.
* **Not-Aus-Knopf** in der Kopfzeile.

### Plotter

* **Bis zu acht Kurven gleichzeitig** mit Legende, Min/Max/Aktuell je Kurve
  und wahlweise gemeinsamer oder eigener Skala je Kurve.
* **Oszilloskop-Trigger** mit sechs Bedingungen (über/unter Schwelle,
  steigende/fallende Flanke, Sprung größer als, Band verlassen), einstellbarem
  Nachlauf und „neu scharf machen".
* **Ereignismarken** vom Teensy als senkrechte Linien im Verlauf.
* Komplett auf **NumPy** umgestellt: ein vorab angelegter 2D-Ringpuffer
  (Kurven × Samples, `float32`), blockweises Schreiben, vektorisierte
  Trigger-Auswertung und Koordinatenumrechnung. Kein `deque`, keine
  Python-Schleife über Einzelwerte mehr — der Plotter teilt sich den Thread
  mit dem Renderer, jede Schleife dort kostet Bildrate.

### Diagnose (neuer Tab)

* **Verbindungsqualität**: Pakete/s, geschätzter Paketverlust (aus den
  Zeitstempeln des Teensy, ohne ein Byte Wire-Format zu kosten) und echte
  Round-Trip-Zeit GUI → Node → GUI.
* **Node-Systemstatus**: CPU-Temperatur, Last, Speicher, WLAN-Pegel, Uptime
  und UART-Zähler des Raspberry Pi Zero.
* **Akku-Warnung**: frei wählbarer Kanal, zwei Schwellen und eine Haltezeit
  gegen Fehlalarme beim Anfahren. Rein optisch — es wird nichts am Roboter
  verändert.
* **Logbuch** mit Filter nach Meldungsstufe.
* **Einstellungen**: helles/dunkles Farbschema, Schriftgröße, Kiosk-Modus,
  Tastatursteuerung, Übernahme der Teensy-Konfiguration.

### Konfiguration vom Teensy, reboot-fest

Der Teensy ist die Quelle der Wahrheit für Kanalnamen, Einheiten, den Aufbau
des Parameter-Tabs und die Overlays der Systemansicht. Was im Deskriptor
ankommt, wird **je Node** unter `rpi5_monitor/64Bit_Version/runtime_config/`
dauerhaft abgelegt — nach einem Neustart steht sofort wieder alles da, auch
ohne eingeschalteten Roboter.

Konflikt zwischen Teensy-Konfiguration und lokaler Bearbeitung: ein
Fingerabdruck entscheidet. Neue Firmware setzt sich durch, sonst bleiben
lokale Änderungen stehen. Die Dateien im Repository bleiben unberührte
Vorlagen.

### Systemansicht

* **Neuer Overlay-Typ `textgrid`**: ein einziger Eintrag legt beliebig viele
  Werte als Raster auf ein Bild (`channels=0-11,20;cols=2;dx=24;dy=5`).
  Vorher brauchte jeder Messwert ein eigenes Overlay mit eigener Position.
* **Feldansicht auf Zentimeter und die tatsächliche Ausrichtung umgestellt**:
  x = 0…180 cm nach Osten, y = 0…240 cm nach Norden; dargestellt um 90° nach
  Osten gedreht (Norden rechts, Osten unten), passend zum Querformat-Display.
  Ein Kompasskurs entspricht in dieser Darstellung direkt der
  Bildschirmdrehung. Achsen sind beschriftet.

### Parameter-Tab

* **Suchfeld** über alle Gruppen hinweg.
* **Abweichungen** vom gespeicherten Default auf einen Blick, mit
  „alle zurücksetzen".
* **Rückgängig** (auch Strg+Z); Änderungen am selben Regler innerhalb von
  1,5 s werden zu einem Schritt zusammengefasst.
* **Soll/Ist-Vergleich** gegen die Rückmeldung des Teensy.

### Node

* **Aux-Uplink** (Port 5021/5022): Ereignisse, Parameter-Rückmeldung und
  Node-Status teilen sich einen Port; die GUI trennt sie am Magic.
* Generischer `MagicFrameAssembler` für alle Uplink-Formate mit variabler
  und fester Länge, inklusive Plausibilitätsprüfung gegen Zufallstreffer im
  Telemetriestrom.
* Discovery trägt jetzt Nummer und Sendezeitpunkt und wird zurückgespiegelt.

### Prüfwerkzeuge

* **`tools/desc_json_check.py`** übersetzt `PDS.cpp` mit einer
  Arduino-Attrappe für den PC, **führt sie aus** und prüft den erzeugten
  Deskriptor mit einem echten JSON-Parser — inklusive Anführungszeichen,
  Backslash, Umlauten und Steuerzeichen in Namen. Ein Übersetzungslauf
  allein findet solche Fehler nicht.
* **`tools/qml_smoketest.py`** startet die komplette Oberfläche offscreen,
  füttert synthetische Daten hinein und wertet jede Qt-Warnung als Fehler.
* `tools/selftest.py` von 48 auf 98 Prüfungen erweitert.
* **GitHub Actions**: alle Prüfungen plus PlatformIO-Build bei jedem Push.

---

## 2.0 — Teensy-Bibliothek ohne Kanalnummern

* `PDS` als fertige globale Instanz; `plot()`/`track()` vergeben Kanäle
  automatisch und melden die Namen an die GUI (O(1) über einen Pointer-Cache).
* `channel_config.h` ist optional (`__has_include`), die Bibliothek lässt sich
  unverändert in fremde Projekte kopieren (`library.json`).
* Kanalnamen finden sich nach einem Neustart auf **beiden** Seiten von allein
  wieder ein: Meldung beim Boot, bei jedem Verbindungsaufbau und in Ruhe mit
  wachsendem Abstand; die GUI erkennt am `micros()`-Sprung einen Neustart.
* Discovery-Paket an **beide** Nodes — der inaktive Node hat vorher dauerhaft
  80 kB/s gebroadcastet und damit die Fernsteuerung des aktiven ausgebremst.
* Behoben: `pinMode(10, INPUT)` in `init()` griff auf einen fremden Pin des
  Roboterprojekts zu.
* Behoben: Dummy-Filterung im Empfänger verschob alle folgenden Kanäle.
* Behoben: unbehandelte Ausnahme in einem Qt-Slot beendete die GUI
  (`qFatal()`) — jetzt `safe_slot`.
* Behoben: Teensy ging **vor** der Übertragung in den Bootloader; ein
  abgebrochener Flash-Vorgang hinterließ einen Roboter ohne Firmware.
* Behoben: Status-LEDs des Nodes waren vollständig auskommentiert.
* `tools/selftest.py`, `tools/check_wire_format.py`,
  `tools/check_qml_bindings.py` und `tools/build_teensy_check.sh` eingeführt.
