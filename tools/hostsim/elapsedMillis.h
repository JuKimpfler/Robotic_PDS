#pragma once
// Minimale Nachbildung der Teensyduino-Klasse elapsedMillis fuer den
// Host-Test (siehe tools/hostsim/Arduino.h).
#include "Arduino.h"

class elapsedMillis {
private:
    unsigned long ms;
public:
    elapsedMillis() : ms(millis()) {}
    operator unsigned long() const { return millis() - ms; }
    elapsedMillis& operator=(unsigned long val) { ms = millis() - val; return *this; }
    elapsedMillis& operator-=(unsigned long val) { ms += val; return *this; }
};
