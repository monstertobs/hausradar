"use strict";

// ============================================================
// Grundriss
// ============================================================
let floorplan    = null;
let fpEditActive = false;
const fpEditBtn  = document.getElementById("fp-edit-btn");

function initFloorplan(rooms, sensors, connections) {
  floorplan = new Floorplan("floorplan-container");
  floorplan.init(rooms, sensors, connections || []);
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

  // Kalibrierungsphasen: höchste Phase pro Raum (falls mehrere Sensoren)
  if (data.sensors && floorplan) {
    const phaseRank = { none: 0, learning: 1, improving: 2, confident: 3 };
    const phases    = {};
    for (const sdata of Object.values(data.sensors)) {
      const rid = sdata.room_id;
      const ph  = sdata.cal_phase;
      if (rid && ph && (phaseRank[ph] ?? 0) > (phaseRank[phases[rid]] ?? -1)) {
        phases[rid] = ph;
      }
    }
    floorplan.updateCalPhases(phases);
  }

  if (data.events) {
    for (const ev of data.events) {
      if (ev.type === "transit" && floorplan) {
        floorplan.animateTransit(ev.from_room, ev.to_room);
      } else if (ev.type === "layout_update") {
        _applyLiveLayout(ev.layout);
      } else if (ev.type === "calibration_update") {
        _handleCalibrationUpdate(ev);
      }
    }
  }
}

async function _handleCalibrationUpdate(ev) {
  _showCalibrationToast(ev.msg || "Kalibrierung verbessert");
  // Grundriss mit aktuellen Raumdaten neu aufbauen
  await _applyLiveLayout({});
}

let _calToastTimer = null;
function _showCalibrationToast(msg) {
  let t = document.getElementById("cal-update-toast");
  if (!t) {
    t = document.createElement("div");
    t.id        = "cal-update-toast";
    t.className = "fp-toast fp-toast--cal";
    document.body.appendChild(t);
  }
  t.textContent = `📐 ${msg}`;
  t.classList.add("fp-toast--visible");
  clearTimeout(_calToastTimer);
  _calToastTimer = setTimeout(() => t.classList.remove("fp-toast--visible"), 5000);
}

async function _applyLiveLayout(layout) {
  if (!floorplan || !layout) return;
  try {
    // Aktuelle Raumdaten holen und Positionen überschreiben
    const [rooms, sensors, connData] = await Promise.all([
      API.rooms(),
      API.sensors(),
      API.connections.list().catch(() => ({ connections: [] })),
    ]);
    for (const room of rooms) {
      const pos = layout[room.id];
      if (pos) room.floorplan = { ...room.floorplan, ...pos };
    }
    floorplan.applyLayout(rooms, sensors, connData.connections || []);
  } catch (err) {
    console.warn("Layout-Update fehlgeschlagen:", err);
  }
}

// ============================================================
// Raumstatus-Leiste
// ============================================================
let _rooms   = [];
let _sensors = [];

function _buildStatusBar(rooms, sensors) {
  _rooms   = rooms;
  _sensors = sensors || [];
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
    // Sensor-Namen als Tooltip zusammenstellen
    const roomSensors = _sensors.filter(s => s.room_id === r.id);
    const tooltip     = roomSensors.map(s => esc(s.name)).join(", ");
    return `<span class="room-pill room-pill--${st}"${tooltip ? ` title="${tooltip}"` : ""}>
      ${esc(r.name)}
      <span class="room-pill__dot"></span>
      <span class="room-pill__label">${label[st] || st}</span>
    </span>`;
  }).join("");
}

// ============================================================
// Dwell-Zonen (Möbel-Erkennung)
// ============================================================
const DWELL_REFRESH_MS = 30_000;
let _dwellTimer = null;

async function _loadDwellZones() {
  try {
    const data = await API.furniture.zones();
    if (floorplan) floorplan.updateDwellZones(data.zones || []);
  } catch (_) {}
}

// ============================================================
// Init
// ============================================================
async function init() {
  try {
    const [rooms, sensors, connData] = await Promise.all([
      API.rooms(),
      API.sensors(),
      API.connections.list().catch(() => ({ connections: [] })),
    ]);
    _buildStatusBar(rooms, sensors);
    initFloorplan(rooms, sensors, connData.connections || []);
    await _loadDwellZones();
    _dwellTimer = setInterval(_loadDwellZones, DWELL_REFRESH_MS);
  } catch (err) {
    console.error("Initialisierungsfehler:", err);
    // Fehlerzustand im Grundriss anzeigen
    const container = document.getElementById("floorplan-container");
    if (container) {
      container.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;color:var(--text-muted);gap:8px">
        <span style="font-size:2rem">⚠️</span>
        <span>Grundriss konnte nicht geladen werden</span>
        <button onclick="location.reload()" style="margin-top:8px;padding:6px 16px;border-radius:6px;background:var(--card-border);border:none;color:var(--text-primary);cursor:pointer">↻ Neu laden</button>
      </div>`;
    }
  }
  wsConnect();
}

init();
