# Plan — Ressourcenverbrauch des Live-Plotters weiter reduzieren

**Stand:** 2026-09-02, Basis Version 2.6 (Commit `80e70e8`)
**Status:** **Phase 0 und Phase 1 sind umgesetzt** (Version 2.7, siehe
`CHANGELOG.md`). Phase 2 ist nach der Messung **gestrichen**. Phase 3 und 4
sind offen; die Messungen aus Phase 0 haben ihre Reihenfolge geändert.

---

## Inhalt

0. [Stand der Umsetzung](#0-stand-der-umsetzung)
1. [Ausgangslage — was 2.6 schon gebracht hat](#1-ausgangslage)
2. [Wo der verbleibende Verbrauch liegt](#2-wo-der-verbleibende-verbrauch-liegt)
3. [Maßnahmen in Phasen](#3-maßnahmen-in-phasen)
4. [Erwartete Gesamtwirkung](#4-erwartete-gesamtwirkung)
5. [Absicherung — wie nichts kaputtgeht](#5-absicherung)
6. [Randbeobachtung aus der Analyse](#6-randbeobachtung)
7. [Was bewusst nicht angefasst wird](#7-was-bewusst-nicht-angefasst-wird)

---

## 0. Stand der Umsetzung

| # | Maßnahme | Stand | Was die Messung sagt |
|---|---|---|---|
| M0 | `tools/plotter_bench.py` | **umgesetzt** | 11 Wert-Vergleiche in der CI; Messreihen unten |
| — | Messfenster von `note_render()` | **umgesetzt** | endete vor `_render_to_pixmap()` — der Wächter sah den größten Posten nie |
| M1 | Adaptiver Bildtakt | **umgesetzt** | 12,0 → 4,2 fps je nach Bilddauer, mit Hysterese |
| M2 | Y-Bereich quantisieren | **umgesetzt** | 91 → 7 Bereichswechsel je 200 Bilder; Zeitgewinn im Rauschen |
| M3 | Normierungsgrenzen puffern | **umgesetzt** | wertgleich; Grenzen wachsen je Block mit, damit nichts aus dem Bild läuft |
| M4 | Statistik/Wächter an Sichtbarkeit | **umgesetzt** | 4 → 0 `statsChanged`/s bei weggeschaltetem Tab; Wächter-Timer aus |
| M5 | Idle-Timer ereignisgesteuert | **verworfen** | spart höchstens 4 Weckrufe/s eines fast kostenlosen `_on_screen()`; braucht dafür neue QML→Host-Verdrahtung samt eigener Fehlerquelle (Plotter bleibt dunkel, wenn die Meldung ausbleibt) |
| M6 | Datenpfad-Restposten | **umgesetzt** | keine Zuteilung mehr im Poll-Takt; Puffer 100 → 60 kB |
| M7 | Legende als `QAbstractListModel` | **gestrichen** | gemessen 0,056 ms je Neuaufbau bei 8 Kurven = 0,28 ms/s. Es gibt nichts zu sparen |
| M8 | Statischer Hintergrund + Scroll-Blitt | **offen, jetzt klar der nächste Schritt** | 1 Kurve × 250 Punkte kostet 31,9 ms, 8 × 600 kosten 46,7 ms — der Grundbetrag dominiert |
| M9 | Rasterskala | **offen** | erst nach M8 sinnvoll zu bewerten |
| M10 | OpenGL | **offen** | unverändert Phase 4 |
| M11 | xcb dokumentieren | **umgesetzt** | `README_QML.md`, Hinweis in `setup_rpi5.sh` |

### Die Messreihen (offscreen, 800 × 400, `python tools/plotter_bench.py`)

```
Datenpfad (2000 Pakete a 5 Samples)      append_block   get_plot_arrays
  1 Kurve,  normiert                        0,010 ms        0,008 ms
  8 Kurven, normiert                        0,054 ms        0,039 ms

Rastern (vollstaendiger _redraw im Bild-Modus)          ms/Bild
  1 Kurve  x 250 Punkte                                   31,9
  1 Kurve  x 600 Punkte                                   35,6
  4 Kurven x 500 Punkte                                   36,3
  8 Kurven x 250 Punkte                                   40,8
  8 Kurven x 600 Punkte                                   46,7

QML-Legende (Delegates komplett neu)                    ms/Aufbau
  1 Kurve                                                 0,018
  8 Kurven                                                0,056
```

**Was daraus folgt — und die Annahmen des Plans korrigiert:**

1. **Die 95/5-Aufteilung aus 2.6 stimmt, ihre Deutung nicht.** Es sind nicht
   „die Kurven", die 95 % kosten: acht Kurven über 600 Punkte kosten nur
   47 % mehr als eine einzige über 250. Der Grundbetrag von rund 32 ms —
   Hintergrund, Gitter, Achsen — ist der eigentliche Posten. Damit ist
   **M8 Stufe A** (Hintergrund einmal rastern und blitten) der mit Abstand
   wirksamste verbleibende Schritt, und **K4** (Downsampling) praktisch
   bedeutungslos: die Punktezahl steht kaum in der Rechnung.
2. **K5 war eine Fehleinschätzung.** Der Legenden-Neuaufbau kostet bei acht
   Kurven 0,056 ms. Bei 5 Hz sind das 0,28 ms pro Sekunde. M7 ist damit vom
   Tisch — auch die dort erwogene Anhebung von `statsIntervalMs` auf 500 ms
   erübrigt sich. (Einschränkung: gemessen wurde das Erzeugen und Zerstören
   der Delegates an einem Repeater ohne sichtbares Fenster.)
3. **K3 lässt sich hier nicht in Zeit umrechnen.** Die Zahl der
   Bereichswechsel fällt eindeutig (91 → 7 je 200 Bilder), der
   Zeitunterschied (31,7 gegen 32,3 ms) liegt aber unter der Streuung von
   2,7 ms innerhalb einer Variante. Der belegte Nutzen von M2 ist vorerst
   die ruhige, ablesbare Achse; ob daraus auf dem Zielgerät Rechenzeit wird,
   ist dort zu messen.
4. **Der Messwert, den es vorher gar nicht gab.** Das Messfenster von
   `note_render()` endete vor `_render_to_pixmap()`. Der Wächter hat ein
   80-ms-Budget überwacht, ohne den teuersten Schritt zu sehen. Seit das
   behoben ist, fallen einzelne teure Durchläufe auf — deshalb schaltet der
   Wächter jetzt erst nach drei in Folge ab statt nach einem.

---

## 1. Ausgangslage

Version 2.6 hat die großen Posten bereits beseitigt (siehe `CHANGELOG.md`):

| Bereits erledigt | Wirkung |
|---|---|
| Zeichnen nur bei `bufferChanged` (Dirty-Flag) | Eingefroren/kein Datenstrom = 0 Redraws statt 20/s |
| `maxFps` 20 → 12, `idleFps` 4 | ~40 % weniger Zeichendurchläufe |
| Statistik/Legende gedrosselt auf 200 ms, ein Durchlauf | 37,5 ms → 3,4 ms je 100 Pakete |
| Keine Array-Allokation im Datentakt (vorab angelegte Puffer, float32) | ~1 MB/s kurzlebiger Speicher weniger |
| Festes QPixmap statt `grab()` pro Bild, `setOpaquePainting`, 1:1-Blitt | ~24 MB/s Allokation weniger |
| Marken-Stifte/-Zustand gepoolt, `setXRange` nur bei Änderung | Kleinkram im Taktniveau |

Die eigene Messung aus 2.6 gilt weiterhin als Arbeitsgrundlage: **~95 % der
Plotter-Last sind das Rastern** (pyqtgraph: Gitter, Achsen, alle Polylinien),
nur ~5 % sind Datenaufbereitung. Der wirksamste Hebel bleibt also der
**Bildtakt** und die **Arbeit pro Bild** — nicht der Datenpfad.

---

## 2. Wo der verbleibende Verbrauch liegt

| # | Kostenstelle | Details | Größe (Schätzung, in Phase 0 zu messen) |
|---|---|---|---|
| K1 | Fixer Bildtakt 12 fps unabhängig von der tatsächlichen Leistung | Auf schwacher Hardware (RPi 4) wird fröhlich gezeichnet, bis der Watchdog den Plotter *komplett* abschaltet — alles oder nichts | dominant, skaliert linear mit fps |
| K2 | Vollständige Szenen-Rasterung im Bildmodus | Pro Bild wird das **ganze** Widget (Gitter + Achsen + alle Kurven) über `QWidget.render()` gerastert, obwohl sich pro Frame nur ~8–9 neue Samples (100 Hz ÷ 12 fps ≈ 1,5 px) am rechten Rand ändern | dominant |
| K3 | Y-AutoRange bei gemeinsamer Skala | `enableAutoRange(Y)` läuft nach jedem `setData`, verändert fast immer den Bereich → Achsen-Ticks + Beschriftung (QFontMetrics) werden pro Frame neu berechnet und gerastert | mittel; im Normierungs-Modus bereits optimal (fest −0,1…1,1) |
| K4 | Downsampling greift praktisch nicht | 500 Punkte auf ~800 px Fläche ⇒ pyqtgraphs Auto-Faktor ≈ 1; es werden alle 500 Punkte je Kurve je Bild gerastert | mittel, wächst mit Kurvenzahl × Punkten |
| K5 | Legenden-Repeater-Neuaufbau alle 200 ms | `curveInfo` ist eine `QVariantList`-Property; jedes `statsChanged` ersetzt das Modell ⇒ QML zerstört/erzeugt alle Delegates (8×) | klein-mittel (Python-Seite 2.6 schon klein, QML-Seite bleibt) |
| K6 | Normierungsgrenzen pro Bild neu | `get_plot_arrays()` rechnet min/max **je Kurve je Bild** (2 NumPy-Durchläufe × 8 × Fenster), obwohl sich die Grenzen kaum ändern | klein (~Anteil der 5 %) |
| K7 | Statistik läuft auch bei unsichtbarem/abgeschaltetem Plotter | `_update_stats()` hängt am Datenpfad, nicht an der Sichtbarkeit; Watchdog-Timer läuft immer (4 Weckrufe/s), Idle-Timer 4/s | klein |
| K8 | Kleinigkeiten im Datenpfad | `_stack()` legt pro Poll ein neues Block-Array an (~4–20 kB × 20 Hz); Trigger hängt `np.concatenate` pro Block an; `_snap_buf`/`_live_buf` in voller Ringgröße statt Fenstergöße | sehr klein |

---

## 3. Maßnahmen in Phasen

Aufwand: **S** = Stunden, **M** = 1–2 Tage, **L** = mehrtägig.
Jede Maßnahme bekommt (wo sinnvoll) einen Schalter in `settings.json` →
`app_settings.DEFAULTS["plotter"]`, Vorgabe = altes Verhalten bzw. konservativ.

### Phase 0 — Messen vor Umbauen (Voraussetzung, S–M)

**M0: Benchmark-Werkzeug `tools/plotter_bench.py`**
- Drei getrennte Messungen, wie es die Repo-Kultur verlangt (2.6 hat jede Zahl belegt):
  1. **Datenpfad**: `append_block` + `get_plot_arrays` × N Pakete (ohne PyQt6, Stubs wie in `selftest.py`).
  2. **Rastern**: QApplication mit `QT_QPA_PLATFORM=offscreen`, Bild-Modus, 1000 Durchläufe `_redraw()` inkl. `_render_to_pixmap()`, Ausgabe ms/Bild je Kurvenzahl (1/4/8) × Punktezahl (250/500/1000).
  3. **QML-Legende**: Zeitmessung im `qml_smoketest.py`-Stil.
- Zusätzlich auf dem Zielgerät: `pidstat -p <GUI-PID> 1` daneben, GUI-Thread-Jitter des 100-Hz-Sendetakters als Endmetrik (die eigentliche Anforderung: der Plotter darf die Fernsteuerung nicht bremsen).
- **Wichtig:** Das heutige `note_render()`-Messfenster endet **vor** `_render_to_pixmap()` — der teuerste Schritt im Bildmodus (K2) geht in keiner Zahl auf. Phase 0 schließt das als Erstes.

Erst wenn Phase 0 die Posten K1–K8 in ms auf dem Zielgerät beziffert, werden die Phasen 1–3 mit Zahlen begleitet.

### Phase 1 — Schnelle, risikoarme Hebel (je S, zusammen ~2 Tage)

**M1: Adaptiver Bildtakt statt fester 12 fps (greift K1)**
- `_redraw` misst bereits (`note_render`). Erweiterung: gleitendes Mittel der **vollständigen** Durchlaufdauer (Messfenster inkl. Pixmap-Rendern, siehe M0) und Taktwahl `interval = clamp(k × t_frame, 1000/maxFps … 1000/minFps)` mit Hysterese, damit es nicht oszilliert.
- Neuer Schalter `plotter.adaptiveFps: true` (+ `plotter.minFps: 4`). `maxFps` bleibt die Obergrenze.
- Wirkung: Auf schwacher Hardware sinkt der Takt graceful auf z. B. 6 fps, **statt** den Plotter per Watchdog ganz abzuschalten; auf starker Hardware bleibt alles wie heute. Der Watchdog bleibt als letztes Netz.
- Risiko: gering. Zu testen: kein Flackern der Bildrate bei Lastwechseln (Hysterese/Tiefpass).

**M2: Y-Bereich quantisieren bei gemeinsamer Skala (greift K3)**
- AutoRange(Y) aus, stattdessen Bereich aus den ohnehin alle 200 ms berechneten min/max aller Kurven (`_refresh_stats`), auf „glatte“ Werte gerundet (1-2-5-Schritte) und nur bei Änderung > ~5 % übernehmen — derselbe Trick wie `_last_x_max` für die X-Achse.
- Wirkung: Kein Achsen-Neulayout/Tick-Neuberechnung mehr pro Bild; stabilere, weniger zappelnde Achse.
- Risiko: gering. Nur Modus „gemeinsame Skala“ betroffen; Normierungs-Modus unverändert.

**M3: Normierungsgrenzen cachen (greift K6)**
- min/max je Kurve nur im Statistik-Takt (200 ms) bzw. bei Kanalwechsel neu rechnen, speichern; `get_plot_arrays()` nutzt die gepufferten Werte. Die Subtraktion/Multiplikation selbst bleibt je Bild (die Werte ändern sich ja).
- Risiko: sehr gering — ein Ausreißer kann bis 200 ms leicht über den Bildrand ragen (Bereich ist mit ±0,1/±10 % Padding versehen); identische Argumentation wie bei der Legenden-Drossel: In 200 ms liest sowieso niemand die Skala neu.

**M4: Statistik & Watchdog an Sichtbarkeit koppeln (greift K7)**
- `_update_stats()` früh aussteigen, wenn `not _plot_active` (der Host meldet das schon an `setPlotActive` — die Brücke muss es nur noch merken). Beim Sichtbarwerden einmal `force=True` nachziehen.
- PerfWatchdog-Timer stoppen, solange der Plotter inaktiv ist (läuft heute ab Start dauerhaft mit 4 Hz).
- Risiko: sehr gering. Legende/Statistikzeile sind nur im Plotter-Tab sichtbar.

**M5: Idle-Timer ereignisgesteuert ersetzen (greift K7)**
- Statt per 4-Hz-Tick `_on_screen()` zu pollen: QML `PlotterView` meldet Sichtbarkeit (`SwipeView`-Index / `visible`) an den Host, der Timer stoppt komplett. Ein 1-Hz-Sicherheits-Tick bleibt für Sonderfälle (Fenster-Mapping), hinter `plotter.visibilityPollHz`.
- Wirkung: Bei ausgeblendetem Plotter null Weckrufe statt 4/s. Nur ein kleiner CPU-/Energiegewinn, aber kostenlos.

**M6: Datenpfad-Restposten (greift K8)**
- `_stack()`: nachwachsender vorab angelegter Puffer statt neuem Array je Poll.
- `_evaluate_trigger`: vorab angelegter `extended`-Puffer statt `np.concatenate` je Block.
- `_snap_buf`/`_live_buf` auf Fenstergröße (500) statt Ringgröße (1000) dimensionieren.
- Risiko: null (Verhalten identisch); Kandidat für Wert-für-Wert-Vergleich wie in 2.6.

### Phase 2 — Legende ohne Neuaufbau (M, ~1 Tag) — **GESTRICHEN**

> Phase 0 hat den Posten gemessen: ein kompletter Delegate-Neuaufbau kostet
> bei acht Kurven **0,056 ms**, bei 5 Hz also 0,28 ms pro Sekunde. Es gibt
> hier nichts zu sparen. Der Abschnitt bleibt stehen, damit nachvollziehbar
> ist, warum er nicht umgesetzt wurde.

**M7: `curveInfo` als `QAbstractListModel` statt `QVariantList` (greift K5)**
- Rollen: `name, unit, color, last, min, max, valid`. Im Statistik-Takt nur `dataChanged` für die passenden Rollen senden — QML aktualisiert dann **Textproperties**, statt 8 Delegates zu zerstören und neu zu erzeugen.
- `PlotterView.qml`: Repeater-Delegate auf Rollen umstellen (`modelData.last` → `model.last`).
- Alternativ/Dazu: `statsIntervalMs`-Vorgabe 200 → 500 ms diskutieren (Zahlen alle 0,5 s sind immer noch schneller lesbar als jemand sie erfassen kann).
- Risiko: mittel-klein (QML-Änderung). Absicherung über `check_qml_bindings.py` und `qml_smoketest.py`, die den Plotter-Pfad bereits ausführen.

### Phase 3 — Renderer-Arbeit im Bildmodus reduzieren (der große Hebel, L)

> Nach Phase 0 der klar nächste Schritt, und zwar deutlicher als gedacht:
> acht Kurven über 600 Punkte kosten nur 47 % mehr als eine einzige über 250.
> Der Grundbetrag (Hintergrund, Gitter, Achsen) ist der Posten — also **Stufe
> A zuerst**, und die Punktezahl-Optimierungen aus Stufe B (min/max-Dekimation)
> haben viel weniger Gewicht, als der ursprüngliche Text annimmt.

**M8: Statischer Hintergrund + Scroll-Blitt (greift K2, der stärkste Posten)**
Kernidee: Pro Bild ändert sich praktisch nur ein schmaler Streifen am rechten
Rand (~1,5 px bei 100 Hz/12 fps; selbst bei 4 fps ~4 px). Zwei Stufen:

- **Stufe A (mittel):** Gitter/Achsen/Beschriftung sind zwischen Resize-/Bereichsänderungen pixelidentisch. Diese Ebene **einmal** in ein Hintergrund-Pixmap rendern (Kurven kurz ausblenden → ein einziger `QWidget.render`-Aufruf), pro Bild nur den Hintergrund blitten und die Kurven darüber zeichnen. Invalidierung bei: Resize, X-/Y-Bereichswechsel, Moduswechsel.
- **Stufe B (groß):** Zusätzlich die **Kurvenebene** als eigenes Pixmap führen. Pro Bild: Pixmap um `k` Pixel nach links schieben (`QPixmap.scroll`/`copy`), nur den neuen Streifen (die 8–9 neuen Samples je Kurve) zeichnen. Rasterkosten werden damit **unabhängig von Fensterbreite und Kurvenzahl** — klassisches Oszilloskop-Verfahren.
  - Voraussetzungen prüfen: fester Y-Bereich (im Normierungs-Modus ohnehin gegeben — passt genau), Marken als Overlay-Layer (schmaler Neuzeichnungs-Streifen + Markenspalte), Einfrieren/Trigger/Umschalten schalten auf Vollredraw zurück.
  - Kurvenzeichnung selbst: min/max-Dekimation auf Pixelspalten (≤ 2 Punkte je Spalte und Kurve), sodass auch Zoom auf 1000 Punkte auf ~400 px Fläche konstant bleibt.
- Absicherung: neuer Schalter `plotter.renderer: "pyqtgraph" (Vorgabe) | "cached"`. Der bestehende Pfad bleibt vollständig erhalten und ist der Fallback — genau wie damals native → image → error.
- Erwartung (zu messen): Faktor 5–10 weniger Rasterarbeit pro Bild im scrollenden Normalfall; auf dem RPi 4 dürfte damit statt „Watchdog schaltet ab“ sogar Stufe B flüssig laufen.

**M9: Rasterskala im Bildmodus (klein, optional, zu Stufe A kombinierbar)**
- `plotter.renderScale: 1.0` (Vorgabe). Bei 0.5 wird das Pixmap halb so groß gerastert und beim Blitt skaliert → 4× weniger Pixelarbeit.
- Angebotener Kompromiss für schwache Geräte: Kurven bleiben lesbar (Trendansicht), Achsentext wird weicher. Deshalb Vorgabe 1.0 und bewusst nur ein Stellschrauben-Angebot.

### Phase 4 — Optional, nach Erfolg von Phase 1–3 bewerten

**M10: OpenGL-Rasterung probeweweise (greift K2)**
- `pg.setConfigOption("useOpenGL", True)` ist heute fest aus. Auf dem RPi 5 (V3D-GPU) könnte das die Polylinen-Rasterung von der CPU auf die GPU verlagern — Schalter `plotter.opengl: "auto"` mit Test beim Start und Fallback.
- Einschränkung, deshalb erst Phase 4: Hilft nur im **nativen Modus (xcb)** — der Bildmodus rendert ohnehin offscreen in ein QPixmap, dort gibt es keine GL-Oberfläche. Außerdem ist pyqtgraph+GL für Eigenheiten bekannt; visueller Abgleich nötig.

**M11: Betriebsmodus xcb dokumentieren/empfehlen (nur Doku/Konfiguration)**
- Der native Modus umgeht die komplette Pixmap-Kette (`QWidget.render` + Blitt) und funktioniert auf xcb zuverlässig (`_NATIVE_OK_PLATFORMS = {"xcb"}`). Für Kiosk-Setups auf dem Pi ist `QT_QPA_PLATFORM=xcb` heute schon der billigste Plotter — das steht nur nirgends als Empfehlung. Ein Absatz in `README_QML.md`/`README.md` + optional Eintrag in `setup_rpi5.sh`-Hinweisen. Vorher Touch-Eingabe und DPI dort abnehmen.

---

## 4. Erwartete Gesamtwirkung

Alle Zahlen sind Schätzungen auf Basis der 95/5-Aufteilung aus 2.6 und müssen
in Phase 0 auf dem Zielgerät belegt werden — genau dafür ist Phase 0 da.

| Maßnahme | Hebel | Erwartung | Aufwand | Risiko |
|---|---|---|---|---|
| M1 adaptiver Takt | K1 | schwache HW: ~50 % weniger Plotter-CPU statt Abschaltung | S | gering |
| M2 Y-Quantisierung | K3 | Achsen-Neulayout ~auf 0 im gemeinsamen Modus | S | gering |
| M3 Grenzen-Cache | K6 | ~1/3 der 5 %-Datenaufbereitung | S | sehr gering |
| M4/M5 Sichtbarkeit | K7 | 0 Kosten bei unsichtbarem Plotter (heute ~8 Weckrufe/s + Statistik) | S | sehr gering |
| M6 Restposten | K8 | Allokationen im Poll-Takt → 0 | S | null |
| M7 Legenden-Modell | K5 | kein Delegate-Neuaufbau mehr; QML-Seite der 200-ms-Kosten → ~0 | M | mittel-klein |
| M8 Scroll-Blitt | K2 | 5–10× weniger Rasterarbeit je Bild (Normalfall) | L | mittel (Fallback vorhanden) |
| M9 Rasterskala | K2 | bis 4× weniger Pixelarbeit (auf Optik) | S | optisch |
| M10 OpenGL | K2 | CPU-Entlastung nur im xcb-Modus, unklar | M | mittel |
| M11 xcb-Empfehlung | K2 | Pixmap-Kette komplett weg (Betriebswahl) | S (Doku) | — |

Reihenfolge bewusst so: Phase 1 kostet wenig, wirkt sofort überall und macht
den Plotter auf schwacher Hardware überhaupt erst wieder benutzbar; Phase 3
greift erst, wenn klar ist (Phase 0/1), wie groß K2 nach M1/M2 wirklich noch ist.

---

## 5. Absicherung

1. **Bestehende Tests laufen unverändert grün** — die Standards von 2.6 gelten weiter:
   `python tools/selftest.py` (214 Prüfungen), `python tools/check_qml_bindings.py`,
   `python tools/qml_smoketest.py` (führt den Plotter-Pfad real aus, inkl. Trigger/Einfrieren — CI-abgedeckt).
2. **Wert-für-Wert-Vergleich** wie in 2.6: Ringpufferinhalt, Kurvenarrays und Legendenzahlen alt/neu identisch (Skript in `tools/plotter_bench.py` mittesten lassen).
3. **Jeder Verhaltenskniff wird ein Schalter** mit Vorgabe = heutiges Verhalten; `settings.json`/`app_settings.DEFAULTS` + Doku im selben PR (Repo-Konvention).
4. **Watchdog bleibt an** — M1 ersetzt ihn nicht, sondern nimmt ihm vorher die Arbeit ab. Überlastungszähler im Diagnose-Tab als Regressionsindikator.
5. **Pro Phase ein Commit/PR**, CHANGELOG-Eintrag je Phase ( wieder mit Messwerten statt Adjektiven).

---

## 6. Randbeobachtung — geklärt, und schlimmer als gedacht

Die Vermutung im ursprünglichen Text war, der Dirty-Skip aus 2.6 habe die
gestrichelte „Live“-Kurve stillgelegt. Nachgemessen stimmt das nicht — die
Ursache ist älter und grundsätzlicher:

> `append_block()` kehrt bei `_frozen` früh zurück, **bevor** überhaupt in den
> Ringpuffer geschrieben wird. Im eingefrorenen Zustand wird also gar nichts
> aufgezeichnet. `live_snapshot()` liest denselben Ring und liefert deshalb
> exakt den Stand vom Moment des Einfrierens.

Nachgewiesen: 60 Samples einspeisen, einfrieren, weitere 40 einspeisen —
`live_snapshot()` endet danach unverändert auf `[55 56 57 58 59]`, und
`_total` steht weiter auf 60. Die gestrichelte Kurve liegt damit exakt auf der
eingefrorenen und war noch nie etwas anderes. Der frühe Rücksprung steht seit
Commit `8eb9743` im Code, also lange vor 2.6.

Damit ist das Banner **„EINGEFROREN — Aufzeichnung läuft weiter
(gestrichelt)“** (`PlotterView.qml`) schlicht falsch: es verspricht etwas, das
die Anwendung nicht tut.

Bewusst **nicht** in diesem Zug geändert, weil beide möglichen Auflösungen
Produktentscheidungen sind:

* **Banner und Overlay entfernen** — ehrlich, kostet nichts, nimmt aber eine
  angekündigte Fähigkeit weg.
* **Wirklich weiter aufzeichnen** — `append_block()` schreibt weiter, nur
  `snapshot()` liefert den festgehaltenen Stand. Das ist mehr als ein
  Einzeiler: `visible_markers()` rechnet gegen `_total` und `_filled`, also
  gegen das **laufende** Fenster. Sobald der Ring im eingefrorenen Zustand
  weiterläuft, wandern die Marken relativ zum stehenden Bild — heute fällt
  das nur deshalb nicht auf, weil `_total` mit einfriert. Dazu kommt der
  Redraw, den die Live-Kurve braucht: der muss im Ruhetakt budgetiert werden
  (nur die Overlay-Kurve, nur mit `idleFps`), sonst gibt man die
  „Eingefroren kostet nichts“-Eigenschaft aus 2.6 wieder her.

Zu entscheiden, bevor jemand daran arbeitet — nicht nebenbei.

---

## 7. Was bewusst nicht angefasst wird

- **Datenpfad-Umzug in einen Thread** (pyqtgraph-Widget ist nicht thread-sicher; der GUI-Thread hält den 100-Hz-Sendetakt — die Fehlerquelle wäre größer als der Gewinn, solange Phase 1–3 nicht ausgeschöpft sind).
- **Ringpuffergröße / `historySeconds`** — 32 kB Speicher und vernachlässigbare Schreibkosten; kein Hebel.
- **Telemetrierate des Teensy** — der Plotter verbraucht daran fast nichts (Fenster ist punktezahl-begrenzt); die Tabelle braucht die 100 Hz.
- **Darstellung/Bedienung** — Farben, Kurvenzahl, Trigger, Marken bleiben exakt, wie sie sind.
