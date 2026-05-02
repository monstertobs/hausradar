/*
 * HausRadar – ESP32 Sensor-Firmware
 *
 * ERSTER START / RESET:
 *   Der ESP32 öffnet einen WLAN-Hotspot „HausRadar-Setup".
 *   Handy oder Laptop damit verbinden → Browser öffnet 192.168.4.1.
 *   WLAN-Daten, Pi-IP und Sensor-ID eingeben → Speichern → fertig.
 *
 *   Zurück zum Einrichtungsmodus: BOOT-Taste (GPIO 0) beim Start
 *   3 Sekunden gedrückt halten.
 *
 * BUILD-MODES:
 *   pio run -e esp32dev        → echter HLK-LD2450 via UART2
 *   pio run -e esp32dev-sim    → Walker-Simulation (kein Sensor nötig)
 *
 * Hardware-Konstanten (Pins, Baudrate, Simulationsraum) weiterhin in config.h.
 * Alles Netzwerk-Spezifische wird im NVS (Flash) gespeichert.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <math.h>
#include <time.h>
#include "config.h"

#ifndef SIMULATE
#include "ld2450.h"
#endif

// =============================================================================
// Konfigurationsstruktur (aus NVS geladen)
// =============================================================================

struct SensorConfig {
    char ssid[64];
    char wifi_pass[64];
    char mqtt_host[64];
    char mqtt_user[32];
    char mqtt_pass[32];
    char sensor_id[64];
    char room_id[64];
};

static SensorConfig cfg;
static bool         _provMode = false;   // true = AP-Einrichtungsmodus

// NVS-Namespace
static Preferences prefs;

static bool loadConfig() {
    prefs.begin("hausradar", /*readOnly=*/true);
    bool valid = prefs.getString("ssid", cfg.ssid, sizeof(cfg.ssid)) > 0
              && prefs.getString("sensor_id", cfg.sensor_id, sizeof(cfg.sensor_id)) > 0;
    prefs.getString("wifi_pass",  cfg.wifi_pass,  sizeof(cfg.wifi_pass));
    prefs.getString("mqtt_host",  cfg.mqtt_host,  sizeof(cfg.mqtt_host));
    prefs.getString("mqtt_user",  cfg.mqtt_user,  sizeof(cfg.mqtt_user));
    prefs.getString("mqtt_pass",  cfg.mqtt_pass,  sizeof(cfg.mqtt_pass));
    prefs.getString("room_id",    cfg.room_id,    sizeof(cfg.room_id));
    prefs.end();
    return valid;
}

static void saveConfig() {
    prefs.begin("hausradar", /*readOnly=*/false);
    prefs.putString("ssid",      cfg.ssid);
    prefs.putString("wifi_pass", cfg.wifi_pass);
    prefs.putString("mqtt_host", cfg.mqtt_host);
    prefs.putString("mqtt_user", cfg.mqtt_user);
    prefs.putString("mqtt_pass", cfg.mqtt_pass);
    prefs.putString("sensor_id", cfg.sensor_id);
    prefs.putString("room_id",   cfg.room_id);
    prefs.end();
}

static void clearConfig() {
    prefs.begin("hausradar", false);
    prefs.clear();
    prefs.end();
}

// MQTT-Topic aus Sensor-ID ableiten
static void buildTopic(char* buf, size_t len) {
    snprintf(buf, len, "hausradar/sensor/%s/state", cfg.sensor_id);
}
static void buildClientId(char* buf, size_t len) {
    snprintf(buf, len, "hausradar-%s", cfg.sensor_id);
}

// =============================================================================
// Walker – Personensimulation (nur SIMULATE-Build)
// =============================================================================

#ifdef SIMULATE

struct Walker {
    float x, y, vx, vy;

    static constexpr float SPEED_MIN       = 80.0f;
    static constexpr float SPEED_MAX       = 300.0f;
    static constexpr float DIR_CHANGE_PROB = 0.04f;
    static constexpr float DIR_CHANGE_MAX  = 0.6f;
    static constexpr float MARGIN          = 0.15f;

    void init() {
        float w = ROOM_WIDTH_MM, h = ROOM_HEIGHT_MM;
        x  = MARGIN*w + (float)esp_random()/UINT32_MAX * w*(1.0f-2.0f*MARGIN);
        y  = MARGIN*h + (float)esp_random()/UINT32_MAX * h*(1.0f-2.0f*MARGIN);
        float spd = SPEED_MIN + (float)esp_random()/UINT32_MAX*(SPEED_MAX-SPEED_MIN);
        float ang = (float)esp_random()/UINT32_MAX * 2.0f*(float)M_PI;
        vx = spd*cosf(ang); vy = spd*sinf(ang);
    }

    void step(float dt) {
        x += vx*dt; y += vy*dt;
        float w = ROOM_WIDTH_MM, h = ROOM_HEIGHT_MM;
        if      (x < 0) { x  = -x;       vx =  fabsf(vx); }
        else if (x > w) { x  = 2.0f*w-x; vx = -fabsf(vx); }
        if      (y < 0) { y  = -y;       vy =  fabsf(vy); }
        else if (y > h) { y  = 2.0f*h-y; vy = -fabsf(vy); }
        if ((float)esp_random()/UINT32_MAX < DIR_CHANGE_PROB) {
            float delta = ((float)esp_random()/UINT32_MAX - 0.5f)*2.0f*DIR_CHANGE_MAX;
            float s = sqrtf(vx*vx+vy*vy), a = atan2f(vy,vx)+delta;
            vx = s*cosf(a); vy = s*sinf(a);
        }
    }
    float speed() const { return sqrtf(vx*vx+vy*vy); }
};

static Walker walker;

static void roomToSensor(float rx, float ry, float& xs, float& ys) {
    float theta = SENSOR_ROTATION_DEG*(float)M_PI/180.0f;
    float dx = rx - SENSOR_X_MM, dy = ry - SENSOR_Y_MM;
    xs = dx*cosf(theta) - dy*sinf(theta);
    ys = dx*sinf(theta) + dy*cosf(theta);
    if (ys < 0.0f) ys = 0.0f;
}

#endif  // SIMULATE

// =============================================================================
// LD2450 UART-Empfang (nur Real-Build)
// =============================================================================

#ifndef SIMULATE

static HardwareSerial _ld2450Serial(2);
static uint8_t        _frameBuf[LD2450::FRAME_LEN];
static uint8_t        _frameBufPos = 0;
static LD2450::Frame  _lastFrame   = {};
static bool           _frameReady  = false;

static void readLD2450() {
    static const uint8_t HDR[4] = {0xAA, 0xFF, 0x03, 0x00};
    while (_ld2450Serial.available()) {
        uint8_t b = (uint8_t)_ld2450Serial.read();
        if (_frameBufPos < 4) {
            if (b == HDR[_frameBufPos]) { _frameBuf[_frameBufPos++] = b; }
            else { _frameBufPos = (b == 0xAA) ? 1 : 0; if (_frameBufPos) _frameBuf[0]=b; }
        } else {
            _frameBuf[_frameBufPos++] = b;
            if (_frameBufPos == LD2450::FRAME_LEN) {
                _frameBufPos = 0;
                if (LD2450::parse(_frameBuf, _lastFrame)) _frameReady = true;
            }
        }
    }
}

#endif  // !SIMULATE

// =============================================================================
// AP-Modus: Einrichtungsseite
// =============================================================================

// HTML-Seite im Flash (PROGMEM) speichern
static const char SETUP_HTML[] PROGMEM = R"html(
<!DOCTYPE html><html lang="de"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HausRadar – Sensor einrichten</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e2e4ec;padding:20px;max-width:480px;margin:0 auto}
h1{color:#22d3ee;font-size:1.15rem;margin-bottom:4px}
.sub{color:#6b7280;font-size:.8rem;margin-bottom:24px}
label{display:block;margin-top:16px;font-size:.8rem;color:#6b7280;text-transform:uppercase;letter-spacing:.05em}
input{display:block;width:100%;padding:9px 12px;margin-top:5px;background:#1a1d27;border:1px solid #2a2d3a;border-radius:6px;color:#e2e4ec;font-size:.95rem}
input:focus{outline:none;border-color:#3b82f6}
.hint{font-size:.75rem;color:#4b5563;margin-top:4px;line-height:1.4}
.sep{border:none;border-top:1px solid #2a2d3a;margin:20px 0}
button{margin-top:24px;width:100%;padding:13px;background:#3b82f6;border:none;border-radius:8px;color:#fff;font-size:1rem;font-weight:600;cursor:pointer}
button:active{background:#2563eb}
.val{color:#22c55e;font-weight:normal}
</style></head><body>
<h1>📡 HausRadar – Sensor einrichten</h1>
<p class="sub">Verbunden mit Hotspot <strong>HausRadar-Setup</strong></p>
<form method="POST" action="/save">
<label>WLAN-Name (SSID) <input type="text" name="ssid" value="%SSID%" required autocomplete="off"></label>
<label>WLAN-Passwort <input type="password" name="wifi_pass" value="%PASS%" autocomplete="off"></label>
<hr class="sep">
<label>HausRadar-IP (Raspberry Pi)
  <input type="text" name="mqtt_host" value="%MQTT_HOST%" placeholder="192.168.178.100" required>
  <div class="hint">IP-Adresse des Pi – sichtbar unter Einstellungen → System-Status → Backend</div>
</label>
<hr class="sep">
<label>Sensor-ID
  <input type="text" name="sensor_id" value="%SENSOR_ID%" placeholder="radar_keller" required autocomplete="off">
  <div class="hint">Sichtbar in HausRadar → Einstellungen → Sensoren → MQTT-Topic<br>
  z.B. <em>hausradar/sensor/<strong>radar_keller</strong>/state</em></div>
</label>
<label>Raum-ID
  <input type="text" name="room_id" value="%ROOM_ID%" placeholder="keller" required autocomplete="off">
  <div class="hint">Kleinschreibung, keine Leerzeichen – muss mit dem Raum in HausRadar übereinstimmen</div>
</label>
<hr class="sep">
<label>MQTT-Benutzername (optional) <input type="text" name="mqtt_user" value="%MQTT_USER%" autocomplete="off"></label>
<label>MQTT-Passwort (optional) <input type="password" name="mqtt_pass" value="%MQTT_PASS%" autocomplete="off"></label>
<button type="submit">💾 Speichern &amp; Neustart</button>
</form></body></html>
)html";

static const char SAVED_HTML[] PROGMEM = R"html(
<!DOCTYPE html><html lang="de"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HausRadar – Gespeichert</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e2e4ec;
     padding:40px 20px;max-width:480px;margin:0 auto;text-align:center}
h1{color:#22c55e;font-size:1.2rem;margin-bottom:12px}
p{color:#6b7280;font-size:.9rem;line-height:1.6}
code{color:#22d3ee;background:#1a1d27;padding:2px 6px;border-radius:4px;font-size:.85rem}
</style></head><body>
<h1>✅ Gespeichert!</h1>
<p>Der Sensor startet jetzt neu und verbindet sich mit deinem WLAN.<br><br>
In etwa 10 Sekunden erscheint <code>%SENSOR_ID%</code> in<br>
HausRadar → Einstellungen → Sensoren als <strong style="color:#22c55e">online</strong>.</p>
</body></html>
)html";

static WebServer webServer(80);
static DNSServer dnsServer;

// Platzhalter %KEY% im HTML ersetzen
static String fillTemplate(const char* tmpl, const SensorConfig& c) {
    String html(tmpl);
    html.replace("%SSID%",      c.ssid);
    html.replace("%PASS%",      c.wifi_pass);
    html.replace("%MQTT_HOST%", c.mqtt_host);
    html.replace("%SENSOR_ID%", c.sensor_id);
    html.replace("%ROOM_ID%",   c.room_id);
    html.replace("%MQTT_USER%", c.mqtt_user);
    html.replace("%MQTT_PASS%", c.mqtt_pass);
    return html;
}

static void handleRoot() {
    webServer.send(200, "text/html", fillTemplate(SETUP_HTML, cfg));
}

static void handleSave() {
    if (webServer.hasArg("ssid"))      webServer.arg("ssid").toCharArray(cfg.ssid, sizeof(cfg.ssid));
    if (webServer.hasArg("wifi_pass")) webServer.arg("wifi_pass").toCharArray(cfg.wifi_pass, sizeof(cfg.wifi_pass));
    if (webServer.hasArg("mqtt_host")) webServer.arg("mqtt_host").toCharArray(cfg.mqtt_host, sizeof(cfg.mqtt_host));
    if (webServer.hasArg("mqtt_user")) webServer.arg("mqtt_user").toCharArray(cfg.mqtt_user, sizeof(cfg.mqtt_user));
    if (webServer.hasArg("mqtt_pass")) webServer.arg("mqtt_pass").toCharArray(cfg.mqtt_pass, sizeof(cfg.mqtt_pass));
    if (webServer.hasArg("sensor_id")) webServer.arg("sensor_id").toCharArray(cfg.sensor_id, sizeof(cfg.sensor_id));
    if (webServer.hasArg("room_id"))   webServer.arg("room_id").toCharArray(cfg.room_id, sizeof(cfg.room_id));

    saveConfig();
    Serial.printf("[Setup] Gespeichert – Sensor: %s  Raum: %s  MQTT: %s\n",
                  cfg.sensor_id, cfg.room_id, cfg.mqtt_host);

    webServer.send(200, "text/html", fillTemplate(SAVED_HTML, cfg));
    delay(2000);
    ESP.restart();
}

// Captive-Portal-Redirect: alle URLs → Konfigseite
static void handleCaptive() {
    webServer.sendHeader("Location", "http://192.168.4.1/", true);
    webServer.send(302, "text/plain", "");
}

static void startProvisioningMode() {
    Serial.println("\n[Setup] Einrichtungsmodus – starte WLAN-Hotspot …");
    WiFi.mode(WIFI_AP);

    // Eindeutiger AP-Name mit letzten 3 Byte der MAC
    uint8_t mac[6]; WiFi.macAddress(mac);
    char apName[32];
    snprintf(apName, sizeof(apName), "HausRadar-Setup-%02X%02X%02X",
             mac[3], mac[4], mac[5]);

    WiFi.softAP(apName);
    delay(100);
    Serial.printf("[Setup] Hotspot: %s  IP: %s\n", apName,
                  WiFi.softAPIP().toString().c_str());

    // DNS: alle Anfragen → AP-IP (Captive Portal)
    dnsServer.start(53, "*", WiFi.softAPIP());

    // Webserver
    webServer.on("/",           HTTP_GET,  handleRoot);
    webServer.on("/save",       HTTP_POST, handleSave);
    webServer.onNotFound(handleCaptive);
    webServer.begin();
    Serial.println("[Setup] Webserver gestartet. Öffne http://192.168.4.1");
}

// =============================================================================
// Normalbetrieb: WiFi + MQTT
// =============================================================================

static WiFiClient   wifiClient;
static PubSubClient mqttClient(wifiClient);

static unsigned long lastPublish = 0;
static unsigned long lastStep    = 0;

static void connectWifi() {
    if (WiFi.status() == WL_CONNECTED) return;
    Serial.printf("\n[WiFi] Verbinde mit \"%s\" …", cfg.ssid);
    WiFi.begin(cfg.ssid, cfg.wifi_pass);
    unsigned long deadline = millis() + 15000UL;
    while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
        delay(300); Serial.print('.');
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Verbunden  IP: %s\n", WiFi.localIP().toString().c_str());
#ifdef NTP_SERVER
        configTime(NTP_UTC_OFFSET_S, 0, NTP_SERVER);
        delay(200);
#endif
    } else {
        Serial.println("\n[WiFi] Verbindung fehlgeschlagen.");
    }
}

static void connectMqtt() {
    if (mqttClient.connected()) return;
    char clientId[80];
    buildClientId(clientId, sizeof(clientId));
    Serial.printf("[MQTT] Verbinde mit %s:%d …\n", cfg.mqtt_host, MQTT_PORT);
    const char* user = strlen(cfg.mqtt_user) ? cfg.mqtt_user : nullptr;
    const char* pass = strlen(cfg.mqtt_pass) ? cfg.mqtt_pass : nullptr;
    if (mqttClient.connect(clientId, user, pass)) {
        Serial.println("[MQTT] Verbunden.");
    } else {
        Serial.printf("[MQTT] Fehlgeschlagen (state=%d) – Retry in 5 s\n", mqttClient.state());
        delay(5000);
    }
}

static int64_t getTimestampMs() {
    time_t t = time(nullptr);
    if (t > 1000000000L) return (int64_t)t * 1000LL;
    return 1700000000000LL + (int64_t)millis();
}

static void publishPayload() {
    char topic[96];
    buildTopic(topic, sizeof(topic));

    StaticJsonDocument<512> doc;
    doc["sensor_id"]    = cfg.sensor_id;
    doc["room_id"]      = cfg.room_id;
    doc["timestamp_ms"] = getTimestampMs();
    JsonArray targets   = doc.createNestedArray("targets");

#ifdef SIMULATE
    float xs, ys;
    roomToSensor(walker.x, walker.y, xs, ys);
    float dist  = sqrtf(xs*xs + ys*ys);
    float angle = (dist > 1.0f) ? atan2f(xs, ys)*180.0f/(float)M_PI : 0.0f;
    JsonObject t = targets.createNestedObject();
    t["id"]          = 1;
    t["x_mm"]        = roundf(xs*10.0f)/10.0f;
    t["y_mm"]        = roundf(ys*10.0f)/10.0f;
    t["speed_mm_s"]  = roundf(walker.speed()*10.0f)/10.0f;
    t["distance_mm"] = roundf(dist*10.0f)/10.0f;
    t["angle_deg"]   = roundf(angle*100.0f)/100.0f;
    doc["target_count"] = 1;
    Serial.printf("[SIM] Raum (%5.0f,%5.0f) mm → Sensor (%5.0f,%5.0f) mm  v=%.0f mm/s\n",
                  walker.x, walker.y, xs, ys, walker.speed());
#else
    uint8_t count = 0;
    for (uint8_t i = 0; i < LD2450::MAX_TARGETS; i++) {
        const LD2450::Target& tgt = _lastFrame.targets[i];
        if (!tgt.active) continue;
        JsonObject t = targets.createNestedObject();
        t["id"]          = (int)(i+1);
        t["x_mm"]        = (int)tgt.x_mm;
        t["y_mm"]        = (int)tgt.y_mm;
        t["speed_mm_s"]  = (int)tgt.speed_mm_s;
        t["distance_mm"] = roundf(tgt.distance_mm()*10.0f)/10.0f;
        t["angle_deg"]   = roundf(tgt.angle_deg()*100.0f)/100.0f;
        count++;
    }
    doc["target_count"] = count;
    _frameReady = false;
    Serial.printf("[LD2450] %d Ziel(e)\n", count);
#endif

    char buf[512];
    serializeJson(doc, buf);
    if (!mqttClient.publish(topic, buf))
        Serial.println("[MQTT] publish fehlgeschlagen.");
}

// =============================================================================
// Arduino-Einstiegspunkte
// =============================================================================

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n========= HausRadar Sensor =========");

    // BOOT-Taste (GPIO 0) für Reset prüfen
    const int BOOT_PIN = 0;
    pinMode(BOOT_PIN, INPUT_PULLUP);
    if (digitalRead(BOOT_PIN) == LOW) {
        Serial.println("[Setup] BOOT gedrückt – warte 3 s …");
        delay(3000);
        if (digitalRead(BOOT_PIN) == LOW) {
            Serial.println("[Setup] Reset bestätigt – lösche Konfiguration.");
            clearConfig();
        }
    }

    // Konfiguration laden
    bool hasConfig = loadConfig();

    if (!hasConfig) {
        // Kein Config → Einrichtungsmodus
        _provMode = true;
        startProvisioningMode();
        return;
    }

    // Normalbetrieb
    Serial.printf("[Config] Sensor: %s  Raum: %s  MQTT: %s\n",
                  cfg.sensor_id, cfg.room_id, cfg.mqtt_host);

#ifdef SIMULATE
    Serial.printf("[Sim]    Raum: %.0f x %.0f mm\n", ROOM_WIDTH_MM, ROOM_HEIGHT_MM);
    walker.init();
#else
    Serial.printf("[LD2450] UART2 RX=GPIO%d  %d Baud\n", LD2450_RX_PIN, LD2450_BAUD);
    _ld2450Serial.begin(LD2450_BAUD, SERIAL_8N1, LD2450_RX_PIN, LD2450_TX_PIN);
    delay(100);
    Serial.println("[LD2450] Aktiviere Multi-Target-Modus …");
    LD2450::configureMultiTarget(_ld2450Serial);
    Serial.println("[LD2450] Konfiguration gesendet.");
#endif

    lastStep    = millis();
    lastPublish = millis();

    WiFi.mode(WIFI_STA);
    connectWifi();
    mqttClient.setServer(cfg.mqtt_host, MQTT_PORT);
    mqttClient.setBufferSize(512);
    connectMqtt();
}

void loop() {
    // Einrichtungsmodus: DNS + Webserver bedienen
    if (_provMode) {
        dnsServer.processNextRequest();
        webServer.handleClient();
        return;
    }

    // Normalbetrieb
    if (WiFi.status() != WL_CONNECTED) { connectWifi(); return; }
    if (!mqttClient.connected())        { connectMqtt(); return; }
    mqttClient.loop();

    unsigned long now = millis();

#ifdef SIMULATE
    float dt = (float)(now - lastStep) / 1000.0f;
    lastStep = now;
    walker.step(dt);
#else
    readLD2450();
    lastStep = now;
#endif

    if (now - lastPublish >= PUBLISH_INTERVAL_MS) {
        lastPublish = now;
#ifndef SIMULATE
        if (!_frameReady) return;
#endif
        publishPayload();
    }
}
