/*
 * tools/teensy_bind_types_test.cpp
 * ---------------------------------
 * Uebersetzungs-Test (wird nie geflasht): stellt sicher, dass PDS.track() und
 * PDS.bind() JEDEN gebraeuchlichen Zahlentyp annehmen.
 *
 * Hintergrund: die Ueberladungen liefen frueher auf int8_t/int16_t/int32_t.
 * Das sind aber nur Aliase — auf dem Teensy ist int32_t == long, und ein ganz
 * gewoehnliches
 *      int heading;  PDS.track("Heading", &heading);
 * hat deshalb NICHT uebersetzt, sondern eine seitenlange Kandidatenliste
 * ausgegeben. Seit Version 2.1 laufen die Ueberladungen auf den fundamentalen
 * Typen; diese Datei haelt das fest.
 *
 * Aufruf: ueber tools/build_teensy_check.sh (Konfiguration 4).
 */
#include "PDS.h"

static float              v_float;
static double             v_double;
static bool               v_bool;
static char               v_char_unused;      // absichtlich NICHT gebunden
static signed char        v_schar;
static unsigned char      v_uchar;
static short              v_short;
static unsigned short     v_ushort;
static int                v_int;
static unsigned int       v_uint;
static long               v_long;
static unsigned long      v_ulong;
static long long          v_llong;
static unsigned long long v_ullong;

// Die Festbreiten-Aliase muessen weiterhin funktionieren.
static int8_t   v_i8;
static uint8_t  v_u8;
static int16_t  v_i16;
static uint16_t v_u16;
static int32_t  v_i32;
static uint32_t v_u32;
static size_t   v_size;

void pds_bind_type_coverage() {
    (void)v_char_unused;

    // track(): Kanal automatisch
    PDS.track("f",      &v_float, "V");
    PDS.track("d",      &v_double);
    PDS.track("b",      &v_bool);
    PDS.track("schar",  &v_schar);
    PDS.track("uchar",  &v_uchar);
    PDS.track("short",  &v_short);
    PDS.track("ushort", &v_ushort);
    PDS.track("int",    &v_int);
    PDS.track("uint",   &v_uint);
    PDS.track("long",   &v_long);
    PDS.track("ulong",  &v_ulong);
    PDS.track("llong",  &v_llong);
    PDS.track("ullong", &v_ullong);

    // bind(): Kanal zuerst
    PDS.bind(0, &v_i8,  "i8");
    PDS.bind(1, &v_u8,  "u8");
    PDS.bind(2, &v_i16, "i16");
    PDS.bind(3, &v_u16, "u16");
    PDS.bind(4, &v_i32, "i32");
    PDS.bind(5, &v_u32, "u32");
    PDS.bind(6, &v_size, "size_t");

    // bind(): Name zuerst, Kanal als drittes Argument (mit/ohne Einheit)
    PDS.bind("i8_b",  &v_i8,    7);
    PDS.bind("f_b",   &v_float, 8, "V");
    PDS.bind("int_b", &v_int,   9, "cm");

    // Zahlentypen bei den Schreibfunktionen
    PDS.plot("p_int", v_int);
    PDS.plot("p_u8",  v_u8, "%");
    PDS.channel(10, v_llong);
    PDS.Channel(11, (float)v_double, "c_double");
    PDS_PLOT("macro", v_short);
}
