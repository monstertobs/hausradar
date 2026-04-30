#pragma once

// =============================================================================
// HausRadar – Sensor-Konfiguration
//
// Diese Datei MUSS vor dem Flashen angepasst werden.
// Jeder Sensor bekommt eine eigene Kopie mit den passenden Werten.
//
// WLAN-Passwort und MQTT-Auth in secrets.h eintragen (nie in config.h!):
//   cp include/secrets.h.example include/secrets.h
//   # dann secrets.h bearbeiten
// =============================================================================

// Sensible Zugangsdaten aus secrets.h laden (nie direkt hier eintragen)
#include "secrets.h"

// -----------------------------------------------------------------------------
// MQTT-Broker (IP-Adresse des Raspberry Pi)
// -----------------------------------------------------------------------------
#define MQTT_HOST       "192.168.178.100"   // ← Pi-IP eintragen
#define MQTT_PORT       1883

// Muss pro Sensor eindeutig sein
#define MQTT_CLIENT_ID  "hausradar-radar_wohnzimmer"

// Topic-Format: hausradar/sensor/{sensor_id}/state
// sensor_id muss mit dem Eintrag in config/sensors.json übereinstimmen
#define MQTT_TOPIC      "hausradar/sensor/radar_wohnzimmer/state"

// -----------------------------------------------------------------------------
// Sensor-Identität  (muss zu config/sensors.json passen)
// In den Einstellungen → Sensoren wird das vollständige MQTT-Topic angezeigt.
// -----------------------------------------------------------------------------
#define SENSOR_ID   "radar_wohnzimmer"
#define ROOM_ID     "wohnzimmer"

// Sensor-Position im Raum [mm]  (aus config/sensors.json)
#define SENSOR_X_MM          3000.0f
#define SENSOR_Y_MM             0.0f
#define SENSOR_ROTATION_DEG     0.0f

// -----------------------------------------------------------------------------
// Raumabmessungen [mm]  (aus config/rooms.json – für Walker-Simulation)
// -----------------------------------------------------------------------------
#define ROOM_WIDTH_MM   6000.0f
#define ROOM_HEIGHT_MM  4500.0f

// -----------------------------------------------------------------------------
// LD2450 UART  (wird nur ohne -DSIMULATE verwendet)
//
// Standard-Verdrahtung: ESP32-GPIO16 → LD2450-TX
//                        ESP32-GPIO17 → LD2450-RX (optional, nur für Konfiguration)
// Baudrate ist vom Hersteller fest auf 256000 gesetzt.
// -----------------------------------------------------------------------------
#define LD2450_RX_PIN   16
#define LD2450_TX_PIN   17
#define LD2450_BAUD     256000

// -----------------------------------------------------------------------------
// Publikationsintervall & NTP
// -----------------------------------------------------------------------------

// Millisekunden zwischen zwei MQTT-Nachrichten
#define PUBLISH_INTERVAL_MS  500

// NTP-Server für korrekten Unix-Timestamp (leer lassen → millis()-Fallback)
#define NTP_SERVER  "pool.ntp.org"

// Zeitzone UTC-Offset in Sekunden (Deutschland Winter: 3600, Sommer: 7200)
#define NTP_UTC_OFFSET_S  3600
