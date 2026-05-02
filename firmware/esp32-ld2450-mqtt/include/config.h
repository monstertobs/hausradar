#pragma once

// =============================================================================
// HausRadar – Hardware-Konfiguration
//
// Diese Datei enthält NUR hardware-spezifische Konstanten (Pins, Baudrate,
// Simulationsraum). WLAN, MQTT-Zugangsdaten und Sensor-ID werden beim ersten
// Start über den Browser eingerichtet und im Flash gespeichert.
//
// → ESP32 flashen, dann mit WLAN "HausRadar-Setup-XXXXXX" verbinden
//   und 192.168.4.1 im Browser öffnen.
// =============================================================================

// -----------------------------------------------------------------------------
// LD2450 UART  (wird nur ohne -DSIMULATE verwendet)
//
// Verdrahtung: ESP32-GPIO16 → LD2450-TX
//              ESP32-GPIO17 → LD2450-RX (optional, nur für Konfiguration)
// Baudrate ist vom Hersteller fest auf 256000 gesetzt.
// -----------------------------------------------------------------------------
#define LD2450_RX_PIN   16
#define LD2450_TX_PIN   17
#define LD2450_BAUD     256000

// -----------------------------------------------------------------------------
// MQTT-Port (Standard, selten ändern)
// -----------------------------------------------------------------------------
#define MQTT_PORT  1883

// -----------------------------------------------------------------------------
// Publikationsintervall & NTP
// -----------------------------------------------------------------------------
#define PUBLISH_INTERVAL_MS  500

#define NTP_SERVER       "pool.ntp.org"
#define NTP_UTC_OFFSET_S  3600   // Deutschland Winter: 3600, Sommer: 7200

// -----------------------------------------------------------------------------
// Walker-Simulation (nur mit -DSIMULATE)
// Raumabmessungen und Sensor-Position für die virtuelle Person.
// -----------------------------------------------------------------------------
#define ROOM_WIDTH_MM        6000.0f
#define ROOM_HEIGHT_MM       4500.0f
#define SENSOR_X_MM          3000.0f
#define SENSOR_Y_MM             0.0f
#define SENSOR_ROTATION_DEG     0.0f
