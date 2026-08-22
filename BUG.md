# Gemeldete Fehler — Stand: alle behoben

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
