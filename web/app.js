"use strict";

// ============================================================
// Grundriss
// ============================================================
let floorplan    = null;
let fpEditActive = false;
const fpEditBtn  = document.getElementById("fp-edit-btn");

function initFloorplan(rooms, sensors) {
  floorplan = new Floorplan("floorplan-container");
  floorplan.init(rooms, sensors);
}

fpEditBtn?.addEventListener("click", () => {
  if (!floorplan) return;
  fpEditActive = !fpEditActive;
  if (fpEditActive) {
    floorplan.enableEditMode();
    fpEditBtn.textContent = "✅ Fertig";
    fpEditBtn.classList.add("btn--edit-active");
  } else {
    floorplan.disableEditMode();
    fpEditBtn.textContent = "✏️ Layout bearbeiten";
    fpEditBtn.classList.remove("btn--edit-active");
  }
});

// ============================================================
// WebSocket – Auto-Reconnect
// ============================================================
const WS_URL             = (location.protocol === "https:" ? "wss:" : "ws:")
                           + "//" + location.host + "/ws/live";
const RECONNECT_DELAY_MS = 2000;

let ws             = null;
let reconnectTimer = null;

function wsConnect() {
  clearTimeout(reconnectTimer);
  _setWsStatus("connecting");

  ws = new WebSocket(WS_URL);
  ws.onopen  = () => _setWsStatus("connected");
  ws.onerror = () => { /* onclose folgt immer */ };
  ws.onclose = () => {
    _setWsStatus("reconnecting");
    reconnectTimer = setTimeout(wsConnect, RECONNECT_DELAY_MS);
  };
  ws.onmessage = (event) => {
    try { handleLiveUpdate(JSON.parse(event.data)); }
    catch (err) { console.warn("WS-Parse-Fehler:", err); }
  };
}

function _setWsStatus(state) {
  const badge = document.getElementById("status-badge");
  if (!badge) return;
  const map = {
    connected:    ["badge--ok",         "Verbunden"],
    reconnecting: ["badge--connecting", "Verbinde neu …"],
    connecting:   ["badge--connecting", "Verbinde …"],
  };
  const [cls, text] = map[state] || map.connecting;
  badge.className   = `badge ${cls}`;
  badge.textContent = text;
}

// ============================================================
// Live-Update verarbeiten
// ============================================================
function handleLiveUpdate(data) {
  if (floorplan) floorplan.update(data);
  if (data.sensors) _updateStatusBar(data.sensors);
}

// ============================================================
// Raumstatus-Leiste
// ============================================================
let _rooms = [];

function _buildStatusBar(rooms) {
  _rooms = rooms;
  _renderStatusBar({});
}

function _updateStatusBar(sensors) {
  const priority = { active: 3, offline: 2, recent: 1, idle: 0 };
  const roomStatus = {};

  for (const s of Object.values(sensors)) {
    const rid = s.room_id;
    if (!rid) continue;
    const st = !s.online ? "offline" : s.target_count > 0 ? "active" : "idle";
    if ((priority[st] ?? 0) > (priority[roomStatus[rid]] ?? -1))
      roomStatus[rid] = st;
  }

  _renderStatusBar(roomStatus);
}

function _renderStatusBar(roomStatus) {
  const bar = document.getElementById("room-status-bar");
  if (!bar || !_rooms.length) return;

  const label = { active: "aktiv", offline: "offline", recent: "zuletzt aktiv", idle: "ruhig" };

  bar.innerHTML = _rooms.map(r => {
    const st = roomStatus[r.id] || "idle";
    return `<span class="room-pill room-pill--${st}">
      ${esc(r.name)}
      <span class="room-pill__dot"></span>
      <span class="room-pill__label">${label[st] || st}</span>
    </span>`;
  }).join("");
}

// ============================================================
// Init
// ============================================================
async function init() {
  try {
    const [rooms, sensors] = await Promise.all([API.rooms(), API.sensors()]);
    _buildStatusBar(rooms);
    initFloorplan(rooms, sensors);
  } catch (err) {
    console.error("API-Fehler:", err);
  }
  wsConnect();
}

init();
