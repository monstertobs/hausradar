#pragma once
/*
 * HLK-LD2450 Frame-Parser
 *
 * Protokoll (30 Bytes pro Frame):
 *   [0..3]   Header:  AA FF 03 00
 *   [4..11]  Ziel 1   (8 Bytes)
 *   [12..19] Ziel 2   (8 Bytes)
 *   [20..27] Ziel 3   (8 Bytes)
 *   [28..29] Tail:    55 CC
 *
 * Kodierung je Ziel (8 Bytes, little-endian):
 *   Bytes 0-1  X-Koordinate [mm]:  Bit15=0 → positiv (rechts), Bit15=1 → negativ (links)
 *   Bytes 2-3  Y-Koordinate [mm]:  Bit15=1 → positiv (vor Sensor), Bit15=0 → negativ
 *                                  ACHTUNG: Y hat UMGEKEHRTE Sign-Bit-Logik gegenüber X!
 *                                  In der Praxis immer positiv (Ziele immer vor dem Sensor).
 *   Bytes 4-5  Geschwindigkeit [mm/s]: gleiche Kodierung wie X (pos=weg, neg=hin)
 *   Bytes 6-7  Auflösung [mm]: Messgate-Breite (unsigned)
 *
 * Kein Ziel (leerer Slot): X == 0 AND Y == 0 AND Speed == 0
 */

#include <stdint.h>
#include <math.h>

namespace LD2450 {

static constexpr uint8_t FRAME_LEN   = 30;
static constexpr uint8_t MAX_TARGETS =  3;

struct Target {
    int16_t  x_mm;
    int16_t  y_mm;
    int16_t  speed_mm_s;
    uint16_t resolution_mm;
    bool     active;

    float distance_mm() const {
        return sqrtf((float)x_mm * (float)x_mm + (float)y_mm * (float)y_mm);
    }

    float angle_deg() const {
        float d = distance_mm();
        return (d > 1.0f) ? atan2f((float)x_mm, (float)y_mm) * 180.0f / (float)M_PI : 0.0f;
    }
};

struct Frame {
    Target  targets[MAX_TARGETS];
    uint8_t target_count;
};

// Dekodiert X / Speed: Bit15=1 → negativ, Bit15=0 → positiv
static inline int16_t decodeCoordX(uint16_t raw) {
    return (raw & 0x8000u) ? -(int16_t)(raw & 0x7FFFu)
                           :  (int16_t)(raw & 0x7FFFu);
}

// Dekodiert Y: Bit15=1 → positiv (vor dem Sensor), Bit15=0 → negativ
// Umgekehrte Sign-Bit-Logik gegenüber X – so liefert der LD2450 die Y-Achse.
static inline int16_t decodeCoordY(uint16_t raw) {
    return (raw & 0x8000u) ?  (int16_t)(raw & 0x7FFFu)
                           : -(int16_t)(raw & 0x7FFFu);
}

// Parst einen vollständigen 30-Byte-Frame.
// Gibt true zurück wenn Header und Tail korrekt sind.
static bool parse(const uint8_t* buf, Frame& out) {
    if (buf[0] != 0xAA || buf[1] != 0xFF || buf[2] != 0x03 || buf[3] != 0x00)
        return false;
    if (buf[28] != 0x55 || buf[29] != 0xCC)
        return false;

    out.target_count = 0;
    for (uint8_t i = 0; i < MAX_TARGETS; i++) {
        const uint8_t* p = buf + 4 + i * 8;
        uint16_t rx = (uint16_t)p[0] | ((uint16_t)p[1] << 8);
        uint16_t ry = (uint16_t)p[2] | ((uint16_t)p[3] << 8);
        uint16_t rs = (uint16_t)p[4] | ((uint16_t)p[5] << 8);
        uint16_t rr = (uint16_t)p[6] | ((uint16_t)p[7] << 8);

        out.targets[i] = {
            decodeCoordX(rx),
            decodeCoordY(ry),
            decodeCoordX(rs),
            rr,
            (rx != 0 || ry != 0 || rs != 0),
        };
        if (out.targets[i].active) out.target_count++;
    }
    return true;
}

} // namespace LD2450
