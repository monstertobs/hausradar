"use strict";
/**
 * HausRadar – Kalibrierung: gemeinsamer Kern
 *
 * Enthält: STATE, DOM-Helper $(), API-Fetch, WebSocket-Live-Position,
 *          Status-Badge-Initialisierung.
 * Wird als erstes geladen; alle anderen calibrate-*.js-Dateien bauen darauf auf.
 */

// ---------------------------------------------------------------------------
// Zustand
// ---------------------------------------------------------------------------

const STATE = {
  sessionId:      null,
  sensorId:       null,
  roomId:         null,
  cornerSequence: ["back_left", "back_right", "front_right", "front_left"],
  cornerDisplay:  {},
  furnitureTypes: {},
  markedCorners:  {},   // label → {x_mm, y_mm}
  computed:       null,
  furniture:      [],   // {id, name, type, is_zone, corners:{}, computed}
  doors:          [],   // {id, name, connects_to, points:{}, computed}
  step:           0,    // aktueller Wizard-Schritt (1-7)

  // WebSocket Live-Position
  wsPos:          null, // {x_mm, y_mm}
  wsOnline:       false,
};

// DOM-Elemente
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------------------
// API-Helper
// ---------------------------------------------------------------------------

async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// WebSocket (für Live-Anzeige im Wizard)
// ---------------------------------------------------------------------------

let _ws = null;

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  _ws = new WebSocket(`${proto}://${location.host}/ws/live`);

  _ws.onmessage = ev => {
    try {
      const data = JSON.parse(ev.data);
      updateLivePos(data);
    } catch (_) {}
  };
  _ws.onclose   = ()  => { STATE.wsOnline = false; renderLiveIndicator(); setTimeout(connectWs, 3000); };
  _ws.onerror   = ()  => { STATE.wsOnline = false; renderLiveIndicator(); };
}

function updateLivePos(wsData) {
  if (!STATE.sensorId) return;
  const sdata = wsData?.sensors?.[STATE.sensorId];
  if (!sdata) return;

  STATE.wsOnline = sdata.online ?? false;
  const targets = sdata.targets ?? [];

  if (targets.length > 0) {
    STATE.wsPos = { x_mm: targets[0].x_mm, y_mm: targets[0].y_mm };
  } else {
    STATE.wsPos = null;
  }
  renderLiveIndicator();
}

function renderLiveIndicator() {
  const el = document.querySelector(".live-pos");
  if (!el) return;

  const dot  = el.querySelector(".live-pos-dot");
  const text = el.querySelector(".live-pos-text");
  if (!dot || !text) return;

  if (!STATE.wsOnline) {
    dot.className  = "live-pos-dot offline";
    text.textContent = "Sensor offline";
    return;
  }
  dot.className = "live-pos-dot";
  if (STATE.wsPos) {
    text.textContent =
      `Erkannt bei x=${STATE.wsPos.x_mm.toFixed(0)} mm, y=${STATE.wsPos.y_mm.toFixed(0)} mm`;
  } else {
    text.textContent = "Sensor online – kein Ziel erkannt";
  }
}

// ---------------------------------------------------------------------------
// Status-Badge WebSocket
// ---------------------------------------------------------------------------

function initStatusBadge() {
  const badge = $("status-badge");
  if (!badge) return;
  const check = () => {
    if (!_ws) return;
    if (_ws.readyState === WebSocket.OPEN) {
      badge.className   = "badge badge--ok";
      badge.textContent = "Verbunden";
    } else {
      badge.className   = "badge badge--connecting";
      badge.textContent = "Verbinde …";
    }
  };
  setInterval(check, 2000);
}
