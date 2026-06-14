# Power Debug System — Benutzerhandbuch

> **Zielgruppe:** Anwender, die das System in Betrieb nehmen und in eigene Teensy-Programme integrieren wollen.  
> **Voraussetzung:** Hardware ist verkabelt, Setup-Skripte wurden ausgeführt (→ `SETUP_GUIDE.md`).  
> **Kontext:** RoboCup Junior Soccer 2v2, Teensy 4.0 + RPi Zero W + RPi 5

---

## Inhaltsverzeichnis

1. [Systemüberblick in 2 Minuten](#1-systemüberblick-in-2-minuten)
2. [Startreihenfolge & täglicher Betrieb](#2-startreihenfolge--täglicher-betrieb)
3. [Teensy-Firmware — Integration in eigene Programme](#3-teensy-firmware--integration-in-eigene-programme)
   - 3.1 [Konzept: Wie das Debug-System parallel läuft](#31-konzept-wie-das-debug-system-parallel-läuft)
   - 3.2 [Schritt-für-Schritt: Eigenen Code einbinden](#32-schritt-für-schritt-eigenen-code-einbinden)
   - 3.3 [Das `DBG()`-Makro — Werte melden](#33-das-dbg-makro--werte-melden)
   - 3.4 [Vollständiges Integrationsbeispiel](#34-vollständiges-integrationsbeispiel)
   - 3.5 [Timing & Einschränkungen](#35-timing--einschränkungen)
4. [Variablen-Gruppen planen](#4-variablen-gruppen-planen)
   - 4.1 [Kanalplan erstellen](#41-kanalplan-erstellen)
   - 4.2 [Kanalplan-Template für RoboCup Soccer](#42-kanalplan-template-für-robocup-soccer)
   - 4.3 [Kanalnamen in der GUI konfigurieren](#43-kanalnamen-in-der-gui-konfigurieren)
   - 4.4 [Kanäle zur Laufzeit aktivieren/deaktivieren](#44-kanäle-zur-laufzeit-aktivierendeaktivieren)
5. [GUI bedienen](#5-gui-bedienen)
   - 5.1 [Steuerungsleiste](#51-steuerungsleiste)
   - 5.2 [Tab Live-Tabelle](#52-tab-live-tabelle)
   - 5.3 [Tab Live-Plotter](#53-tab-live-plotter)
   - 5.4 [Typische Debug-Szenarien](#54-typische-debug-szenarien)
6. [Firmware flashen](#6-firmware-flashen)
7. [LED-Statusanzeige — Schnellreferenz](#7-led-statusanzeige--schnellreferenz)
8. [Troubleshooting](#8-troubleshooting)
9. [Referenz: Kanalplan-Vorlage](#9-referenz-kanalplan-vorlage)

---

## 1. Systemüberblick in 2 Minuten

```
Dein Roboter-Code (Teensy)
  │
  │  DBG(CH_MOTOR_L, leftSpeed);   ← du schreibst Werte rein
  │  DBG(CH_COMPASS, heading);
  │
  ▼
UART-Sender (Serial1)  ──TX──►  RPi Zero W  ──WiFi UDP──►  RPi 5 GUI
  (sendet 100×/s)                (leitet weiter)          (zeigt an)
```

Das Debug-System läuft **vollständig im Hintergrund** deines Roboter-Codes:

- Du rufst **einmal pro Loop** `DBG(Kanal, Wert)` auf — fertig. (Max. 400 Kanäle)
- Der Teensy sendet das fertige Paket per UART (Serial1) mit 4 Mbps an den RPi Zero W.
- Der RPi Zero W leitet sie per WiFi an den RPi 5 weiter.
- Die GUI zeigt alle Werte live an — ohne dass dein Roboter-Code gebremst wird.

**Was du brauchst:**
- `main.cpp` auf dem Teensy anpassen (→ Abschnitt 3)
- Kanalnamen in `config.py` auf dem RPi 5 eintragen (→ Abschnitt 4.3)
- Fertig — der Rest passiert automatisch

---

## 2. Startreihenfolge & täglicher Betrieb

### Empfohlene Reihenfolge beim Einschalten

```
 ① RPi 5 einschalten
    └─ Warte bis WLAN-AP "PowerDebugAP" sichtbar ist (~30 Sek.)
    └─ GUI startet automatisch nach dem Desktop-Login

 ② RPi Zero W(s) einschalten
    └─ Grüne LED blinkt → Dienste laufen
    └─ Blaue LED leuchtet dauerhaft → WLAN verbunden

 ③ Roboter (Teensy) einschalten / per USB an RPi Zero anschließen
    └─ Gelbe LED blinkt → Teensy sendet Daten

 ④ GUI auf RPi 5 zeigt nach ~5 Sekunden Live-Daten
```

> **Reihenfolge wichtig:** RPi 5 muss zuerst starten, da er den WLAN-Hotspot aufspannt.  
> Die RPi Zeros verbinden sich erst, wenn der AP sichtbar ist.

### Täglicher Betrieb (System läuft bereits)

- Roboter neu starten → Daten erscheinen automatisch wieder in der GUI
- Firmware ändern → Abschnitt 6 (Over-the-Air Flash)
- Zweiten Roboter anschließen → Node-Selektor in GUI auf Node 2 umschalten

### System sauber herunterfahren

```bash
# Auf RPi 5 (falls nötig):
sudo shutdown -h now

# Auf RPi Zero W (falls nötig):
ssh pi@192.168.42.11 "sudo shutdown -h now"
```

Beide Geräte können auch einfach stromlos gemacht werden — die Dienste starten beim nächsten Boot automatisch.

---

## 3. Teensy-Firmware — Integration in eigene Programme

### 3.1 Konzept: Wie das Debug-System parallel läuft

Die `main.cpp` aus diesem Repository ist ein **Standalone-Testprogramm** das Sinuswellen sendet. In der Praxis willst du aber **deinen Roboter-Code** laufen lassen und dabei Werte überwachen.

Das Prinzip: Es gibt ein globales Float-Array `debugData[400]`. Du schreibst deine Werte dort hinein. `buildPacket()` liest daraus und verpackt alles. `Serial1.write()` kopiert das fertige Paket in den TX-Buffer und kehrt sofort zurück — dein Loop wird nicht blockiert.

```
Dein loop()                     Interrupt (automatisch)
────────────────                ────────────────────────
sensors.update();               alle 10 ms: buildPacket()
debugData[0] = leftSpeed;  →→→  → packt debugData[] als UART-Paket
debugData[1] = rightSpeed;      → Serial1.write() → TX-Buffer
motors.drive(...);              → DMA sendet async an RPi Zero
debugData[2] = heading;
// keine Wartezeit nötig!
```

### 3.2 Schritt-für-Schritt: Eigenen Code einbinden

#### A. Datei `main.cpp` öffnen (PlatformIO / VS Code)

Die relevante Stelle ist `buildPacket()`. Standardmäßig steht dort das Testmuster (Sinuswellen). Das wird ersetzt.

#### B. Globales Debug-Array anlegen

Direkt unter den `#include`-Zeilen und Konstanten einfügen:

```cpp
// ── Debug-Datenarray ─────────────────────────────────────────────────────────
// Alle Kanäle mit Dummy-Wert vorbelegen (wird vom RPi 5 herausgefiltert)
static float   debugData[MAX_FLOATS];   // MAX_FLOATS = 400
static uint8_t _pkt_buf[PACKET_BYTES];  // 1608 Bytes — Sende-Buffer

// Komfortmakro: DBG(Kanal, Wert) — schreibt einen Wert in den Debug-Puffer
#define DBG(channel, value)  debugData[(channel)] = static_cast<float>(value)

// ── Kanal-Definitionen ────────────────────────────────────────────────────────
// Hier alle Kanalnummern als sprechende Konstanten definieren
// (muss mit config.py auf dem RPi 5 übereinstimmen)
#define CH_MOTOR_L_SPEED    0
#define CH_MOTOR_R_SPEED    1
#define CH_MOTOR_L_PWM      2
#define CH_MOTOR_R_PWM      3
#define CH_COMPASS          10
#define CH_BALL_X           20
#define CH_BALL_Y           21
#define CH_BALL_STRENGTH    22
// ... weitere Kanäle (→ Abschnitt 4)
```

#### C. `buildPacket()` anpassen

Die Funktion `buildPacket()` ersetzt den Sinuswellen-Testcode durch das Kopieren des Debug-Arrays:

```cpp
void buildPacket() {
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(_pkt_buf,     &magic, 4);
    memcpy(_pkt_buf + 4, &ts,    4);
    memcpy(_pkt_buf + 8, debugData, MAX_FLOATS * sizeof(float));
}
```

#### D. `setup()` anpassen

Debug-Array mit Dummy-Wert vorinitialisieren:

```cpp
void setup() {
    Serial.begin(115200);
    delay(400);

    // Debug-Array initialisieren (alle Kanäle = inaktiv)
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 9898.0f;  // 400 Kanäle

    // ... restlicher Setup-Code (Motoren, Sensoren etc.) ...

    // Serial1 TX-Buffer erweitern (Standard 64 Byte ist zu klein für 1608 Byte)
    static uint8_t serial1_buf[4096];
    Serial1.addMemoryForWrite(serial1_buf, sizeof(serial1_buf));
    Serial1.begin(4000000, SERIAL_8N1);   // 4 Mbps, 8N1

    Serial.println("[Teensy] Debug-System bereit.");
}
```

#### E. `loop()` — DBG()-Aufrufe einstreuen

```cpp
void loop() {
    static uint32_t last_us = 0;

    // ── Dein normaler Roboter-Code ────────────────────────────────────────────
    compass.update();
    ball.update();
    motors.calculate();

    // ── Debug-Werte melden (einfach zwischen beliebige Code-Zeilen setzen) ────
    DBG(CH_COMPASS,       compass.getHeading());
    DBG(CH_BALL_X,        ball.getX());
    DBG(CH_BALL_Y,        ball.getY());
    DBG(CH_BALL_STRENGTH, ball.getStrength());
    DBG(CH_MOTOR_L_SPEED, motors.getLeftSpeed());
    DBG(CH_MOTOR_R_SPEED, motors.getRightSpeed());
    DBG(CH_MOTOR_L_PWM,   motors.getLeftPWM());
    DBG(CH_MOTOR_R_PWM,   motors.getRightPWM());

    // ── UART-Paket alle 10 ms senden (100 Hz) ─────────────────────────────────
    const uint32_t now = micros();
    if (now - last_us >= SAMPLE_PERIOD_US) {
        last_us = now;
        buildPacket();                          // füllt _pkt_buf[]
        Serial1.write(_pkt_buf, PACKET_BYTES); // non-blocking, kehrt sofort zurück
    }
}
```

### 3.3 Das `DBG()`-Makro — Werte melden

Das `DBG()`-Makro ist absichtlich so einfach wie möglich gehalten:

```cpp
DBG(CH_COMPASS, 127.5f);           // Float-Wert direkt
DBG(CH_MOTOR_L_PWM, pwmValue);     // Variable (wird zu float gecastet)
DBG(CH_BALL_FOUND, ball.found());  // bool (wird 0.0 oder 1.0)
DBG(CH_STATE, (int)robotState);    // Enum als Zahl
DBG(CH_LOOP_TIME, loopMicros);     // uint32_t
```

**Wo im Code aufrufen?**

- `DBG()` kann **überall** in `loop()` aufgerufen werden — auch in Unterfunktionen
- Der Aufruf kostet nur eine Array-Zuweisung: `debugData[x] = (float)y` → **nahezu keine Laufzeitkosten**
- Pro Kanal reicht **ein Aufruf pro Loop-Iteration** — bei 100 Hz Loop werden 100 Werte/s übertragen

**Was passiert, wenn ich denselben Kanal mehrfach beschreibe?**

Immer der **zuletzt geschriebene Wert** landet im Paket. Das ist nützlich für Zwischenwerte:

```cpp
DBG(CH_PID_ERROR, error);          // Fehler vor Clipping
pidOutput = constrain(pidRaw, -255, 255);
DBG(CH_PID_OUTPUT, pidOutput);     // Ausgabe nach Clipping
// → beide Werte landen im selben Paket, keine Überschreibung (verschiedene Kanäle)
```

### 3.4 Vollständiges Integrationsbeispiel

Hier ein realistisches Beispiel für einen RoboCup-Soccer-Roboter:

```cpp
/*
 * RoboCup Soccer Roboter — main.cpp
 * Integriert Power Debug System
 */

#include <Arduino.h>
#include "MyCompass.h"      // deine eigenen Bibliotheken
#include "MyBallSensor.h"
#include "MyMotors.h"

// ── Kanal-Definitionen ────────────────────────────────────────────────────────
#include "debug_channels.h"   // Kanal-Header (→ Abschnitt 4.1)

// ── Debug-System ──────────────────────────────────────────────────────────────
#ifndef ACTIVE_CHANNELS
  #define ACTIVE_CHANNELS 400
#endif
static constexpr uint32_t UART_BAUD        = 4000000UL;
static constexpr uint32_t HEADER_MAGIC     = 0xDEADBEEFUL;
static constexpr int      MAX_FLOATS       = 400;
static constexpr int      PACKET_BYTES     = 8 + MAX_FLOATS * 4;  // 1608 Bytes
static constexpr uint32_t SAMPLE_PERIOD_US = 10000UL;

static float   debugData[MAX_FLOATS];
static uint8_t _pkt_buf[PACKET_BYTES];
static uint8_t _serial1_buf[4096];        // erweiterter TX-Buffer
#define DBG(ch, val) debugData[(ch)] = static_cast<float>(val)

void buildPacket() {
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(_pkt_buf,     &magic, 4);
    memcpy(_pkt_buf + 4, &ts,    4);
    memcpy(_pkt_buf + 8, debugData, MAX_FLOATS * sizeof(float));
}

// ── Deine Objekte ─────────────────────────────────────────────────────────────
MyCompass   compass;
MyBallSensor ball;
MyMotors    motors;

// ── Roboter-Zustand ───────────────────────────────────────────────────────────
enum State { SEARCH, APPROACH, SHOOT, DEFEND };
State robotState = SEARCH;

// ─────────────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(300);

    // Debug-Array mit Dummy-Wert füllen
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 9898.0f;

    // Eigene Hardware initialisieren
    compass.begin();
    ball.begin();
    motors.begin();

    // UART starten
    // Serial1 TX-Buffer erweitern (Standard 64 Byte ist zu klein für 1608 Byte)
    static uint8_t serial1_buf[4096];
    Serial1.addMemoryForWrite(serial1_buf, sizeof(serial1_buf));
    Serial1.begin(4000000, SERIAL_8N1);   // 4 Mbps, 8N1

    Serial.println("[Roboter] Bereit.");
}

void loop() {
    static uint32_t last_sample_us  = 0;
    static uint32_t last_stat_ms    = 0;
    static uint32_t loopStart       = 0;
    static uint32_t pkt_count       = 0;

    loopStart = micros();

    // ══════════════════════════════════════════════════════════════════════════
    //  ROBOTER-LOGIK
    // ══════════════════════════════════════════════════════════════════════════

    // Sensoren auslesen
    compass.update();
    ball.update();

    float heading   = compass.getHeading();    // 0..359
    float ballAngle = ball.getAngle();         // -180..180
    float ballDist  = ball.getDistance();      // 0..100
    bool  ballSeen  = ball.isVisible();

    // Zustandsmaschine
    switch (robotState) {
        case SEARCH:
            motors.rotate(45.0f);
            if (ballSeen) robotState = APPROACH;
            break;
        case APPROACH:
            motors.moveTowards(ballAngle, 180);
            if (ballDist < 15.0f) robotState = SHOOT;
            if (!ballSeen)        robotState = SEARCH;
            break;
        case SHOOT:
            motors.kick();
            robotState = SEARCH;
            break;
        case DEFEND:
            motors.holdPosition(0.0f, heading);
            break;
    }

    // ══════════════════════════════════════════════════════════════════════════
    //  DEBUG-REPORTING  (alle Kanäle hier befüllen)
    // ══════════════════════════════════════════════════════════════════════════

    // Gruppe: Antrieb
    DBG(CH_MOTOR_L_SPEED, motors.getLeftSpeed());
    DBG(CH_MOTOR_R_SPEED, motors.getRightSpeed());
    DBG(CH_MOTOR_L_PWM,   motors.getLeftPWM());
    DBG(CH_MOTOR_R_PWM,   motors.getRightPWM());

    // Gruppe: Kompass / Orientierung
    DBG(CH_COMPASS_HEADING, heading);

    // Gruppe: Ball-Sensor
    DBG(CH_BALL_ANGLE,    ballAngle);
    DBG(CH_BALL_DIST,     ballDist);
    DBG(CH_BALL_VISIBLE,  (float)ballSeen);

    // Gruppe: Systemzustand
    DBG(CH_STATE,      (int)robotState);
    DBG(CH_LOOP_TIME,  micros() - loopStart);

    // ══════════════════════════════════════════════════════════════════════════
    //  UART-PAKET SENDEN (alle 10 ms → 100 Hz)
    // ══════════════════════════════════════════════════════════════════════════

    const uint32_t now = micros();
    if (now - last_sample_us >= SAMPLE_PERIOD_US) {
        last_sample_us = now;
        buildPacket();
        Serial1.write(_pkt_buf, PACKET_BYTES);  // non-blocking
        pkt_count++;
    }

    // Statistik alle 5 s auf Serial
    const uint32_t now_ms = millis();
    if (now_ms - last_stat_ms >= 5000) {
        last_stat_ms = now_ms;
        Serial.printf("[Debug] %lu Pkt/5s | Loop: %lu µs | TX-frei: %d B\n",
                      pkt_count, micros() - loopStart,
                      Serial1.availableForWrite());
        pkt_count = 0;
    }
}
```

### 3.5 Timing & Einschränkungen

| Aspekt | Detail |
|---|---|
| **Loop-Overhead** | `DBG()` = 1 Float-Zuweisung ≈ 1–2 ns → vernachlässigbar |
| **UART-Übertragung** | 1608 Bytes bei 4 Mbps ≈ 4,0 ms — `Serial1.write()` non-blocking, DMA überträgt asynchron |
| **Paketrate** | Fest 100 Hz (alle 10 ms) — unabhängig von Loop-Geschwindigkeit |
| **Maximale Kanäle** | 400 float32 pro Paket (je 4 Byte = 1600 Byte Nutzdaten) |
| **Aktive Kanäle** | Frei wählbar (0–400) via `ACTIVE_CHANNELS`. Inaktive Kanäle = 9898.0f |
| **Wert-Typ** | Immer `float32`. Bool/Enum/Int werden automatisch gecasted |
| **UART-Pins (Teensy 4.0)** | TX=Pin 1 (→ RPi GPIO15), RX=Pin 0 (← RPi GPIO14, optional) |
| **Loop muss nicht 100 Hz haben** | Wenn dein Loop schneller läuft (z.B. 500 Hz) werden einfach mehrere Loops pro Paket ausgeführt — kein Problem |

> ⚠️ **Wichtig:** `Serial1.write()` kopiert die Bytes in den internen TX-Buffer und kehrt sofort zurück. Der UART-DMA überträgt im Hintergrund. Stelle sicher, dass `Serial1.addMemoryForWrite()` in `setup()` aufgerufen wird — sonst ist der Buffer zu klein und `write()` blockiert.

---

## 4. Variablen-Gruppen planen

### 4.1 Kanalplan erstellen

Der Teensy hat 400 Kanäle (0–399). Die Planung in Gruppen macht die GUI übersichtlich und erleichtert späteres Erweitern.

**Empfehlung: Separate Header-Datei `debug_channels.h`**

Diese Datei auf dem Teensy und parallel in `config.py` auf dem RPi 5 pflegen.

```cpp
// teensy_firmware/src/debug_channels.h
#pragma once

// ── Gruppe 0: Antrieb (Kanäle 0–9) ──────────────────────────────────────────
#define CH_MOTOR_L_SPEED    0   // Solldrehzahl links  [rad/s oder normiert -1..1]
#define CH_MOTOR_R_SPEED    1   // Solldrehzahl rechts
#define CH_MOTOR_L_PWM      2   // PWM-Wert links      [0..255]
#define CH_MOTOR_R_PWM      3   // PWM-Wert rechts
#define CH_MOTOR_L_ACTUAL   4   // Ist-Drehzahl links  (falls Encoder vorhanden)
#define CH_MOTOR_R_ACTUAL   5   // Ist-Drehzahl rechts
// 6–9: Reserve Antrieb

// ── Gruppe 1: Orientierung (Kanäle 10–19) ────────────────────────────────────
#define CH_COMPASS_HEADING  10  // Kompass-Winkel [0..359°]
#define CH_COMPASS_RAW_X    11  // Rohwert X-Achse (Kalibrierung)
#define CH_COMPASS_RAW_Y    12  // Rohwert Y-Achse
#define CH_GYRO_Z           13  // Gierrate [°/s]
#define CH_TARGET_HEADING   14  // Sollwinkel (Regler-Eingang)
#define CH_HEADING_ERROR    15  // Winkel-Fehler (Ist - Soll)
// 16–19: Reserve Orientierung

// ── Gruppe 2: Ball-Sensor (Kanäle 20–29) ─────────────────────────────────────
#define CH_BALL_ANGLE       20  // Ball-Winkel relativ zu Roboter [-180..180°]
#define CH_BALL_DIST        21  // Ball-Distanz [normiert 0..100]
#define CH_BALL_VISIBLE     22  // Ball sichtbar [0 oder 1]
#define CH_BALL_STRONGEST   23  // Stärkster IR-Sensor (0..11)
#define CH_BALL_RAW_0       24  // IR-Rohwert Sensor 0
#define CH_BALL_RAW_1       25  // IR-Rohwert Sensor 1
// ... bis CH_BALL_RAW_11 = 35
// 28–29: Reserve Ball

// ── Gruppe 3: Liniensensor (Kanäle 30–39) ────────────────────────────────────
#define CH_LINE_FRONT       30  // Linie vorne erkannt [0/1]
#define CH_LINE_BACK        31  // Linie hinten
#define CH_LINE_LEFT        32  // Linie links
#define CH_LINE_RIGHT       33  // Linie rechts
#define CH_LINE_POSITION    34  // Linienposition [-1..1]
// 35–39: Reserve Linie

// ── Gruppe 4: PID-Regler (Kanäle 40–59) ──────────────────────────────────────
#define CH_PID_HEADING_SP   40  // Heading-Regler Sollwert
#define CH_PID_HEADING_IST  41  // Heading-Regler Istwert
#define CH_PID_HEADING_ERR  42  // Fehler
#define CH_PID_HEADING_P    43  // P-Anteil
#define CH_PID_HEADING_I    44  // I-Anteil
#define CH_PID_HEADING_D    45  // D-Anteil
#define CH_PID_HEADING_OUT  46  // Ausgang
// 47–49: Reserve Heading-PID

#define CH_PID_DRIVE_SP     50  // Antriebs-Regler Sollwert
#define CH_PID_DRIVE_OUT    51
// 52–59: Reserve Drive-PID

// ── Gruppe 5: Kommunikation (Kanäle 60–79) ───────────────────────────────────
#define CH_PARTNER_X        60  // Position Partner-Roboter X
#define CH_PARTNER_Y        61  // Position Partner-Roboter Y
#define CH_PARTNER_HEADING  62  // Heading Partner
#define CH_PARTNER_ACTIVE   63  // Partner empfängt [0/1]
#define CH_COMM_RSSI        64  // WLAN-Signalstärke (falls verfügbar)
// 65–79: Reserve Kommunikation

// ── Gruppe 6: System / Diagnose (Kanäle 80–99) ───────────────────────────────
#define CH_STATE            80  // Roboter-Zustandsmaschine (Enum als int)
#define CH_LOOP_TIME        81  // Loop-Dauer [µs]
#define CH_BATTERY_V        82  // Akku-Spannung [V]
#define CH_BATTERY_PCT      83  // Akku-Ladung [%]
#define CH_UPTIME_S         84  // Betriebszeit [s]
#define CH_ERROR_FLAGS      85  // Fehler-Bitmaske
// 86–99: Reserve System

// ── Gruppe 7: Freie Nutzung / Experimente (Kanäle 100–499) ───────────────────
// Frei belegbar für temporäre Messungen, neue Sensoren, etc.

// ── Gruppe 8: Nicht genutzt (Kanäle 100–399) → Dummy 9898 ────────────────────
```

### 4.2 Kanalplan-Template für RoboCup Soccer

Übersicht aller empfohlenen Gruppen:

| Bereich | Kanäle | Anzahl | Typische Werte |
|---|:---:|:---:|---|
| Antrieb | 0–9 | 6 genutzt | Geschwindigkeit, PWM, Ist-Wert |
| Orientierung | 10–19 | 6 genutzt | Kompass, Gyro, Soll/Ist-Heading |
| Ball-Sensor | 20–29 | 4 genutzt | Winkel, Distanz, IR-Rohwerte |
| Liniensensor | 30–39 | 5 genutzt | Erkennung je Seite, Position |
| PID-Regler | 40–59 | 10 genutzt | SP/IST/P/I/D/OUT pro Regler |
| Kommunikation | 60–79 | 5 genutzt | Partner-Position, RSSI |
| System / Diagnose | 80–99 | 6 genutzt | Zustand, Loop-Zeit, Akku |
| Freie Nutzung | 100–499 | — | Temporäre Messungen |
| Ungenutzt | 100–399 | — | Dummy (9898) |

> **Tipp:** Nicht alle 400 Kanäle müssen belegt sein. Leere Kanäle werden automatisch mit `9898.0f` gefüllt und von der GUI herausgefiltert — sie tauchen gar nicht auf.

### 4.3 Kanalnamen in der GUI konfigurieren

Die Kanalnamen werden in `config.py` auf dem **RPi 5** konfiguriert.

```bash
# Auf RPi 5: Konfigurationsdatei öffnen
nano /opt/power_debug_monitor/config.py
```

Den `VARIABLE_NAMES`-Block anpassen:

```python
# config.py  — Abschnitt VARIABLE_NAMES
VARIABLE_NAMES: dict[int, str] = {
    i: f"Var_{i:03d}" for i in range(MAX_FLOATS)  # Standard: generisch
}

# ── Eigene Namen eintragen (nach dem obigen Block): ──────────────────────────

# Gruppe 0: Antrieb
VARIABLE_NAMES[0]  = "Motor_L_Speed"
VARIABLE_NAMES[1]  = "Motor_R_Speed"
VARIABLE_NAMES[2]  = "Motor_L_PWM"
VARIABLE_NAMES[3]  = "Motor_R_PWM"
VARIABLE_NAMES[4]  = "Motor_L_Actual"
VARIABLE_NAMES[5]  = "Motor_R_Actual"

# Gruppe 1: Orientierung
VARIABLE_NAMES[10] = "Compass_Heading"
VARIABLE_NAMES[11] = "Compass_Raw_X"
VARIABLE_NAMES[12] = "Compass_Raw_Y"
VARIABLE_NAMES[13] = "Gyro_Z"
VARIABLE_NAMES[14] = "Target_Heading"
VARIABLE_NAMES[15] = "Heading_Error"

# Gruppe 2: Ball
VARIABLE_NAMES[20] = "Ball_Angle"
VARIABLE_NAMES[21] = "Ball_Distance"
VARIABLE_NAMES[22] = "Ball_Visible"
VARIABLE_NAMES[23] = "Ball_Strongest_IR"

# Gruppe 3: Linie
VARIABLE_NAMES[30] = "Line_Front"
VARIABLE_NAMES[31] = "Line_Back"
VARIABLE_NAMES[32] = "Line_Left"
VARIABLE_NAMES[33] = "Line_Right"
VARIABLE_NAMES[34] = "Line_Position"

# Gruppe 4: PID
VARIABLE_NAMES[40] = "PID_Hdg_Setpoint"
VARIABLE_NAMES[41] = "PID_Hdg_Istwert"
VARIABLE_NAMES[42] = "PID_Hdg_Error"
VARIABLE_NAMES[43] = "PID_Hdg_P"
VARIABLE_NAMES[44] = "PID_Hdg_I"
VARIABLE_NAMES[45] = "PID_Hdg_D"
VARIABLE_NAMES[46] = "PID_Hdg_Output"

# Gruppe 6: System
VARIABLE_NAMES[80] = "Robot_State"
VARIABLE_NAMES[81] = "Loop_Time_us"
VARIABLE_NAMES[82] = "Battery_Voltage"
VARIABLE_NAMES[83] = "Battery_Percent"
VARIABLE_NAMES[84] = "Uptime_s"
VARIABLE_NAMES[85] = "Error_Flags"
```

Nach dem Speichern die GUI neu starten:

```bash
pkill -f "python3 main.py"
power-debug-monitor &
```

### 4.4 Kanäle zur Laufzeit aktivieren/deaktivieren

`ACTIVE_CHANNELS` in `platformio.ini` steuert, wie viele Kanäle übertragen werden:

```ini
; platformio.ini
build_flags =
    -DACTIVE_CHANNELS=100   ; Nur Kanäle 0–99 aktiv, 100–399 = Dummy
```

Oder direkt in `main.cpp` / `debug_channels.h`:

```cpp
// Temporär: nur Antrieb + Ball debuggen → weniger Traffic
#undef  ACTIVE_CHANNELS
#define ACTIVE_CHANNELS 25   // Kanäle 0–24 aktiv (max. 400 gesamt)
```

> Weniger aktive Kanäle = kleinere nutzbare Pakete, aber die Paketgröße bleibt immer 4008 Bytes (Dummy füllt den Rest). Für die Übertragungsrate macht es keinen Unterschied.

---

## 5. GUI bedienen

### 5.1 Steuerungsleiste

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [○ Node 1 (192.168.42.11)]  [● Node 2 (192.168.42.12)]                 │
│  ⬤ Node 1  ⬤ Node 2    Ziel: ☑ Node 1  ☐ Node 2   [⚡ Flashen…]        │
└─────────────────────────────────────────────────────────────────────────┘
```

| Element | Funktion |
|---|---|
| **Node-Wahl (Radio)** | Umschalten welcher Roboter in Tabelle + Plotter angezeigt wird |
| **⬤ Grün** | Node verbunden und sendet Daten |
| **⬤ Rot** | Node nicht erreichbar / Teensy sendet nicht |
| **Ziel-Checkboxen** | Welche Nodes beim Flash-Vorgang beschrieben werden |
| **⚡ Flashen** | Firmware-Datei auswählen und auf gewählte Nodes übertragen |

> **Node wechseln** löscht Min/Max-Statistik und den Plot-Buffer — das ist beabsichtigt, damit keine Werte vom anderen Roboter die Statistik verfälschen.

### 5.2 Tab Live-Tabelle

Zeigt alle **aktiven Kanäle** (Wert ≠ 9898) als Tabelle:

| Spalte | Bedeutung |
|---|---|
| **Variable** | Name aus `config.py` (z.B. `Motor_L_Speed`) |
| **Aktuell** | Letzter empfangener Wert. Grün = positiv, Rot = negativ |
| **Min** | Kleinstwert seit Start oder letztem Reset |
| **Max** | Größtwert seit Start oder letztem Reset |
| **Δ** | Max − Min (Wertebereich) |

**Nützliche Aktionen:**

- **„↺ Min/Max zurücksetzen"** — vor einer Testfahrt drücken, um saubere Statistiken zu bekommen
- Tabelle nach Kanal-Name sortierbar (Spaltenheader klicken)
- Scrollbar bei vielen Kanälen

### 5.3 Tab Live-Plotter

Visualisiert einen einzelnen Kanal als Zeitverlauf.

```
Variable: [Motor_L_Speed ▼]   Punkte: [200 ⬆]    [⏸ Einfrieren]  [🗑 Löschen]
┌─────────────────────────────────────────────────────────────────────────────┐
│  3.0 ┤                    ╭──╮                                               │
│  2.0 ┤               ╭───╯  ╰──╮                                            │
│  1.0 ┤          ╭────╯         ╰─────╮                                      │
│  0.0 ┼──────────╯                    ╰────────                              │
│ -1.0 ┤                                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
Min: -1.234  |  Max: 3.014  |  Aktuell: 1.872  |  σ: 0.891
```

**Bedielelemente:**

| Element | Funktion |
|---|---|
| **Variable** | Dropdown: Kanal auswählen |
| **Punkte** | Anzahl sichtbarer Datenpunkte (50–500). Weniger = schnellerer Überblick |
| **⏸ Einfrieren** | Plot stoppt — Maus-Zoom und Pan möglich. Live-Queue läuft weiter! |
| **▶ Weiter** | Live-Anzeige fortsetzen |
| **🗑 Löschen** | Buffer leeren (z.B. nach Konfigurationsänderung) |

**Freeze-Modus — So nutzt du ihn:**

```
1. Roboter fährt → Plot läuft live
2. Interessantes Ereignis passiert (z.B. Ball-Verlust, Schleudern)
3. ⏸ Einfrieren drücken → Plot hält an
4. Mit Maus in die Kurve hineinzoomen (Scrollrad)
5. Mit Maus verschieben (Drag) → genaue Werte ablesen
6. ▶ Weiter → zurück zur Live-Ansicht
   (Während Freeze sind alle Pakete in der Queue gepuffert — kein Datenverlust!)
```

### 5.4 Typische Debug-Szenarien

#### Szenario A: Kompass-Drift prüfen

```
1. Tab Live-Plotter → Variable: "Compass_Heading"
2. Roboter auf Spielfeld stellen, Hand-Rotation durchführen
3. Kurve sollte 0→360 glatt durchlaufen ohne Sprünge
4. Bei Sprüngen: Kompass-Kalibrierung prüfen (Ch_COMPASS_RAW_X/Y beobachten)
```

#### Szenario B: PID-Regler einstellen

```
1. Tab Live-Plotter → Variable: "PID_Hdg_Error"
2. Roboter auf feste Ausrichtung fahren
3. Freeze → Überschwingen / Einschwingzeit messen
4. PID-Parameter im Code anpassen → neu flashen → wiederholen
5. Gleichzeitig Tab Tabelle: Min/Max von "PID_Hdg_Output" beobachten → Sättigung?
```

#### Szenario C: Ball-Sensor kalibrieren

```
1. Tab Live-Tabelle → Kanäle: Ball_Angle, Ball_Distance, Ball_Visible
2. Ball in verschiedene Positionen legen
3. Erwartete Winkel mit angezeigten Winkeln vergleichen
4. Offset-Kalibrierung im Code anpassen
```

#### Szenario D: Loop-Zeit überwachen

```
1. Tab Live-Plotter → Variable: "Loop_Time_us"
2. Sollte konstant niedrig sein (z.B. < 1000 µs bei 1kHz-Loop)
3. Spitzen = Code-Blockierungen (z.B. Serial.print(), I2C-Timeouts, voller TX-Buffer)
4. Min/Max in Tab Tabelle → maximale Loop-Zeit ablesen
```

#### Szenario E: Akku-Spannung überwachen (Spielbetrieb)

```
1. Tab Live-Tabelle → "Battery_Voltage" + "Battery_Percent"
2. Spalten Min/Max zeigen niedrigsten Wert unter Last
3. Bei Δ > 0.5V: Spannungseinbrüche durch Motorlast — Kondensatoren prüfen
```

---

## 6. Firmware flashen

Das System ermöglicht Over-the-Air Firmware-Updates vom PC aus — ohne USB-Kabel am Roboter.

### Ablauf

```
PC  ──USB-C──►  RPi 5  ──WiFi──►  RPi Zero W  ──USB──►  Teensy 4.0
     (Datei)   (verteilt)          (flasht)              (bootet neu)
```

### Schritte

**1. Firmware kompilieren (PlatformIO):**
```
VS Code → PlatformIO: Build  (Ctrl+Alt+B)
→ erzeugt: .pio/build/teensy40/firmware.hex
```

**2. GUI auf RPi 5 öffnen** (Steuerungsleiste):
```
Ziel wählen: ☑ Node 1  und/oder  ☑ Node 2
[⚡ Firmware flashen…] drücken
→ Datei-Dialog → firmware.hex auswählen
```

**3. Fortschritt beobachten:**
```
Statusleiste: "Flashe Node 1…"
Rote LED am RPi Zero: AN (Empfang) → 3× blinken (Erfolg)
Statusleiste: "✅ Node 1 Flash: OK"
```

**4. Teensy bootet automatisch neu** mit der neuen Firmware.

### Flash vom PC-Terminal (alternativ)

Wenn die GUI nicht verfügbar ist:

```bash
# Auf dem PC (USB-C an RPi 5)
python3 upload_firmware.py firmware.hex
# → flasht automatisch Node 1

python3 upload_firmware.py firmware.hex --both
# → flasht Node 1 + Node 2 parallel
```

### Troubleshooting Flash

| Problem | Ursache | Lösung |
|---|---|---|
| „Node nicht erreichbar" | RPi Zero offline | LED-Status prüfen, `ping 192.168.42.11` |
| „ERR: teensy_loader_cli not found" | Tool fehlt | `sudo apt install teensy-loader-cli` auf RPi Zero |
| „ERR: USB not found" | Teensy nicht per USB am RPi Zero | Micro-USB Kabel prüfen |
| Flash hängt nach 90s | Teensy bootet nicht neu | Teensy manuell per Reset-Knopf neustarten |
| Falsche MCU-Fehlermeldung | MCU-Typ falsch | `MCU = "TEENSY40"` in `flash_daemon.py` prüfen |

---

## 7. LED-Statusanzeige — Schnellreferenz

### RPi Zero W (am Roboter)

| LED | Muster | Bedeutung |
|:---:|---|---|
| 🟢 Grün | 3× kurz blinken beim Boot | Dienste bereit — alles OK |
| 🟢 Grün | 1× pro Sekunde blinken | System läuft normal |
| 🟢 Grün | Dauerhaft AN | Boot noch nicht abgeschlossen |
| 🟢 Grün | Aus | Dienst abgestürzt (`journalctl -u uart-receiver`) |
| 🔵 Blau | Dauerhaft AN | WLAN verbunden (RPi 5 erreichbar) |
| 🔵 Blau | 4× schnell | WLAN-Verbindungsaufbau |
| 🔵 Blau | Aus | Kein WLAN — RPi 5 noch nicht gestartet? |
| 🟡 Gelb | ~2× pro Sekunde | Teensy sendet Daten — alles korrekt |
| 🟡 Gelb | Aus | Kein Signal vom Teensy — Kabel prüfen! |
| 🔴 Rot | Dauerhaft AN | Flash läuft gerade |
| 🔴 Rot | 3× langsam | Flash erfolgreich ✅ |
| 🔴 Rot | 10× schnell | Flash fehlgeschlagen ❌ |
| 🔴 Rot | Aus | Normalbetrieb (kein Flash) |

### GUI auf RPi 5

| Anzeige | Bedeutung |
|---|---|
| ⬤ Grün (Node 1/2) | Pakete werden empfangen |
| ⬤ Rot (Node 1/2) | Seit > 3s keine Daten — Teensy oder RPi Zero offline |
| `X Pkt/s` (rechts unten) | Empfangsrate — sollte ~100 Pkt/s sein |

---

## 8. Troubleshooting

### Keine Daten in der GUI

```
Checkliste (von unten nach oben):

① Teensy läuft?
   → Serial Monitor in PlatformIO öffnen → Meldung "[Teensy] Bereit" sichtbar?
   → Gelbe LED am RPi Zero blinkt?

② UART-Verdrahtung korrekt?
   → Teensy Pin 1 (TX1)  → RPi Pin 10 (GPIO15, UART RX)
   → GND                 → RPi Pin  6 (GND)
   → Pegel 3,3 V? (kein 5V-Anschluss!)

③ UART-Receiver läuft?
   ssh pi@192.168.42.11
   journalctl -u uart-receiver -f
   → "Synchronisiert" oder "Throughput: X Pkt/s"?

④ WLAN verbunden?
   → Blaue LED AN?
   → ping 192.168.42.11 vom RPi 5 aus

⑤ UDP kommt an?
   sudo tcpdump -i wlan0 udp port 5001 -c 5 -q
   → Pakete sichtbar?
```

### Werte sehen falsch aus (z.B. alle 0 oder 9898)

```
① Sind die Kanäle in buildPacket() / debugData[] befüllt?
   → DBG()-Aufrufe vor dem SPI-Sende-Block?
   → Kanal-Nummer stimmt mit config.py überein?

② ACTIVE_CHANNELS zu niedrig?
   → In platformio.ini: -DACTIVE_CHANNELS=400 (Maximum bei UART)

③ Wert ist wirklich 0?
   → Motor evtl. nicht initialisiert? setup() prüfen
```

### Sehr hohe Loop-Zeit (CH_LOOP_TIME)

```
Typische Ursachen:
  • Serial.print() im Loop → durch Serial.printf() mit Bedingung ersetzen
  • I2C-Sensor hängt    → Timeout in Sensor-Bibliothek setzen
  • delay() im Loop     → durch Zeitstempel-Vergleich ersetzen (millis())
  • UART TX-Buffer voll   → Serial1.availableForWrite() auf USB-Serial prüfen
                            → _serial1_buf[4096] groß genug? Paket = 1608 Bytes

Diagnose:
  → Loop-Zeit vor und nach verdächtigen Codeabschnitten messen:
     DBG(CH_DEBUG_T1, micros());
     suspekterCode();
     DBG(CH_DEBUG_T2, micros());
     DBG(CH_DEBUG_DELTA, debugData[CH_DEBUG_T2] - debugData[CH_DEBUG_T1]);
```

### RPi Zero W verbindet sich nicht

```
① RPi 5 zuerst starten! (AP muss sichtbar sein)
② Passwort in setup_node.sh korrekt? (Standard: "HighSpeedDebug123")
③ Auf RPi Zero W:
   nmcli connection show PowerDebugAP
   nmcli connection up PowerDebugAP
```

---

## 9. Referenz: Kanalplan-Vorlage

Kopierfertige Vorlage für `debug_channels.h` und `config.py`:

### debug_channels.h (Teensy)

```cpp
#pragma once
// ────────────────────────────────────────────────────────────────────────────
//  Kanal-Definitionen — Power Debug System
//  Muss mit config.py auf dem RPi 5 synchron gehalten werden!
// ────────────────────────────────────────────────────────────────────────────

// Gruppe 0: Antrieb ── Kanäle 0–9
#define CH_MOTOR_L_SPEED    0
#define CH_MOTOR_R_SPEED    1
#define CH_MOTOR_L_PWM      2
#define CH_MOTOR_R_PWM      3
#define CH_MOTOR_L_ACTUAL   4
#define CH_MOTOR_R_ACTUAL   5

// Gruppe 1: Orientierung ── Kanäle 10–19
#define CH_COMPASS_HEADING  10
#define CH_COMPASS_RAW_X    11
#define CH_COMPASS_RAW_Y    12
#define CH_GYRO_Z           13
#define CH_TARGET_HEADING   14
#define CH_HEADING_ERROR    15

// Gruppe 2: Ball-Sensor ── Kanäle 20–29
#define CH_BALL_ANGLE       20
#define CH_BALL_DIST        21
#define CH_BALL_VISIBLE     22
#define CH_BALL_STRONGEST   23

// Gruppe 3: Liniensensor ── Kanäle 30–39
#define CH_LINE_FRONT       30
#define CH_LINE_BACK        31
#define CH_LINE_LEFT        32
#define CH_LINE_RIGHT       33
#define CH_LINE_POSITION    34

// Gruppe 4: PID Heading ── Kanäle 40–49
#define CH_PID_HDG_SP       40
#define CH_PID_HDG_IST      41
#define CH_PID_HDG_ERR      42
#define CH_PID_HDG_P        43
#define CH_PID_HDG_I        44
#define CH_PID_HDG_D        45
#define CH_PID_HDG_OUT      46

// Gruppe 5: PID Antrieb ── Kanäle 50–59
#define CH_PID_DRV_SP       50
#define CH_PID_DRV_OUT      51

// Gruppe 6: Kommunikation ── Kanäle 60–79
#define CH_PARTNER_X        60
#define CH_PARTNER_Y        61
#define CH_PARTNER_HEADING  62
#define CH_PARTNER_ACTIVE   63

// Gruppe 7: System / Diagnose ── Kanäle 80–99
#define CH_STATE            80
#define CH_LOOP_TIME        81
#define CH_BATTERY_V        82
#define CH_BATTERY_PCT      83
#define CH_UPTIME_S         84
#define CH_ERROR_FLAGS      85

// Gruppe 7: Freie Nutzung ── Kanäle 100–399
// (nach Bedarf belegen)

// Temporäre Debug-Kanäle (können jederzeit umbelegt werden)
#define CH_DEBUG_T1         490
#define CH_DEBUG_T2         491
#define CH_DEBUG_DELTA      492
#define CH_DEBUG_A          493
#define CH_DEBUG_B          494
#define CH_DEBUG_C          495
```

### config.py (RPi 5) — Namens-Block

```python
# In config.py nach der generischen VARIABLE_NAMES-Definition einfügen:

# Gruppe 0: Antrieb
VARIABLE_NAMES[0]  = "Motor_L_Speed"
VARIABLE_NAMES[1]  = "Motor_R_Speed"
VARIABLE_NAMES[2]  = "Motor_L_PWM"
VARIABLE_NAMES[3]  = "Motor_R_PWM"
VARIABLE_NAMES[4]  = "Motor_L_Actual"
VARIABLE_NAMES[5]  = "Motor_R_Actual"

# Gruppe 1: Orientierung
VARIABLE_NAMES[10] = "Compass_Heading"
VARIABLE_NAMES[11] = "Compass_Raw_X"
VARIABLE_NAMES[12] = "Compass_Raw_Y"
VARIABLE_NAMES[13] = "Gyro_Z"
VARIABLE_NAMES[14] = "Target_Heading"
VARIABLE_NAMES[15] = "Heading_Error"

# Gruppe 2: Ball
VARIABLE_NAMES[20] = "Ball_Angle"
VARIABLE_NAMES[21] = "Ball_Distance"
VARIABLE_NAMES[22] = "Ball_Visible"
VARIABLE_NAMES[23] = "Ball_Strongest_IR"

# Gruppe 3: Linie
VARIABLE_NAMES[30] = "Line_Front"
VARIABLE_NAMES[31] = "Line_Back"
VARIABLE_NAMES[32] = "Line_Left"
VARIABLE_NAMES[33] = "Line_Right"
VARIABLE_NAMES[34] = "Line_Position"

# Gruppe 4: PID Heading
VARIABLE_NAMES[40] = "PID_Hdg_Setpoint"
VARIABLE_NAMES[41] = "PID_Hdg_Istwert"
VARIABLE_NAMES[42] = "PID_Hdg_Error"
VARIABLE_NAMES[43] = "PID_Hdg_P"
VARIABLE_NAMES[44] = "PID_Hdg_I"
VARIABLE_NAMES[45] = "PID_Hdg_D"
VARIABLE_NAMES[46] = "PID_Hdg_Output"

# Gruppe 5: PID Antrieb
VARIABLE_NAMES[50] = "PID_Drive_Setpoint"
VARIABLE_NAMES[51] = "PID_Drive_Output"

# Gruppe 6: Kommunikation
VARIABLE_NAMES[60] = "Partner_X"
VARIABLE_NAMES[61] = "Partner_Y"
VARIABLE_NAMES[62] = "Partner_Heading"
VARIABLE_NAMES[63] = "Partner_Active"

# Gruppe 7: System
VARIABLE_NAMES[80] = "Robot_State"
VARIABLE_NAMES[81] = "Loop_Time_us"
VARIABLE_NAMES[82] = "Battery_Voltage"
VARIABLE_NAMES[83] = "Battery_Percent"
VARIABLE_NAMES[84] = "Uptime_s"
VARIABLE_NAMES[85] = "Error_Flags"

# Temporäre Debug-Kanäle
VARIABLE_NAMES[490] = "Debug_T1"
VARIABLE_NAMES[491] = "Debug_T2"
VARIABLE_NAMES[492] = "Debug_Delta"
VARIABLE_NAMES[493] = "Debug_A"
VARIABLE_NAMES[494] = "Debug_B"
VARIABLE_NAMES[495] = "Debug_C"
```

---

> **Weitere Details** zur Hardware-Einrichtung: `SETUP_GUIDE.md`  
> **Entwickler-Dokumentation** (Architektur, neue Hardware integrieren): `DEVELOPER_README.md`  
> **Netzwerk-Konfiguration** im Detail: `network_setup.md`
