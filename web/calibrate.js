"use strict";
/**
 * HausRadar – Kalibrierungs-Wizard
 *
 * Ablauf:
 *   Schritt 0  Sensor/Raum wählen  (HTML-Form, kein Wizard-Panel)
 *   Schritt 1  Ecke: back_left
 *   Schritt 2  Ecke: back_right
 *   Schritt 3  Ecke: front_right
 *   Schritt 4  Ecke: front_left
 *   Schritt 5  Vorschau der berechneten Raummaße
 *   Schritt 6  Möbel erfassen (wiederholbar, beliebig viele)
 *   Schritt 7  Speichern
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
  step:           0,    // aktueller Wizard-Schritt (1-7)

  // WebSocket Live-Position
  wsPos:          null, // {x_mm, y_mm}
  wsOnline:       false,
};

// DOM-Elemente
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------------------
// WebSocket (für Live-Anzeige)
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
// Setup: Sensoren + Räume laden
// ---------------------------------------------------------------------------

async function loadSelectors() {
  const [sensors, rooms] = await Promise.all([
    apiFetch("/api/sensors"),
    apiFetch("/api/rooms"),
  ]);

  const selSensor = $("sel-sensor");
  const selRoom   = $("sel-room");

  selSensor.innerHTML = sensors
    .filter(s => s.enabled !== false)
    .map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`)
    .join("");

  // Raum anhand Sensor befüllen
  function syncRoom() {
    const sid = selSensor.value;
    const sensor = sensors.find(s => s.id === sid);
    selRoom.innerHTML = rooms
      .map(r => `<option value="${esc(r.id)}" ${r.id === sensor?.room_id ? "selected" : ""}>${esc(r.name)}</option>`)
      .join("");
    $("btn-start").disabled = false;
  }
  selSensor.addEventListener("change", syncRoom);
  syncRoom();
}

$("btn-start").addEventListener("click", async () => {
  const sensor_id = $("sel-sensor").value;
  const room_id   = $("sel-room").value;
  if (!sensor_id || !room_id) return;

  $("btn-start").disabled = true;
  try {
    const res = await apiFetch("/api/calibrate/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body:   JSON.stringify({ sensor_id, room_id }),
    });

    STATE.sessionId      = res.session_id;
    STATE.sensorId       = sensor_id;
    STATE.roomId         = room_id;
    STATE.cornerSequence = res.corner_sequence;
    STATE.cornerDisplay  = res.corner_display;
    STATE.furnitureTypes = res.furniture_types;

    $("step-select").style.display = "none";
    $("wizard-progress").style.display = "block";
    $("wizard-body").style.display     = "block";

    connectWs();
    gotoStep(1);
  } catch (e) {
    alert("Fehler beim Starten: " + e.message);
    $("btn-start").disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Schritt-Navigation
// ---------------------------------------------------------------------------

const TOTAL_STEPS = 7;

function gotoStep(n) {
  STATE.step = n;
  renderProgress();
  renderStep(n);
}

function renderProgress() {
  const bar = $("wizard-steps-bar");
  const labels = [
    "↖ H.L.", "↗ H.R.", "↘ V.R.", "↙ V.L.", "Vorschau", "Möbel", "Speichern"
  ];
  bar.innerHTML = "";
  for (let i = 1; i <= TOTAL_STEPS; i++) {
    if (i > 1) {
      const line = document.createElement("div");
      line.className = "wizard-step-line";
      bar.appendChild(line);
    }
    const step = document.createElement("div");
    step.className = "wizard-step";
    const dot = document.createElement("div");
    dot.className = "wizard-step-dot" +
      (i < STATE.step ? " done" : i === STATE.step ? " active" : "");
    dot.textContent = i < STATE.step ? "✓" : String(i);
    dot.title = labels[i - 1];
    step.appendChild(dot);
    bar.appendChild(step);
  }
}

// ---------------------------------------------------------------------------
// Schritt-Rendering
// ---------------------------------------------------------------------------

function renderStep(n) {
  const body = $("wizard-body");
  if (n >= 1 && n <= 4) renderCornerStep(n, body);
  else if (n === 5)     renderPreviewStep(body);
  else if (n === 6)     renderFurnitureStep(body);
  else if (n === 7)     renderSaveStep(body);
}

// ─── Ecken-Schritt (1–4) ────────────────────────────────────────────────────

function renderCornerStep(stepNum, body) {
  const label = STATE.cornerSequence[stepNum - 1];
  const info  = STATE.cornerDisplay[label] || {};
  const already = STATE.markedCorners[label];

  body.innerHTML = `
    <div class="wizard-panel">
      <h3>Schritt ${stepNum}/4 &nbsp; ${esc(info.icon || "")} ${esc(info.de || label)}</h3>
      <p class="wizard-hint">${esc(info.hint || "")}</p>

      <!-- Raum-Diagram -->
      <svg class="room-diagram" viewBox="0 0 220 160" xmlns="http://www.w3.org/2000/svg">
        ${roomDiagramSvg(label)}
      </svg>

      <!-- Live-Position -->
      <div class="live-pos">
        <div class="live-pos-dot"></div>
        <span class="live-pos-text">Warte auf Sensordaten …</span>
      </div>

      ${already ? `
        <div style="color:var(--green);font-size:.875rem;margin-bottom:12px">
          ✓ Bereits markiert: x=${already.x_mm.toFixed(0)} mm, y=${already.y_mm.toFixed(0)} mm
          <br><small>Klicke "Jetzt markieren" um die Position zu überschreiben.</small>
        </div>` : ""}

      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <button class="btn-mark" id="btn-mark-corner">📍 Jetzt markieren</button>
        ${stepNum > 1 ? '<button class="btn-secondary" id="btn-prev">← Zurück</button>' : ""}
      </div>
      <div id="mark-result" style="margin-top:12px"></div>
    </div>`;

  renderLiveIndicator();

  $("btn-mark-corner").addEventListener("click", async () => {
    $("btn-mark-corner").disabled    = true;
    $("btn-mark-corner").textContent = "Markiere …";
    $("mark-result").innerHTML       = "";
    try {
      const res = await apiFetch(
        `/api/calibrate/session/${STATE.sessionId}/mark/${label}`,
        { method: "POST" }
      );
      STATE.markedCorners[label] = { x_mm: res.x_mm, y_mm: res.y_mm };

      $("mark-result").innerHTML =
        `<span style="color:var(--green)">✓ Markiert: x=${res.x_mm.toFixed(0)} mm, y=${res.y_mm.toFixed(0)} mm</span>`;

      if (res.targets_total > 1) {
        $("mark-result").innerHTML +=
          `<br><small style="color:var(--yellow)">Hinweis: ${res.targets_total} Ziele erkannt – besser alleine im Raum sein</small>`;
      }

      setTimeout(() => {
        if (stepNum < 4) gotoStep(stepNum + 1);
        else             gotoStep(5);
      }, 900);
    } catch (e) {
      $("mark-result").innerHTML = `<span style="color:var(--red)">✗ ${esc(e.message)}</span>`;
      $("btn-mark-corner").disabled    = false;
      $("btn-mark-corner").textContent = "📍 Jetzt markieren";
    }
  });

  if ($("btn-prev")) {
    $("btn-prev").addEventListener("click", () => gotoStep(stepNum - 1));
  }
}

// ─── Vorschau-Schritt (5) ───────────────────────────────────────────────────

async function renderPreviewStep(body) {
  body.innerHTML = `<div class="wizard-panel"><p class="wizard-hint">Berechne …</p></div>`;
  try {
    const res = await apiFetch(
      `/api/calibrate/session/${STATE.sessionId}/compute`,
      { method: "POST" }
    );
    STATE.computed = res;

    body.innerHTML = `
      <div class="wizard-panel">
        <h3>Schritt 5 – Berechnete Raummaße</h3>
        <p class="wizard-hint">Stimmen diese Werte ungefähr mit deinem Raum überein?</p>

        <div class="result-grid">
          <div class="result-item">
            <div class="result-item-label">Raumbreite</div>
            <div class="result-item-value">${(res.width_mm / 1000).toFixed(2)} m</div>
          </div>
          <div class="result-item">
            <div class="result-item-label">Raumtiefe</div>
            <div class="result-item-value">${(res.height_mm / 1000).toFixed(2)} m</div>
          </div>
          <div class="result-item">
            <div class="result-item-label">Sensor X</div>
            <div class="result-item-value">${(res.sensor_x_mm / 1000).toFixed(2)} m</div>
          </div>
          <div class="result-item">
            <div class="result-item-label">Rotation</div>
            <div class="result-item-value">${res.rotation_deg.toFixed(1)}°</div>
          </div>
        </div>

        <p class="wizard-hint" style="margin-top:8px">
          Fläche: ca. ${((res.width_mm / 1000) * (res.height_mm / 1000)).toFixed(1)} m²
        </p>

        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn-secondary" id="btn-prev5">← Zurück (neu messen)</button>
          <button class="btn-mark" id="btn-next5">Weiter → Möbel</button>
          <button class="btn-secondary" id="btn-skip-furn">Möbel überspringen</button>
        </div>
      </div>`;

    $("btn-prev5").addEventListener("click", () => gotoStep(4));
    $("btn-next5").addEventListener("click", () => gotoStep(6));
    $("btn-skip-furn").addEventListener("click", () => gotoStep(7));
  } catch (e) {
    body.innerHTML = `
      <div class="wizard-panel">
        <p style="color:var(--red)">Fehler bei der Berechnung: ${esc(e.message)}</p>
        <button class="btn-secondary" style="margin-top:12px" id="btn-prev5e">← Zurück</button>
      </div>`;
    $("btn-prev5e").addEventListener("click", () => gotoStep(4));
  }
}

// ─── Möbel-Schritt (6) ──────────────────────────────────────────────────────

function renderFurnitureStep(body) {
  const typeOptions = Object.entries(STATE.furnitureTypes)
    .map(([k, v]) => `<option value="${esc(k)}">${esc(v.de)}</option>`)
    .join("");

  const furnListHtml = STATE.furniture.length === 0
    ? `<p class="muted" style="font-size:.875rem">Noch keine Möbel hinzugefügt.</p>`
    : STATE.furniture.map(f => furnItemHtml(f)).join("");

  body.innerHTML = `
    <div class="wizard-panel">
      <h3>Schritt 6 – Möbel erfassen <span style="color:var(--muted);font-weight:400">(optional)</span></h3>
      <p class="wizard-hint">
        Füge Möbelstücke hinzu: Nenne das Möbel, wähle den Typ und stell dich nacheinander
        an zwei diagonal gegenüberliegende Ecken (z.B. vorne links → hinten rechts).
        <br>Als Zone markierte Möbel werden automatisch in der Zonen-Erkennung verwendet.
      </p>

      <!-- Möbel hinzufügen -->
      <div class="add-furniture-form">
        <div class="form-group">
          <label class="form-label">Name</label>
          <input id="furn-name" class="form-input" placeholder="z.B. Sofa" maxlength="40"/>
        </div>
        <div class="form-group">
          <label class="form-label">Typ</label>
          <select id="furn-type" class="form-select">${typeOptions}</select>
        </div>
        <div class="form-group">
          <label class="form-label">Als Zone?</label>
          <select id="furn-zone" class="form-select">
            <option value="true">Ja</option>
            <option value="false">Nein</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">&nbsp;</label>
          <button class="btn-secondary" id="btn-add-furn">+ Hinzufügen</button>
        </div>
      </div>

      <!-- Liste -->
      <div class="furniture-list" id="furn-list">${furnListHtml}</div>

      <!-- Live-Position -->
      <div class="live-pos" id="furn-live-pos">
        <div class="live-pos-dot"></div>
        <span class="live-pos-text">–</span>
      </div>

      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn-secondary" id="btn-prev6">← Zurück</button>
        <button class="btn-mark" id="btn-next6">Weiter → Speichern</button>
      </div>
    </div>`;

  renderLiveIndicator();
  bindFurnitureEvents();

  $("btn-prev6").addEventListener("click", () => gotoStep(5));
  $("btn-next6").addEventListener("click", () => gotoStep(7));
}

function furnItemHtml(f) {
  const aOk = !!f.corners?.a;
  const bOk = !!f.corners?.b;
  const done = !!f.computed;
  const type = STATE.furnitureTypes[f.type]?.de || f.type;

  return `
    <div class="furniture-item" id="fi-${esc(f.id)}">
      <div class="furniture-item-info">
        <div class="furniture-item-name">${esc(f.name)}</div>
        <div class="furniture-item-meta">${esc(type)}${f.is_zone ? " · als Zone" : ""}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn-secondary" style="font-size:.78rem;padding:4px 10px"
          id="btn-mark-a-${esc(f.id)}" ${done ? "disabled" : ""}>
          ${aOk ? "✓" : "📍"} Ecke A
        </button>
        <button class="btn-secondary" style="font-size:.78rem;padding:4px 10px"
          id="btn-mark-b-${esc(f.id)}" ${done || !aOk ? "disabled" : ""}>
          ${bOk ? "✓" : "📍"} Ecke B
        </button>
        <span class="furniture-item-status ${done ? "done" : ""}">
          ${done ? `${f.computed.width_mm}×${f.computed.height_mm} mm` : (bOk ? "Berechne …" : "Warte …")}
        </span>
      </div>
    </div>`;
}

function bindFurnitureEvents() {
  $("btn-add-furn")?.addEventListener("click", async () => {
    const name    = $("furn-name").value.trim();
    const ftype   = $("furn-type").value;
    const is_zone = $("furn-zone").value === "true";
    if (!name) { $("furn-name").focus(); return; }

    try {
      const res = await apiFetch(
        `/api/calibrate/session/${STATE.sessionId}/furniture`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body:   JSON.stringify({ name, type: ftype, is_zone }),
        }
      );
      STATE.furniture.push({ id: res.furniture_id, name, type: ftype, is_zone, corners: {}, computed: null });
      $("furn-name").value = "";
      refreshFurnList();
    } catch (e) {
      alert("Fehler: " + e.message);
    }
  });

  // Ecken-Buttons für bereits vorhandene Möbel
  for (const f of STATE.furniture) {
    bindFurnCornerBtn(f, "a");
    bindFurnCornerBtn(f, "b");
  }
}

function bindFurnCornerBtn(f, corner) {
  const btn = $(`btn-mark-${corner}-${f.id}`);
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled    = true;
    btn.textContent = "…";
    try {
      const res = await apiFetch(
        `/api/calibrate/session/${STATE.sessionId}/furniture/${f.id}/mark/${corner}`,
        { method: "POST" }
      );
      f.corners[corner] = { x_mm: res.x_mm, y_mm: res.y_mm };

      if (res.ready) {
        // Beide Ecken markiert → berechnen
        const comp = await apiFetch(
          `/api/calibrate/session/${STATE.sessionId}/furniture/${f.id}/compute`,
          { method: "POST" }
        );
        f.computed = comp;
      }
      refreshFurnList();
    } catch (e) {
      alert("Fehler: " + e.message);
      btn.disabled = false;
      btn.textContent = `📍 Ecke ${corner.toUpperCase()}`;
    }
  });
}

function refreshFurnList() {
  const list = $("furn-list");
  if (!list) return;
  list.innerHTML = STATE.furniture.length === 0
    ? `<p class="muted" style="font-size:.875rem">Noch keine Möbel hinzugefügt.</p>`
    : STATE.furniture.map(f => furnItemHtml(f)).join("");
  bindFurnitureEvents();
}

// ─── Speichern-Schritt (7) ──────────────────────────────────────────────────

function renderSaveStep(body) {
  const readyFurn = STATE.furniture.filter(f => f.computed).length;
  const totalFurn = STATE.furniture.length;

  body.innerHTML = `
    <div class="wizard-panel">
      <h3>Schritt 7 – Speichern</h3>
      <p class="wizard-hint">
        Die folgenden Werte werden in <code>rooms.json</code> und
        <code>sensors.json</code> geschrieben. Danach muss der Dienst neu
        gestartet werden.
      </p>

      <div class="result-grid" style="margin-bottom:16px">
        <div class="result-item">
          <div class="result-item-label">Raumbreite</div>
          <div class="result-item-value">${STATE.computed ? (STATE.computed.width_mm / 1000).toFixed(2) + " m" : "–"}</div>
        </div>
        <div class="result-item">
          <div class="result-item-label">Raumtiefe</div>
          <div class="result-item-value">${STATE.computed ? (STATE.computed.height_mm / 1000).toFixed(2) + " m" : "–"}</div>
        </div>
        <div class="result-item">
          <div class="result-item-label">Sensor X</div>
          <div class="result-item-value">${STATE.computed ? (STATE.computed.sensor_x_mm / 1000).toFixed(2) + " m" : "–"}</div>
        </div>
        <div class="result-item">
          <div class="result-item-label">Möbelstücke</div>
          <div class="result-item-value">${readyFurn} / ${totalFurn}</div>
        </div>
      </div>

      ${totalFurn > 0 && readyFurn < totalFurn
        ? `<p style="color:var(--yellow);font-size:.875rem;margin-bottom:12px">
            ⚠ ${totalFurn - readyFurn} Möbelstück(e) nicht vollständig markiert – werden übersprungen.
           </p>` : ""}

      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
        <button class="btn-secondary" id="btn-prev7">← Zurück</button>
        <button class="btn-success" id="btn-save">💾 Jetzt speichern</button>
      </div>
      <div id="save-result"></div>
    </div>`;

  $("btn-prev7").addEventListener("click", () => gotoStep(6));
  $("btn-save").addEventListener("click", async () => {
    $("btn-save").disabled    = true;
    $("btn-save").textContent = "Speichere …";
    $("save-result").innerHTML = "";
    try {
      const res = await apiFetch(
        `/api/calibrate/session/${STATE.sessionId}/save`,
        { method: "POST" }
      );

      $("save-result").innerHTML = `
        <div class="save-result">
          <p>✅ <strong>Kalibrierung erfolgreich gespeichert!</strong></p>
          <p>Raum <strong>${esc(res.room.id)}</strong>:
             ${(res.room.width_mm/1000).toFixed(2)} m ×
             ${(res.room.height_mm/1000).toFixed(2)} m</p>
          <p>Sensor <strong>${esc(res.sensor.id)}</strong>:
             x=${(res.sensor.x_mm/1000).toFixed(2)} m,
             rotation=${res.sensor.rotation_deg.toFixed(1)}°</p>
          ${res.furniture_saved > 0
            ? `<p>${res.furniture_saved} Möbelstück(e) gespeichert.</p>` : ""}
          <p style="margin-top:12px">
            ⚠ <strong>Backend neu starten</strong> damit die Änderungen wirken:<br>
            <code>${esc(res.restart_hint)}</code>
          </p>
        </div>`;

      // Session-ID zurücksetzen (ist serverseitig gelöscht)
      STATE.sessionId = null;
      $("btn-save").textContent = "✓ Gespeichert";
    } catch (e) {
      $("save-result").innerHTML =
        `<p style="color:var(--red)">✗ Fehler: ${esc(e.message)}</p>`;
      $("btn-save").disabled    = false;
      $("btn-save").textContent = "💾 Jetzt speichern";
    }
  });
}

// ---------------------------------------------------------------------------
// SVG-Diagramm: Raumskizze mit markierter Ecke
// ---------------------------------------------------------------------------

function roomDiagramSvg(activeLabel) {
  const corners = {
    back_left:   { cx: 20,  cy: 20 },
    back_right:  { cx: 200, cy: 20 },
    front_left:  { cx: 20,  cy: 140 },
    front_right: { cx: 200, cy: 140 },
  };

  const labels = {
    back_left:   { x: 5,   y: 14,  anchor: "start"  },
    back_right:  { x: 215, y: 14,  anchor: "end"    },
    front_left:  { x: 5,   y: 155, anchor: "start"  },
    front_right: { x: 215, y: 155, anchor: "end"    },
  };

  let svg = `
    <!-- Raumumriss -->
    <rect x="20" y="20" width="180" height="120" fill="none" stroke="#374151" stroke-width="2" rx="2"/>
    <!-- Sensor an oberer Wand, Mitte -->
    <circle cx="110" cy="20" r="5" fill="#164e63" stroke="#22d3ee" stroke-width="1.5"/>
    <polygon points="110,28 105,20 115,20" fill="#22d3ee" opacity=".8"/>
    <text x="110" y="14" text-anchor="middle" font-size="7" fill="#22d3ee">Sensor</text>
    <!-- Sichtfeld -->
    <line x1="110" y1="20" x2="20"  y2="140" stroke="#22d3ee" stroke-width=".5" opacity=".2"/>
    <line x1="110" y1="20" x2="200" y2="140" stroke="#22d3ee" stroke-width=".5" opacity=".2"/>
  `;

  for (const [lbl, pos] of Object.entries(corners)) {
    const active = lbl === activeLabel;
    const done   = !!STATE.markedCorners[lbl];
    const color  = active ? "#3b82f6" : done ? "#22c55e" : "#374151";
    const fill   = active ? "#1e3a5f" : done ? "#052e16" : "#1a1d27";
    const info   = STATE.cornerDisplay[lbl] || {};

    svg += `
      <circle cx="${pos.cx}" cy="${pos.cy}" r="${active ? 9 : 7}"
        fill="${fill}" stroke="${color}" stroke-width="${active ? 2.5 : 1.5}"/>
      <text x="${labels[lbl].x}" y="${labels[lbl].y}"
        text-anchor="${labels[lbl].anchor}"
        font-size="${active ? 8 : 7}"
        fill="${color}">${esc(info.icon || "")}</text>
    `;
  }

  // Beschriftung Seiten
  svg += `
    <text x="110" y="100" text-anchor="middle" font-size="9" fill="#4b5563">Raum</text>
  `;

  return svg;
}

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
// Status-Badge WebSocket
// ---------------------------------------------------------------------------

function initStatusBadge() {
  const badge = $("status-badge");
  if (!badge) return;
  // Benutze den gleichen WS wie oben
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

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadSelectors();
  initStatusBadge();
});
