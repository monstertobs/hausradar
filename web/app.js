"use strict";

// ============================================================
// DOM-Referenzen
// ============================================================
const statusBadge   = document.getElementById("status-badge");
const healthStatus  = document.getElementById("health-status");
const wsStatusEl    = document.getElementById("ws-status");
const roomCount     = document.getElementById("room-count");
const sensorCount   = document.getElementById("sensor-count");
const roomList      = document.getElementById("room-list");
const sensorList    = document.getElementById("sensor-list");
const liveDebug     = document.getElementById("live-debug");
const liveTimestamp = document.getElementById("live-timestamp");
const liveCounter   = document.getElementById("live-counter");

// ============================================================
// Grundriss
// ============================================================
let floorplan = null;

function initFloorplan(rooms, sensors) {
  floorplan = new Floorplan("floorplan-container");
  floorplan.init(rooms, sensors);
}

// ============================================================
// WebSocket – Auto-Reconnect alle 2 Sekunden
// ============================================================
const WS_URL             = (location.protocol === "https:" ? "wss:" : "ws:")
                           + "//" + location.host + "/ws/live";
const RECONNECT_DELAY_MS = 2000;

let ws             = null;
let reconnectTimer = null;
let updateCount    = 0;

function wsConnect() {
  clearTimeout(reconnectTimer);
  _setWsStatus("connecting");

  ws = new WebSocket(WS_URL);

  ws.onopen = () => _setWsStatus("connected");

  ws.onmessage = (event) => {
    try {
      handleLiveUpdate(JSON.parse(event.data));
    } catch (err) {
      console.warn("WS-Nachricht nicht parsbar:", err);
    }
  };

  ws.onerror = () => { /* onclose folgt immer */ };

  ws.onclose = () => {
    _setWsStatus("reconnecting");
    reconnectTimer = setTimeout(wsConnect, RECONNECT_DELAY_MS);
  };
}

function _setWsStatus(state) {
  statusBadge.className = "badge";
  const labels = {
    connected:    ["badge--ok",         "Verbunden"],
    reconnecting: ["badge--connecting", "Verbinde neu …"],
    connecting:   ["badge--connecting", "Verbinde …"],
  };
  const [cls, text] = labels[state] || labels.connecting;
  statusBadge.classList.add(cls);
  statusBadge.textContent = text;

  if (wsStatusEl) {
    const colors = { connected: "var(--green)", reconnecting: "var(--yellow)", connecting: "var(--muted)" };
    wsStatusEl.textContent = text;
    wsStatusEl.style.color = colors[state] || "var(--muted)";
  }
}

// ============================================================
// Live-Update verarbeiten
// ============================================================
function handleLiveUpdate(data) {
  updateCount++;

  if (liveCounter)   liveCounter.textContent   = `(${updateCount} Updates)`;
  if (liveTimestamp) liveTimestamp.textContent  = new Date().toLocaleTimeString("de-DE");
  if (liveDebug)     liveDebug.textContent      = JSON.stringify(data, null, 2);

  // Grundriss-Zielpunkte und Raumfarben
  if (floorplan) floorplan.update(data);

  // Raumkacheln in der Listenansicht
  if (data.sensors) _updateRoomTiles(data.sensors);
}

// ============================================================
// Raumkacheln nach Live-Daten aktualisieren
// ============================================================
function _updateRoomTiles(sensors) {
  const priority = { active: 3, offline: 2, recent: 1, idle: 0 };
  const roomStatus = {};

  for (const sdata of Object.values(sensors)) {
    const rid = sdata.room_id;
    if (!rid) continue;

    let st;
    if (!sdata.online)            st = "offline";
    else if (sdata.target_count > 0) st = "active";
    else                          st = "idle";

    if ((priority[st] ?? 0) > (priority[roomStatus[rid]] ?? -1)) {
      roomStatus[rid] = st;
    }
  }

  document.querySelectorAll(".room-tile[data-room-id]").forEach(tile => {
    const st    = roomStatus[tile.dataset.roomId] || "idle";
    const badge = tile.querySelector(".room-tile__status");
    if (!badge) return;
    badge.className  = `room-tile__status status--${st}`;
    badge.textContent = { active: "aktiv", offline: "offline", recent: "zuletzt aktiv", idle: "ruhig" }[st] ?? st;
  });
}

// ============================================================
// HTTP-Init: Backend, Räume, Sensoren
// ============================================================
function renderRooms(rooms) {
  if (!rooms || rooms.length === 0) {
    roomList.innerHTML = '<p class="muted">Keine Räume konfiguriert.</p>';
    return;
  }
  roomList.innerHTML = rooms.map(r => `
    <div class="room-tile" data-room-id="${esc(r.id)}">
      <div class="room-tile__name">${esc(r.name)}</div>
      <div class="room-tile__meta">
        ${(r.width_mm / 1000).toFixed(1)} m × ${(r.height_mm / 1000).toFixed(1)} m<br>
        ${(r.zones || []).length} Zone(n)
      </div>
      <span class="room-tile__status status--idle">ruhig</span>
    </div>
  `).join("");
}

function renderSensors(sensors) {
  if (!sensors || sensors.length === 0) {
    sensorList.innerHTML = '<p class="muted">Keine Sensoren konfiguriert.</p>';
    return;
  }
  sensorList.innerHTML = sensors.map(s => `
    <div class="sensor-tile" id="sensor-${esc(s.id)}">
      <div class="sensor-tile__name">${esc(s.name)}</div>
      <div class="sensor-tile__meta">
        Raum: ${esc(s.room_id)}<br>
        Position: ${esc(s.x_mm)}&thinsp;mm / ${esc(s.y_mm)}&thinsp;mm<br>
        Höhe: ${esc(s.mount_height_mm)}&thinsp;mm<br>
        Drehung: ${esc(s.rotation_deg)}°<br>
        Status: ${s.enabled ? "aktiv" : "deaktiviert"}
      </div>
    </div>
  `).join("");
}

async function init() {
  try {
    const [health, rooms, sensors] = await Promise.all([
      API.health(),
      API.rooms(),
      API.sensors(),
    ]);

    if (healthStatus) {
      healthStatus.textContent = health.status === "ok" ? "✓ OK" : health.status;
    }
    if (roomCount)   roomCount.textContent   = rooms.length;
    if (sensorCount) sensorCount.textContent = sensors.length;

    renderRooms(rooms);
    renderSensors(sensors);
    initFloorplan(rooms, sensors);
  } catch (err) {
    if (healthStatus) {
      healthStatus.textContent = "Nicht erreichbar";
      healthStatus.style.color = "var(--red)";
    }
    console.error("API-Fehler:", err);
  }

  // WebSocket unabhängig vom HTTP-Ergebnis starten
  wsConnect();
}

init();
