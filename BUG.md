# Gemeldete Fehler — Stand: alle behoben

## Runde 4

- [x] **Ein einziger unbrauchbarer Wert im Teensy-Deskriptor kostete die
  KOMPLETTE Parameter-Konfiguration.** `runtime_config._convert_entries()`
  verspricht im eigenen Docstring, einen unplausiblen Eintrag zu
  überspringen — bei `min`/`max` tat es das auch, bei `default` und `step`
  aber nicht: dort stand ein ungeschütztes `float()`. Ein `"def": null` aus
  einer halb übertragenen Firmware warf damit bis in `_persist_registry`
  hoch. Gefangen wurde es dort zwar, aber die ganze Konfiguration war weg
  und die GUI lief still mit der Vorlage aus dem Repository weiter — mit
  falschen Namen, Bereichen und Gruppen an den Reglern. Dasselbe galt für
  einen unlesbaren Joystick-Bereich.
- [x] **„Teensy übernehmen" im Overlay-Editor konnte die GUI beenden.** Die
  Overlay-Werte kommen über UART/WLAN und teilweise aus einem frei
  geschriebenen `extra`-String; `channel_registry._teensy_overlay_to_entry()`
  rechnete sie mit ungeschütztem `int()`/`float()` um. Im Poll-Timer war das
  nur ein Logeintrag (die Anordnung des Teensy kam dann nie an), im Slot
  `applyPendingTeensyConfig` dagegen macht PyQt aus einer Ausnahme ein
  `abort()`. Alle Zahlenfelder fallen jetzt auf ihren Standardwert zurück.
- [x] **Die Trigger-Marke im Plotter war unsichtbar.** `visible_markers()`
  rechnete gegen `self._total` — den Index des NÄCHSTEN Samples. Eine gerade
  gesetzte Marke kam damit auf Position `count/(count-1) > 1` heraus und
  wurde rechts neben die Zeichenfläche gemalt. Zusätzlich trug die
  Trigger-Marke den Blockindex statt der Auslösestelle: sie hätte, sichtbar,
  bis zu fünf Samples zu weit rechts gestanden.
- [x] **Der Overlay-Editor meldete Mängel, die keine waren.** Ein optionaler
  Kanal, der schlicht nicht gesetzt ist (ein Körper der Feldansicht braucht
  weder Winkel noch Durchmesser), lief in `problems()` auf `int(None)` und
  wurde als „keine gültige Kanalnummer" gezählt. `summary()` und
  `problems()` laufen in `pyqtProperty`-Gettern — mit Text an einer
  Zahlenstelle warfen sie dort ebenfalls, mit demselben `abort()` als Folge.
- [x] **Die Feldansicht stand in der Editor-Liste als `180x240 cm`**, während
  die Ansicht daneben 240 × 180 zeichnete: in `overlay_schema.summary()`
  waren die Rückfallwerte für x und y vertauscht.
- [x] **Ein Tippfehler in `controller_config.json` verhinderte den Start der
  gesamten Oberfläche.** Die Datei ist ausdrücklich zum Bearbeiten von Hand
  gedacht, ihr Inhalt wurde aber ungeprüft übernommen; `float(map["deadzone"])`
  im Konstruktor von `ControllerBridge` riss dann den Aufbau
  ControllerBridge → ParamBridge → AppBridge mit. Jetzt werden die Typen
  geprüft, unbrauchbare Felder behalten ihren Standardwert, und eine
  Totzone außerhalb 0…0,9 wird verworfen (bei ≥ 1,0 teilte
  `_apply_deadzone()` zusätzlich durch null).
- [x] **`tools/desc_json_check.py` ließ sich mit dem eigens empfohlenen
  Ersatz-Compiler nicht ausführen.** Der Dateikopf nennt
  `CXX="python -m ziglang c++"` für Rechner ohne `g++` — zig macht aus
  `__DATE__`/`__TIME__` per Default einen Fehler (`-Wdate-time`). Die
  Makros sind der Build-Stempel der Firmware und sollen dort stehen; die
  Warnung wird jetzt abgeschaltet (g++/clang++ ignorieren die Option).

## Runde 3

- [x] **Die GUI stürzte beim Beenden ab — nur auf dem Raspberry Pi, nicht auf
  dem Entwicklungsrechner.** `FastControlWorker` (Ableitung von
  `threading.Thread`) hatte ein Attribut `self._stop`. Bis einschließlich
  Python 3.12 ist `_stop` eine **interne Methode** von `threading.Thread`, die
  `join()` beim Threadende aufruft; das Attribut überdeckte sie, und `join()`
  lief in `TypeError: 'Event' object is not callable`. Der Absturz riss den
  Interpreter mit — QML baute anschließend auf eine halb abgeräumte Brücke
  ab, was vierzig Folgemeldungen und am Ende ein `SIGABRT` ergab.
  Auf dem Entwicklungsrechner (Python 3.14) fiel es nicht auf, weil diese
  Methode dort nicht mehr existiert; der Pi läuft mit 3.11. Der Selbsttest
  prüft jetzt versionsunabhängig, dass keine Thread-Ableitung ein Interna von
  `threading.Thread` überdeckt.
- [x] **`tools/desc_json_check.py` prüfte nie die echte `channel_config.h`,
  sondern immer die leere Vorlage.** Ein Include in Anführungszeichen sucht
  zuerst im Verzeichnis der einbindenden Datei — dort lag immer die
  auskommentierte Vorlage aus `teensy_firmware/src/`, unabhängig von der
  `-I`-Reihenfolge. Der CI-Job schlug deshalb zu Recht fehl. Behoben, indem
  alle Quellen vor dem Test in ein temporäres Verzeichnis kopiert werden;
  eine neue Prüfung stellt zusätzlich fest, ob überhaupt die Testkonfiguration
  benutzt wurde.
- [x] **Smoketest prüfte Plotter/Systemansicht ohne vorher hinzuschalten** —
  funktionierte nur zufällig, je nachdem wie viele Tabs der `SwipeView` im
  Voraus aufbaut. Der Test schaltet jetzt um, bevor er einen Tab anfasst.

## Runde 2

- [x] **Spielfeld: Änderungen wirkten nicht, Bild fehlte, falsche Drehung.**
  Ursache war eine Umrechnung, nicht die Zeichnung: `field_width: 240,
  field_height: 180` wurde als **Meter** gelesen und mit 100 multipliziert —
  daraus wurde ein **240 × 180 Meter** großes Feld. Ein 45-cm-Tor nahm darin
  0,25 % einer Kante ein, der Mittelkreis war ein Punkt, und die Rasterlinien
  alle 30 cm ergaben 800 Striche, also eine Fläche. Deshalb sah man von den
  Markierungen nichts.
  Dazu waren die Achsen vertauscht. Gezeichnet wird jetzt wieder **x nach
  rechts, y nach oben** — so wie es die frühere Widgets-Oberfläche tat und
  wie alle Konfigurationen und Hintergrundbilder es erwarten.
  Das Hintergrundbild ist wieder an und passt mit den korrigierten Maßen
  pixelgenau (Bild4: 4913 × 3685 = 4:3, Feld 240 × 180 cm = 4:3). Eigene
  Markierungen werden nur gezeichnet, wenn **kein** Bild hinterlegt ist —
  sonst lägen sie doppelt über einem Foto, das sie schon zeigt.

- [x] **Parameter zählten gesendete Pakete hoch, obwohl kein Node verbunden
  war.** Ein UDP-`sendto()` an eine unerreichbare Gegenstelle gelingt lokal
  immer; gezählt wurde also „an den Socket übergeben" und gelesen als
  „angekommen". Ohne Verbindung steht dort jetzt eine Warnung in Bernstein
  statt einer grünen Erfolgsmeldung, und die Zähler beginnen bei jedem
  Verbindungsaufbau neu.

- [x] **Altlasten entfernt:** die alte PyQt6-Widgets-GUI (`main.py` + `gui/`,
  3748 Zeilen) samt aller Verweise in README, Setup-Skript, CI und Doku.
  `pc_flash_tool/bt_flash_protocol.py` bleibt bewusst als Kopie von
  `shared/bt_flash_protocol.py` liegen — das Verzeichnis soll allein auf
  einen anderen PC kopierbar sein. Der Selbsttest prüft die beiden jetzt
  Byte für Byte gegeneinander.

  Nebenbefund: `starter.bat` enthielt mitten in einer Zeile ein verirrtes
  Carriage-Return-Byte (`..\..<CR>equirements.txt`); die Fehlermeldung
  überschrieb sich dadurch selbst und nannte einen Pfad, den es nicht gibt.

## Runde 1

- [x] **Trigger im Plotter klappte beim Antippen zusammen**, die Werte waren
  nicht mehr erreichbar.
  Zwei Fehler übereinander in `qml/PlotterView.qml`:
  1. `Flow { anchors.fill: parent }` in einem Kasten, dessen Höhe aus
     `triggerRow.implicitHeight` kam → Bindungsschleife. Qt löst die auf,
     indem es eine Seite fallen lässt; der Kasten fiel beim Einschalten von
     192 auf 16 Pixel zusammen. Jetzt wird nur die **Breite** gebunden.
  2. Ein direktes Kind der `Flow` hatte `anchors.verticalCenter`. Qt meldet
     dazu „Cannot specify anchors for items inside Flow. Flow will not
     function." und ordnet danach gar nichts mehr an. Jetzt über
     `verticalAlignment`.

- [x] **Stopp-Knopf entfernt** (`qml/Main.qml`). Der Not-Aus liegt weiterhin
  auf der **Leertaste**.

- [x] **Beschriftung des Spielfelds** zeigt jetzt `240 × 180 cm` — in der
  Reihenfolge, in der man das Feld auch sieht (waagerecht × senkrecht).

- **Kanaltabelle:** Kanäle ohne Daten zeigten bei Min/Max/Δ gar nichts statt
  „—". Das Modell liefert dort `None`, in QML kommt das als `undefined` an —
  geprüft wurde aber auf `null`, und `undefined !== null` ist wahr.
- **Parameter-Leiste:** die Knöpfe (56 px) ragten aus der 40 px hohen Zeile
  heraus und überlappten die Zeile darunter.
- **Firmware-Version:** `-DBUILD_DATE=\"__DATE__\"` setzte das Makro nie ein —
  in der Firmware stand wörtlich `__DATE____TIME__`. Außerdem war der Puffer
  `_fwVersion[24]` zu klein für den zusammengesetzten Text.
- **`tools/build_teensy_check.sh`** kannte die `-D`-Flags aus
  `platformio.ini` nicht und meldete deshalb einen Fehler in `main.cpp`, der
  keiner war.
- **`tools/selftest.py`** ließ die CI-Stufe `pyflakes` rot laufen (ungenutzter
  `import serial`).
