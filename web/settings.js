"use strict";

let _healthTimer = null;

// ---------------------------------------------------------------------------
// Einstiegspunkt
// ---------------------------------------------------------------------------

async function initSettings() {
  _loadHealth();
  _loadConfig();
  _healthTimer = setInterval(_loadHealth, 5000);
}

// ---------------------------------------------------------------------------
// System-Status (Health-Endpoint)
// ---------------------------------------------------------------------------

async function _loadHealth() {
  const el = document.getElementById("health-grid");
  try {
    const h = await API.health();
    _renderHealth(el, h);
    // Topbar-Badge mitführen
    const badge = document.getElementById("status-badge");
    if (badge) {
      badge.className = "badge badge--ok";
      badge.textContent = "Backend OK";
    }
  } catch {
    el.innerHTML = '<p class="muted error-text">Backend nicht erreichbar.</p>';
    const badge = document.getElementById("status-badge");
    if (badge) { badge.className = "badge badge--error"; badge.textContent = "Fehler"; }
  }
}

function _renderHealth(el, h) {
  const rows = [
    ["Backend",          _dot(true) + " OK"],
    ["Uptime",           _fmt_uptime(h.uptime_s)],
    ["Datenbank",        h.db_ok   ? _dot(true)  + " OK"        : _dot(false) + " Fehler"],
    ["MQTT",             h.mqtt_connected ? _dot(true) + " Verbunden" : _dot(false) + " Kein Broker"],
    ["WebSocket-Clients", String(h.ws_clients)],
  ];

  el.innerHTML = rows.map(([label, value]) =>
    `<div class="health-row">
       <span class="health-label">${label}</span>
       <span class="health-value">${value}</span>
     </div>`
  ).join("");
}

function _dot(ok) {
  return `<span class="dot dot--${ok ? "ok" : "off"}"></span>`;
}

function _fmt_uptime(s) {
  if (s == null) return "–";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min ${sec} s`;
  return `${sec} s`;
}

// ---------------------------------------------------------------------------
// Räume und Sensoren
// ---------------------------------------------------------------------------

async function _loadConfig() {
  try {
    const [rooms, sensors] = await Promise.all([API.rooms(), API.sensors()]);
    _renderRooms(rooms);
    _renderSensors(sensors, rooms);
  } catch {
    document.getElementById("settings-rooms").innerHTML =
      '<p class="muted error-text">Fehler beim Laden der Konfiguration.</p>';
    document.getElementById("settings-sensors").innerHTML = "";
  }
}

function _renderRooms(rooms) {
  const el = document.getElementById("settings-rooms");
  if (!rooms.length) { el.innerHTML = '<p class="muted">Keine Räume konfiguriert.</p>'; return; }

  el.innerHTML = rooms.map(r => {
    const zones = (r.zones || []).map(z =>
      `<span class="chip">${esc(z.name)}</span>`
    ).join(" ");
    return `
      <div class="room-tile">
        <strong>${esc(r.name)}</strong>
        <div class="room-tile__meta">
          ${(r.width_mm / 1000).toFixed(1)} m × ${(r.height_mm / 1000).toFixed(1)} m
          &nbsp;·&nbsp; ${(r.zones || []).length} Zone(n)
        </div>
        ${zones ? `<div class="chip-row">${zones}</div>` : ""}
      </div>`;
  }).join("");
}

function _renderSensors(sensors, rooms) {
  const el = document.getElementById("settings-sensors");
  const roomMap = Object.fromEntries((rooms || []).map(r => [r.id, r.name]));
  if (!sensors.length) { el.innerHTML = '<p class="muted">Keine Sensoren konfiguriert.</p>'; return; }

  el.innerHTML = sensors.map(s => {
    const roomName = roomMap[s.room_id] || s.room_id;
    const statusClass = s.enabled ? "dot dot--ok" : "dot dot--off";
    const statusLabel = s.enabled ? "aktiv" : "deaktiviert";
    return `
      <div class="sensor-tile">
        <strong><span class="${statusClass}"></span> ${esc(s.name)}</strong>
        <div class="sensor-tile__meta">
          Raum: ${esc(roomName)}<br>
          Position: ${esc(s.x_mm)} mm / ${esc(s.y_mm)} mm<br>
          Höhe: ${esc(s.mount_height_mm)} mm<br>
          Drehung: ${esc(s.rotation_deg)}°<br>
          Status: ${statusLabel}
        </div>
      </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", initSettings);
