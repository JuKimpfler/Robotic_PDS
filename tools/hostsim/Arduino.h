#pragma once
/*
 * tools/hostsim/Arduino.h — minimale Arduino-Attrappe für den PC
 * ================================================================
 * Erlaubt es, teensy_firmware/src/PDS.cpp mit einem gewöhnlichen g++ zu
 * übersetzen und AUSZUFÜHREN. Damit lässt sich der Deskriptor-JSON, den der
 * Teensy an die GUI schickt, ohne Hardware erzeugen und gegen einen echten
 * JSON-Parser prüfen (siehe tools/desc_json_check.py).
 *
 * Warum das den Aufwand wert ist: der Deskriptor wird von Hand in einen
 * Zeichenpuffer geschrieben, mit Überlaufreserve und abgeschnittenen Listen.
 * Ein Komma zu viel oder eine fehlende Klammer macht ihn unlesbar — und in
 * der GUI äußert sich das nur als "die Kanalnamen kommen nicht an". Genau
 * dieser Fehler ist in diesem Projekt schon einmal aufgetreten.
 *
 * Bewusst NUR so viel, wie PDS.cpp/PDS.h tatsächlich benutzen. Das hier ist
 * kein Arduino-Ersatz.
 */

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <math.h>
#include <vector>
#include <deque>

// ── Steuerbare Uhr ────────────────────────────────────────────────────────
//  Der Test soll Zeit vergehen lassen können, ohne wirklich zu warten.
extern unsigned long pds_sim_millis;
extern unsigned long pds_sim_micros;

// Um so viel rueckt micros() bei JEDEM Aufruf weiter. 0 = die Uhr steht
// still (Standard, macht die Ausgabe reproduzierbar). Mit einem Wert > 0
// laesst sich das Zeitbudget von PDS.update() wirklich ausreizen — sonst
// bliebe der scheibenweise Deskriptor-Bau ungetestet, weil ohne
// vergehende Zeit nie ein Budget aufgebraucht wird.
extern unsigned long pds_sim_micros_step;

inline unsigned long millis() { return pds_sim_millis; }
inline unsigned long micros() {
    pds_sim_micros += pds_sim_micros_step;
    return pds_sim_micros;
}

inline void pds_sim_advance(unsigned long ms) {
    pds_sim_millis += ms;
    pds_sim_micros += ms * 1000UL;
}

// ── Print / Serial ────────────────────────────────────────────────────────
class Print {
public:
    virtual ~Print() {}
    virtual size_t write(const uint8_t* buf, size_t len) { (void)buf; return len; }
    size_t print(const char* s) { fputs(s, stdout); return strlen(s); }
    size_t println(const char* s) { fputs(s, stdout); fputc('\n', stdout); return strlen(s) + 1; }
    int printf(const char* fmt, ...) {
        va_list a; va_start(a, fmt);
        const int n = vfprintf(stdout, fmt, a);
        va_end(a);
        return n;
    }
};

class UsbSerial : public Print {
public:
    void begin(unsigned long) {}
    // In der Attrappe ist nie ein Terminal offen — genau wie im Roboter,
    // wenn der Teensy ohne USB-Kabel läuft. pdsWarn() gibt dann nichts aus.
    explicit operator bool() const { return false; }
    // Wird von serialRoomFor() in PDS.cpp abgefragt: die Bibliothek schreibt
    // nur nach USB-Serial, wenn dort auch Platz ist (ein volles USB-CDC
    // blockiert auf dem echten Teensy bis zu 120 ms).
    int availableForWrite() { return 0; }
};
extern UsbSerial Serial;

static const int SERIAL_8N1 = 0;

// ── HardwareSerial: sammelt alles Geschriebene in einem Puffer ────────────
class HardwareSerial : public Print {
public:
    std::vector<uint8_t> tx;
    std::deque<uint8_t>  rx;                   // was der Node "geschickt" hat

    void begin(unsigned long, int = SERIAL_8N1) {}
    void addMemoryForWrite(void*, size_t) {}
    void addMemoryForRead(void*, size_t) {}
    int availableForWrite() { return 8192; }   // nie voll -> nichts wird verworfen

    /// Bytes in den Empfangspuffer legen — damit laesst sich der
    /// Param-Downlink (auch ein abgebrochenes Paket) nachstellen.
    void feed(const void* data, size_t n) {
        const uint8_t* p = (const uint8_t*)data;
        rx.insert(rx.end(), p, p + n);
    }

    int available() { return (int)rx.size(); }
    int read() {
        if (rx.empty()) return -1;
        const int b = rx.front();
        rx.pop_front();
        return b;
    }

    size_t write(const uint8_t* buf, size_t len) override {
        tx.insert(tx.end(), buf, buf + len);
        return len;
    }
};
extern HardwareSerial Serial3;
