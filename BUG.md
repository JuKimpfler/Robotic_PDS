# Gemeldete Fehler — Stand: alle behoben

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

- [x] **Spielfeld sah falsch aus.**
  Ursache war das Hintergrundbild: die Feldansicht legte das Gruppenbild —
  in aller Regel eine Platinenaufnahme — hinter den Platz. Das ist jetzt
  standardmäßig **aus** und über das Feld „Bild der Gruppe als Hintergrund"
  im Editor einschaltbar. Dazu gezeichnet: **Tore** an beiden Enden der
  langen Achse (mittig, als Nische in der Bande), **Mittellinie**,
  **Mittelkreis** und Anstoßpunkt; das Raster ist deutlich dezenter, der
  Platz hat eine gedämpfte Rasenfarbe. Toröffnung und Tortiefe sind im
  Editor einstellbar.

- [x] **Stopp-Knopf entfernt** (`qml/Main.qml`). Der Not-Aus liegt weiterhin
  auf der **Leertaste**.

- [x] **Beschriftung des Spielfelds** zeigt jetzt `240 × 180 cm` — in der
  Reihenfolge, in der man das Feld auch sieht (waagerecht × senkrecht). Die
  lange Achse (Nord) liegt im Querformat waagerecht.

## Nebenbefunde, beim Nachprüfen gefunden und mitbehoben

- **Kanaltabelle:** Kanäle ohne Daten zeigten bei Min/Max/Δ gar nichts statt
  „—". Das Modell liefert dort `None`, in QML kommt das als `undefined` an —
  geprüft wurde aber auf `null`, und `undefined !== null` ist wahr.
- **Parameter-Leiste:** die Knöpfe (56 px) ragten aus der 40 px hohen Zeile
  heraus und überlappten die Zeile darunter.
- **Firmware-Version:** `-DBUILD_DATE=\"__DATE__\"` setzte das Makro nie ein —
  in der Firmware stand wörtlich `__DATE____TIME__`. Außerdem war der Puffer
  `_fwVersion[24]` zu klein für den zusammengesetzten Text und schnitt ihn
  nach `„v0.0.1(Build vom Aug 22"` ab.
- **`tools/build_teensy_check.sh`** kannte die `-D`-Flags aus
  `platformio.ini` nicht und meldete deshalb einen Fehler in `main.cpp`, der
  keiner war. Die Flags werden jetzt aus der `platformio.ini` gelesen.
- **`tools/selftest.py`** ließ die CI-Stufe `pyflakes` rot laufen (ungenutzter
  `import serial`); jetzt über `importlib.util.find_spec()`.
