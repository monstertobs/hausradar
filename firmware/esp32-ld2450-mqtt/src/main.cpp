/*
 * HausRadar – ESP32 Sensor-Firmware  (Milestone 12 + 13)
 *
 * Zwei Build-Modes über PlatformIO-Environment:
 *
 *   pio run -e esp32dev         → echter HLK-LD2450 via UART2
 *   pio run -e esp32dev-sim     → Walker-Simulation (kein Sensor nötig)
 *
 * Alle Einstellungen in include/config.h anpassen.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <math.h>
#include <time.h>
#include "config.h"

#ifndef SIMULATE
#include "ld2450.h"
#endif

// =============================================================================
// Walker – Personensimulation (nur SIMULATE-Build)
// =============================================================================

#ifdef SIMULATE

struct Walker {
    float x, y;
    float vx, vy;

    static constexpr float SPEED_MIN       = 80.0f;
    static constexpr float SPEED_MAX       = 300.0f;
    static constexpr float DIR_CHANGE_PROB = 0.04f;
    static constexpr float DIR_CHANGE_MAX  = 0.6f;
    static constexpr float MARGIN          = 0.15f;

    void init() {
        float w = ROOM_WIDTH_MM, h = ROOM_HEIGHT_MM;
        x = MARGIN * w + (float)esp_random() / (float)UINT32_MAX * w * (1.0f - 2.0f * MARGIN);
        y = MARGIN * h + (float)esp_random() / (float)UINT32_MAX * h * (1.0f - 2.0f * MARGIN);
        float spd = SPEED_MIN + (float)esp_random() / (float)UINT32_MAX * (SPEED_MAX - SPEED_MIN);
        float ang = (float)esp_random() / (float)UINT32_MAX * 2.0f * (float)M_PI;
        vx = spd * cosf(ang);
        vy = spd * sinf(ang);
    }

    void step(float dt) {
        x += vx * dt;  y += vy * dt;
        float w = ROOM_WIDTH_MM, h = ROOM_HEIGHT_MM;
        if      (x < 0) { x  = -x;        vx =  fabsf(vx); }
        else if (x > w) { x  = 2.0f*w-x;  vx = -fabsf(vx); }
        if      (y < 0) { y  = -y;        vy =  fabsf(vy); }
        else if (y > h) { y  = 2.0f*h-y;  vy = -fabsf(vy); }
        if ((float)esp_random() / (float)UINT32_MAX < DIR_CHANGE_PROB) {
            float delta = ((float)esp_random() / (float)UINT32_MAX - 0.5f) * 2.0f * DIR_CHANGE_MAX;
            float s = sqrtf(vx*vx + vy*vy);
            float a = atan2f(vy, vx) + delta;
            vx = s * cosf(a);  vy = s * sinf(a);
        }
    }

    float speed() const { return sqrtf(vx*vx + vy*vy); }
};

static Walker walker;

// Raum- → Sensorkoordinaten (Inverse Transformation aus coordinate_transform.py)
static void roomToSensor(float rx, float ry, float& xs, float& ys) {
    float theta = SENSOR_ROTATION_DEG * (float)M_PI / 180.0f;
    float dx = rx - SENSOR_X_MM;
    float dy = ry - SENSOR_Y_MM;
    xs = dx * cosf(theta) - dy * sinf(theta);
    ys = dx * sinf(theta) + dy * cosf(theta);
    if (ys < 0.0f) ys = 0.0f;
}

#endif  // SIMULATE

// =============================================================================
// LD2450 UART-Empfang (nur Real-Build)
// =============================================================================

#ifndef SIMULATE

static HardwareSerial  _ld2450Serial(2);   // UART2
static uint8_t         _frameBuf[LD2450::FRAME_LEN];
static uint8_t         _frameBufPos = 0;
static LD2450::Frame   _lastFrame   = {};
static bool            _frameReady  = false;

// Liest verfügbare Bytes und assembliert vollständige Frames.
// Header-Synchronisation: Bytes werden verworfen bis AA FF 03 00 gesehen wird.
static void readLD2450() {
    static const uint8_t HDR[4] = {0xAA, 0xFF, 0x03, 0x00};

    while (_ld2450Serial.available()) {
        uint8_t b = (uint8_t)_ld2450Serial.read();

        if (_frameBufPos < 4) {
            // Header-Byte prüfen
            if (b == HDR[_frameBufPos]) {
                _frameBuf[_frameBufPos++] = b;
            } else {
                // Resync: neuer Versuch ab 0xAA
                _frameBufPos = (b == 0xAA) ? 1 : 0;
                if (_frameBufPos) _frameBuf[0] = b;
            }
        } else {
            _frameBuf[_frameBufPos++] = b;
            if (_frameBufPos == LD2450::FRAME_LEN) {
                _frameBufPos = 0;
                if (LD2450::parse(_frameBuf, _lastFrame)) {
                    _frameReady = true;
                }
            }
        }
    }
}

#endif  // !SIMULATE

// =============================================================================
// Gemeinsame Hilfsfunktionen
// =============================================================================

// Unix-Timestamp [ms]: NTP wenn verfügbar, sonst millis()-Fallback
static int64_t getTimestampMs() {
    time_t t = time(nullptr);
    if (t > 1000000000L) return (int64_t)t * 1000LL;
    return 1700000000000LL + (int64_t)millis();
}

// =============================================================================
// Globale Objekte
// =============================================================================

static WiFiClient   wifiClient;
static PubSubClient mqttClient(wifiClient);

static unsigned long lastPublish = 0;
static unsigned long lastStep    = 0;

// =============================================================================
// WiFi-Verbindung
// =============================================================================

static void connectWifi() {
    if (WiFi.status() == WL_CONNECTED) return;

    Serial.printf("\n[WiFi] Verbinde mit \"%s\" …", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long deadline = millis() + 15000UL;
    while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
        delay(300);
        Serial.print('.');
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Verbunden  IP: %s\n",
                      WiFi.localIP().toString().c_str());
#ifdef NTP_SERVER
        configTime(NTP_UTC_OFFSET_S, 0, NTP_SERVER);
        Serial.printf("[NTP]  Synchronisiere mit %s …\n", NTP_SERVER);
        delay(200);
#endif
    } else {
        Serial.println("\n[WiFi] Verbindung fehlgeschlagen.");
    }
}

// =============================================================================
// MQTT-Verbindung
// =============================================================================

static void connectMqtt() {
    if (mqttClient.connected()) return;

    Serial.printf("[MQTT] Verbinde mit %s:%d …\n", MQTT_HOST, MQTT_PORT);
    // MQTT_USER / MQTT_PASSWORD aus config.h (leer = anonyme Verbindung)
    const char* user = (strlen(MQTT_USER) > 0) ? MQTT_USER : nullptr;
    const char* pass = (strlen(MQTT_PASSWORD) > 0) ? MQTT_PASSWORD : nullptr;
    if (mqttClient.connect(MQTT_CLIENT_ID, user, pass)) {
        Serial.println("[MQTT] Verbunden.");
    } else {
        Serial.printf("[MQTT] Fehlgeschlagen (state=%d) – Retry in 5 s\n",
                      mqttClient.state());
        delay(5000);
    }
}

// =============================================================================
// Payload bauen und senden
// =============================================================================

static void publishPayload() {
    StaticJsonDocument<512> doc;
    doc["sensor_id"]    = SENSOR_ID;
    doc["room_id"]      = ROOM_ID;
    doc["timestamp_ms"] = getTimestampMs();
    JsonArray targets   = doc.createNestedArray("targets");

#ifdef SIMULATE
    float xs, ys;
    roomToSensor(walker.x, walker.y, xs, ys);
    float dist  = sqrtf(xs*xs + ys*ys);
    float angle = (dist > 1.0f) ? atan2f(xs, ys) * 180.0f / (float)M_PI : 0.0f;

    JsonObject t = targets.createNestedObject();
    t["id"]          = 1;
    t["x_mm"]        = roundf(xs          * 10.0f)  / 10.0f;
    t["y_mm"]        = roundf(ys          * 10.0f)  / 10.0f;
    t["speed_mm_s"]  = roundf(walker.speed() * 10.0f) / 10.0f;
    t["distance_mm"] = roundf(dist        * 10.0f)  / 10.0f;
    t["angle_deg"]   = roundf(angle       * 100.0f) / 100.0f;
    doc["target_count"] = 1;

    Serial.printf("[SIM] Raum (%5.0f,%5.0f) mm → Sensor (%5.0f,%5.0f) mm  "
                  "v=%.0f mm/s\n", walker.x, walker.y, xs, ys, walker.speed());

#else   // Real LD2450
    uint8_t count = 0;
    for (uint8_t i = 0; i < LD2450::MAX_TARGETS; i++) {
        const LD2450::Target& tgt = _lastFrame.targets[i];
        if (!tgt.active) continue;
        JsonObject t = targets.createNestedObject();
        t["id"]          = (int)(i + 1);
        t["x_mm"]        = (int)tgt.x_mm;
        t["y_mm"]        = (int)tgt.y_mm;
        t["speed_mm_s"]  = (int)tgt.speed_mm_s;
        t["distance_mm"] = roundf(tgt.distance_mm() * 10.0f) / 10.0f;
        t["angle_deg"]   = roundf(tgt.angle_deg()   * 100.0f) / 100.0f;
        count++;
    }
    doc["target_count"] = count;
    _frameReady = false;

    Serial.printf("[LD2450] %d Ziel(e)\n", count);
#endif

    char buf[512];
    serializeJson(doc, buf);
    if (!mqttClient.publish(MQTT_TOPIC, buf)) {
        Serial.println("[MQTT] publish fehlgeschlagen.");
    }
}

// =============================================================================
// Arduino-Einstiegspunkte
// =============================================================================

void setup() {
    Serial.begin(115200);
    delay(100);

#ifdef SIMULATE
    Serial.println("\nHausRadar Fake-Sensor (Walker-Simulation)");
    Serial.printf("  Sensor: %s  Raum: %s  (%.0f x %.0f mm)\n",
                  SENSOR_ID, ROOM_ID, ROOM_WIDTH_MM, ROOM_HEIGHT_MM);
    walker.init();
#else
    Serial.println("\nHausRadar LD2450-Sensor");
    Serial.printf("  Sensor: %s  Raum: %s  UART2 RX=GPIO%d  %d Baud\n",
                  SENSOR_ID, ROOM_ID, LD2450_RX_PIN, LD2450_BAUD);
    _ld2450Serial.begin(LD2450_BAUD, SERIAL_8N1, LD2450_RX_PIN, LD2450_TX_PIN);
    delay(100);  // Sensor braucht kurz nach UART-Init
    Serial.println("[LD2450] Aktiviere Multi-Target-Modus …");
    LD2450::configureMultiTarget(_ld2450Serial);
    Serial.println("[LD2450] Konfiguration gesendet.");
#endif

    lastStep    = millis();
    lastPublish = millis();

    connectWifi();
    mqttClient.setServer(MQTT_HOST, MQTT_PORT);
    mqttClient.setBufferSize(512);
    connectMqtt();
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) { connectWifi(); return; }
    if (!mqttClient.connected())        { connectMqtt(); return; }
    mqttClient.loop();

    unsigned long now = millis();

#ifdef SIMULATE
    // Walker-Schritt
    float dt = (float)(now - lastStep) / 1000.0f;
    lastStep = now;
    walker.step(dt);
#else
    // LD2450-Bytes lesen (so oft wie möglich, nicht nur zum Publish-Zeitpunkt)
    readLD2450();
    lastStep = now;
#endif

    // Im konfigurierten Intervall senden
    if (now - lastPublish >= PUBLISH_INTERVAL_MS) {
        lastPublish = now;
#ifndef SIMULATE
        // Nur senden wenn ein neuer Frame vorliegt
        if (!_frameReady) return;
#endif
        publishPayload();
    }
}
