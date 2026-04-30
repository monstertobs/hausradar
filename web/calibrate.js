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
  doors:          [],   // {id, name, connects_to, points:{}, computed}
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

const TOTAL_STEPS = 8;

function gotoStep(n) {
  STATE.step = n;
  renderProgress();
  renderStep(n);
}

function renderProgress() {
  const bar = $("wizard-steps-bar");
  const labels = [
    "↖ H.L.", "↗ H.R.", "↘ V.R.", "↙ V.L.", "Vorschau", "Möbel", "Türen", "Speichern"
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
  else if (n === 7)     renderDoorStep(body);
  else if (n === 8)     renderSaveStep(body);
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

        <!-- Einzelpunkt-Nachkalibrierung -->
        <details style="margin:16px 0">
          <summary style="cursor:pointer;font-size:.875rem;color:var(--muted);
                          padding:8px 0;user-select:none">
            ⚙ Einzelne Punkte nachkalibrieren (bei Messfehlern)
          </summary>
          <div style="margin-top:12px;display:flex;flex-direction:column;gap:8px">
            ${Object.entries(STATE.markedCorners).map(([lbl, pos]) => {
              const info = STATE.cornerDisplay[lbl] || {};
              return `
                <div style="display:flex;align-items:center;justify-content:space-between;
                            padding:8px 12px;background:rgba(255,255,255,.04);border-radius:6px;
                            font-size:.85rem">
                  <span>
                    <strong>${esc(info.icon || "")} ${esc(info.de || lbl)}</strong>
                    <span style="color:var(--muted);margin-left:8px">
                      x=${pos.x_mm.toFixed(0)} mm, y=${pos.y_mm.toFixed(0)} mm
                    </span>
                  </span>
                  <button class="btn-secondary" style="font-size:.78rem;padding:3px 10px"
                    id="btn-remark-${esc(lbl)}">Neu markieren</button>
                </div>`;
            }).join("")}
          </div>
          <div id="remark-result" style="margin-top:8px"></div>
        </details>

        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn-mark" id="btn-next5">Weiter → Möbel</button>
          <button class="btn-secondary" id="btn-skip-furn">Möbel &amp; Türen überspringen</button>
        </div>
      </div>`;

    // Nachkalibrierungs-Buttons binden
    for (const lbl of Object.keys(STATE.markedCorners)) {
      const btn = $(`btn-remark-${lbl}`);
      if (!btn) continue;
      btn.addEventListener("click", async () => {
        btn.disabled    = true;
        btn.textContent = "Markiere …";
        $("remark-result").innerHTML = "";
        try {
          const res = await apiFetch(
            `/api/calibrate/session/${STATE.sessionId}/remark/${lbl}`,
            { method: "POST" }
          );
          STATE.markedCorners[lbl] = { x_mm: res.x_mm, y_mm: res.y_mm };
          $("remark-result").innerHTML =
            `<span style="color:var(--green)">✓ ${esc(lbl)} neu markiert – berechne …</span>`;
          // Neu berechnen und Vorschau aktualisieren
          const computed = await apiFetch(
            `/api/calibrate/session/${STATE.sessionId}/compute`,
            { method: "POST" }
          );
          STATE.computed = computed;
          renderPreviewStep($("wizard-body"));
        } catch (e) {
          $("remark-result").innerHTML =
            `<span style="color:var(--red)">✗ ${esc(e.message)}</span>`;
          btn.disabled    = false;
          btn.textContent = "Neu markieren";
        }
      });
    }

    $("btn-next5").addEventListener("click", () => gotoStep(6));
    $("btn-skip-furn").addEventListener("click", () => gotoStep(8));
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
        <button class="btn-mark" id="btn-next6">Weiter → Türen</button>
        <button class="btn-secondary" id="btn-skip-doors6">Türen überspringen</button>
      </div>
    </div>`;

  renderLiveIndicator();
  bindFurnitureEvents();

  $("btn-prev6").addEventListener("click", () => gotoStep(5));
  $("btn-next6").addEventListener("click", () => gotoStep(7));
  $("btn-skip-doors6").addEventListener("click", () => gotoStep(8));
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

// ─── Türen-Schritt (7) ──────────────────────────────────────────────────────

function renderDoorStep(body) {
  // Alle Räume für das Dropdown holen
  fetch("/api/rooms")
    .then(r => r.json())
    .then(rooms => renderDoorStepWithRooms(body, rooms))
    .catch(() => renderDoorStepWithRooms(body, []));
}

function renderDoorStepWithRooms(body, allRooms) {
  const otherRooms = allRooms.filter(r => r.id !== STATE.roomId);
  const roomOptions = otherRooms
    .map(r => `<option value="${esc(r.id)}">${esc(r.name)}</option>`)
    .join("");

  const doorListHtml = STATE.doors.length === 0
    ? `<p class="muted" style="font-size:.875rem">Noch keine Türen erfasst.</p>`
    : STATE.doors.map(d => doorItemHtml(d, allRooms)).join("");

  body.innerHTML = `
    <div class="wizard-panel">
      <h3>Schritt 7 – Türen erfassen <span style="color:var(--muted);font-weight:400">(optional)</span></h3>
      <p class="wizard-hint">
        Stell dich nacheinander an beide Kanten einer Türöffnung und markiere sie.
        Der Sensor berechnet automatisch auf welcher Wand die Tür liegt und wie breit sie ist.
        Gib an wohin die Tür führt – so entsteht die Verbindung zwischen den Räumen.
      </p>

      <!-- Tür hinzufügen -->
      <div class="add-furniture-form" style="grid-template-columns:1fr 1fr auto">
        <div class="form-group">
          <label class="form-label">Name</label>
          <input id="door-name" class="form-input" placeholder="z.B. Tür zur Küche" maxlength="40"/>
        </div>
        <div class="form-group">
          <label class="form-label">Führt zu</label>
          <select id="door-target" class="form-select">
            ${roomOptions.length
              ? roomOptions
              : `<option value="">– kein anderer Raum –</option>`}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">&nbsp;</label>
          <button class="btn-secondary" id="btn-add-door">+ Hinzufügen</button>
        </div>
      </div>

      <!-- Liste -->
      <div class="furniture-list" id="door-list">${doorListHtml}</div>

      <!-- Live-Position -->
      <div class="live-pos">
        <div class="live-pos-dot"></div>
        <span class="live-pos-text">–</span>
      </div>

      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn-secondary" id="btn-prev7">← Zurück</button>
        <button class="btn-mark" id="btn-next7">Weiter → Speichern</button>
      </div>
    </div>`;

  renderLiveIndicator();
  bindDoorEvents(allRooms);
  $("btn-prev7").addEventListener("click", () => gotoStep(6));
  $("btn-next7").addEventListener("click", () => gotoStep(8));
}

function doorItemHtml(d, allRooms) {
  const aOk = !!d.points?.a;
  const bOk = !!d.points?.b;
  const done = !!d.computed;
  const targetName = allRooms.find(r => r.id === d.connects_to)?.name || d.connects_to;

  let statusText = "Warte …";
  if (done) {
    const wallNames = { top: "oben", bottom: "unten", left: "links", right: "rechts" };
    statusText = `Wand ${wallNames[d.computed.wall] || d.computed.wall}, ` +
                 `${d.computed.width_mm} mm breit`;
  } else if (bOk) {
    statusText = "Berechne …";
  } else if (aOk) {
    statusText = "Kante A ✓";
  }

  return `
    <div class="furniture-item" id="di-${esc(d.id)}">
      <div class="furniture-item-info">
        <div class="furniture-item-name">${esc(d.name)}</div>
        <div class="furniture-item-meta">→ ${esc(targetName)}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn-secondary" style="font-size:.78rem;padding:4px 10px"
          id="btn-mark-da-${esc(d.id)}" ${done ? "disabled" : ""}>
          ${aOk ? "✓" : "📍"} Kante A
        </button>
        <button class="btn-secondary" style="font-size:.78rem;padding:4px 10px"
          id="btn-mark-db-${esc(d.id)}" ${done || !aOk ? "disabled" : ""}>
          ${bOk ? "✓" : "📍"} Kante B
        </button>
        <span class="furniture-item-status ${done ? "done" : ""}">${esc(statusText)}</span>
      </div>
    </div>`;
}

function bindDoorEvents(allRooms) {
  $("btn-add-door")?.addEventListener("click", async () => {
    const name       = $("door-name").value.trim();
    const connects_to = $("door-target")?.value || "";
    if (!name) { $("door-name").focus(); return; }

    try {
      const res = await apiFetch(
        `/api/calibrate/session/${STATE.sessionId}/door`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body:   JSON.stringify({ name, connects_to }),
        }
      );
      STATE.doors.push({ id: res.door_id, name, connects_to, points: {}, computed: null });
      $("door-name").value = "";
      refreshDoorList(allRooms);
    } catch (e) {
      alert("Fehler: " + e.message);
    }
  });

  for (const d of STATE.doors) {
    bindDoorPointBtn(d, "a", allRooms);
    bindDoorPointBtn(d, "b", allRooms);
  }
}

function bindDoorPointBtn(d, point, allRooms) {
  const btn = $(`btn-mark-d${point}-${d.id}`);
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled    = true;
    btn.textContent = "…";
    try {
      const res = await apiFetch(
        `/api/calibrate/session/${STATE.sessionId}/door/${d.id}/mark/${point}`,
        { method: "POST" }
      );
      d.points[point] = { x_mm: res.x_mm, y_mm: res.y_mm };

      if (res.ready) {
        const comp = await apiFetch(
          `/api/calibrate/session/${STATE.sessionId}/door/${d.id}/compute`,
          { method: "POST" }
        );
        d.computed = comp;
      }
      refreshDoorList(allRooms);
    } catch (e) {
      alert("Fehler: " + e.message);
      btn.disabled    = false;
      btn.textContent = `📍 Kante ${point.toUpperCase()}`;
    }
  });
}

function refreshDoorList(allRooms) {
  const list = $("door-list");
  if (!list) return;
  list.innerHTML = STATE.doors.length === 0
    ? `<p class="muted" style="font-size:.875rem">Noch keine Türen erfasst.</p>`
    : STATE.doors.map(d => doorItemHtml(d, allRooms)).join("");
  bindDoorEvents(allRooms);
}

// ─── Speichern-Schritt (8) ──────────────────────────────────────────────────

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
          <div class="result-item-label">Möbel / Türen</div>
          <div class="result-item-value">${readyFurn} / ${STATE.doors.filter(d=>d.computed).length}</div>
        </div>
      </div>

      ${totalFurn > 0 && readyFurn < totalFurn
        ? `<p style="color:var(--yellow);font-size:.875rem;margin-bottom:12px">
            ⚠ ${totalFurn - readyFurn} Möbelstück(e) nicht vollständig markiert – werden übersprungen.
           </p>` : ""}

      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
        <button class="btn-secondary" id="btn-prev8">← Zurück</button>
        <button class="btn-success" id="btn-save">💾 Jetzt speichern</button>
      </div>
      <div id="save-result"></div>
    </div>`;

  $("btn-prev8").addEventListener("click", () => gotoStep(7));
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
          ${res.doors_saved > 0
            ? `<p>${res.doors_saved} Tür(en) gespeichert.</p>` : ""}
          <p style="margin-top:12px">
            ⚠ <strong>Backend neu starten</strong> damit die Änderungen wirken:<br>
            <code>${esc(res.restart_hint)}</code>
          </p>
        </div>`;

      // Session-ID zurücksetzen (ist serverseitig gelöscht)
      STATE.sessionId = null;
      $("btn-save").textContent = "✓ Gespeichert";
      // Übersicht aktualisieren
      document.dispatchEvent(new Event("calibration-saved"));
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
// Übersicht gespeicherter Kalibrierungen
// ---------------------------------------------------------------------------

async function loadOverview() {
  const body = $("overview-body");
  body.innerHTML = `<p class="muted">Lade …</p>`;
  try {
    const rooms = await apiFetch("/api/calibrate/overview");
    renderOverview(rooms);
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">Fehler: ${esc(e.message)}</p>`;
  }
}

function renderOverview(rooms) {
  const body = $("overview-body");
  if (!rooms.length) {
    body.innerHTML = `<p class="muted">Keine Räume konfiguriert.</p>`;
    return;
  }

  body.innerHTML = rooms.map(room => overviewRoomHtml(room)).join("");

  // Events binden
  for (const room of rooms) {
    // Gesamtreset
    const btnReset = $(`btn-reset-room-${room.id}`);
    if (btnReset) {
      btnReset.addEventListener("click", () => confirmResetRoom(room.id, room.name));
    }
    // Alle Möbel löschen
    const btnClearFurn = $(`btn-clear-furn-${room.id}`);
    if (btnClearFurn) {
      btnClearFurn.addEventListener("click", () => confirmClearFurniture(room.id, room.name));
    }
    // Einzelne Möbel löschen + bearbeiten
    for (const f of (room.furniture || [])) {
      const btnDel = $(`btn-del-furn-${room.id}-${f.id}`);
      if (btnDel) {
        btnDel.addEventListener("click", () => confirmDeleteFurniture(room.id, f.id, f.name));
      }
      const btnEdit = $(`btn-edit-furn-${room.id}-${f.id}`);
      if (btnEdit) {
        btnEdit.addEventListener("click", (ev) => {
          ev.stopPropagation();
          editFurnitureItem(btnEdit, room.id, f, STATE.furnitureTypes);
        });
      }
    }
    // Einzelne Türen löschen + bearbeiten
    for (const d of (room.doors || [])) {
      const btnDel = $(`btn-del-door-${room.id}-${d.id}`);
      if (btnDel) {
        btnDel.addEventListener("click", () => confirmDeleteDoor(room.id, d.id, d.name));
      }
      const btnEdit = $(`btn-edit-door-${room.id}-${d.id}`);
      if (btnEdit) {
        btnEdit.addEventListener("click", (ev) => {
          ev.stopPropagation();
          editDoorItem(btnEdit, room.id, d, rooms);
        });
      }
    }
    // Möbel hinzufügen
    const btnAddFurn = $(`btn-add-furn-${room.id}`);
    if (btnAddFurn) {
      btnAddFurn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        addFurnitureToRoom(btnAddFurn, room.id, STATE.furnitureTypes);
      });
    }
    // Tür hinzufügen
    const btnAddDoor = $(`btn-add-door-${room.id}`);
    if (btnAddDoor) {
      btnAddDoor.addEventListener("click", (ev) => {
        ev.stopPropagation();
        addDoorToRoom(btnAddDoor, room.id, rooms);
      });
    }
    // Neue Kalibrierung für diesen Raum starten
    const btnCal = $(`btn-calibrate-room-${room.id}`);
    if (btnCal) {
      btnCal.addEventListener("click", () => prefillWizard(room));
    }
    // Raummaße bearbeiten
    const btnEditDims = $(`btn-edit-room-dims-${room.id}`);
    if (btnEditDims) {
      btnEditDims.addEventListener("click", (ev) => {
        ev.stopPropagation();
        editRoomDimensions(btnEditDims, room.id, room);
      });
    }
    // Sensorwerte bearbeiten
    for (const s of (room.sensors || [])) {
      const btnEditSensor = $(`btn-edit-sensor-${room.id}-${s.id}`);
      if (btnEditSensor) {
        btnEditSensor.addEventListener("click", (ev) => {
          ev.stopPropagation();
          editSensorValues(btnEditSensor, s.id, s);
        });
      }
    }
  }
}

function overviewRoomHtml(room) {
  const hasFurniture = (room.furniture || []).length > 0;
  const sensors      = room.sensors || [];

  const sensorHtml = sensors.length === 0
    ? `<span class="muted" style="font-size:.8rem">Kein Sensor</span>`
    : sensors.map(s => `
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <div style="font-size:.82rem;color:var(--muted)">
            <strong style="color:var(--text)">${esc(s.name)}</strong>
            · x=${(s.x_mm/1000).toFixed(2)} m
            · y=${(s.y_mm/1000).toFixed(2)} m
            · rot=${s.rotation_deg.toFixed(1)}°
            ${s.flip_x ? '· <span style="color:var(--yellow)">flip_x</span>' : ""}
            ${!s.enabled ? '· <span style="color:var(--red)">deaktiviert</span>' : ""}
          </div>
          <button class="btn-edit-icon" title="Sensorwerte bearbeiten"
            id="btn-edit-sensor-${esc(room.id)}-${esc(s.id)}">✏️</button>
        </div>`).join("");

  const furnitureHtml = `
    ${hasFurniture ? `
      <div class="furniture-list" style="margin-top:10px">
        ${(room.furniture || []).map(f => `
          <div class="furniture-item">
            <div class="furniture-item-info">
              <div class="furniture-item-name">${esc(f.name)}</div>
              <div class="furniture-item-meta">
                ${esc(f.type || "–")}
                · ${(f.width_mm/1000).toFixed(2)} m × ${(f.height_mm/1000).toFixed(2)} m
                · Position (${(f.x_mm/1000).toFixed(2)} m, ${(f.y_mm/1000).toFixed(2)} m)
              </div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
              <button class="btn-edit-icon" title="Bearbeiten"
                id="btn-edit-furn-${esc(room.id)}-${esc(f.id)}">✏️</button>
              <button class="btn-secondary"
                style="font-size:.75rem;padding:3px 10px;color:var(--red);border-color:var(--red)"
                id="btn-del-furn-${esc(room.id)}-${esc(f.id)}">🗑</button>
            </div>
          </div>`).join("")}
      </div>` : `<p class="muted" style="font-size:.8rem;margin:8px 0 0">Keine Möbel erfasst.</p>`}
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      <button class="btn-secondary" style="font-size:.78rem"
        id="btn-add-furn-${esc(room.id)}">＋ Möbel hinzufügen</button>
      ${hasFurniture ? `
        <button class="btn-secondary"
          style="font-size:.78rem;color:var(--red);border-color:var(--red)"
          id="btn-clear-furn-${esc(room.id)}">🗑 Alle löschen</button>` : ""}
    </div>`;

  return `
    <div class="calibration-overview-room" style="
      border:1px solid var(--border);border-radius:var(--radius);
      padding:16px;margin-bottom:12px">

      <!-- Kopfzeile -->
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
          <div style="font-weight:700;font-size:1rem">${esc(room.name)}</div>
          <div style="font-size:.82rem;color:var(--muted)">
            ${(room.width_mm/1000).toFixed(2)} m × ${(room.height_mm/1000).toFixed(2)} m
            · Fläche ~${((room.width_mm/1000)*(room.height_mm/1000)).toFixed(1)} m²
          </div>
          <button class="btn-edit-icon" title="Raummaße bearbeiten"
            id="btn-edit-room-dims-${esc(room.id)}">✏️</button>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn-secondary" style="font-size:.78rem"
            id="btn-calibrate-room-${esc(room.id)}">
            🎯 Neu kalibrieren
          </button>
          <button class="btn-secondary"
            style="font-size:.78rem;color:var(--red);border-color:var(--red)"
            id="btn-reset-room-${esc(room.id)}">
            ↺ Kalibrierung zurücksetzen
          </button>
        </div>
      </div>

      <!-- Sensor-Info -->
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;
                    letter-spacing:.05em;margin-bottom:6px">Sensor</div>
        ${sensorHtml}
      </div>

      <!-- Möbel -->
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;
                    letter-spacing:.05em;margin-bottom:4px">
          Möbel (${(room.furniture||[]).length})
        </div>
        ${furnitureHtml}
      </div>

      <!-- Türen -->
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;
                    letter-spacing:.05em;margin-bottom:4px">
          Türen (${(room.doors||[]).length})
        </div>
        ${overviewDoorsHtml(room)}
      </div>
    </div>`;
}

// ─── Bestätigungs-Dialoge + API-Calls ──────────────────────────────────────

function overviewDoorsHtml(room) {
  const doors     = room.doors || [];
  const wallNames = { top: "oben", bottom: "unten", left: "links", right: "rechts" };
  return `
    ${doors.length ? `
      <div class="furniture-list" style="margin-top:8px">
        ${doors.map(d => `
          <div class="furniture-item">
            <div class="furniture-item-info">
              <div class="furniture-item-name">${esc(d.name)}</div>
              <div class="furniture-item-meta">
                → ${esc(d.connects_to || "–")}
                · Wand ${esc(wallNames[d.wall] || d.wall)}
                · ${d.position_mm} mm ab Ecke
                · ${d.width_mm} mm breit
              </div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
              <button class="btn-edit-icon" title="Bearbeiten"
                id="btn-edit-door-${esc(room.id)}-${esc(d.id)}">✏️</button>
              <button class="btn-secondary"
                style="font-size:.75rem;padding:3px 10px;color:var(--red);border-color:var(--red)"
                id="btn-del-door-${esc(room.id)}-${esc(d.id)}">🗑</button>
            </div>
          </div>`).join("")}
      </div>` : `<p class="muted" style="font-size:.8rem;margin:4px 0 0">Keine Türen erfasst.</p>`}
    <div style="margin-top:10px">
      <button class="btn-secondary" style="font-size:.78rem"
        id="btn-add-door-${esc(room.id)}">＋ Tür hinzufügen</button>
    </div>`;
}

async function confirmDeleteDoor(roomId, doorId, doorName) {
  if (!confirm(`Tür "${doorName}" wirklich löschen?\n\nDer Dienst muss danach neu gestartet werden.`)) return;
  try {
    await apiFetch(`/api/calibrate/room/${roomId}/door/${doorId}`, { method: "DELETE" });
    showRestartHint();
    loadOverview();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

async function confirmDeleteFurniture(roomId, furnId, furnName) {
  if (!confirm(`Möbelstück "${furnName}" wirklich löschen?\n\nDer Dienst muss danach neu gestartet werden.`)) return;
  try {
    await apiFetch(`/api/calibrate/room/${roomId}/furniture/${furnId}`, { method: "DELETE" });
    showRestartHint();
    loadOverview();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

async function confirmClearFurniture(roomId, roomName) {
  if (!confirm(`Alle Möbel in "${roomName}" löschen?\n\nDer Dienst muss danach neu gestartet werden.`)) return;
  try {
    await apiFetch(`/api/calibrate/room/${roomId}/furniture`, { method: "DELETE" });
    showRestartHint();
    loadOverview();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

async function confirmResetRoom(roomId, roomName) {
  if (!confirm(
    `Kalibrierung für "${roomName}" vollständig zurücksetzen?\n\n` +
    `• Alle Möbel und Möbel-Zonen werden gelöscht\n` +
    `• Sensorposition wird auf Standardwerte zurückgesetzt\n\n` +
    `Der Dienst muss danach neu gestartet werden.`
  )) return;
  try {
    await apiFetch(`/api/calibrate/room/${roomId}/reset`, { method: "DELETE" });
    showRestartHint();
    loadOverview();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

// ---------------------------------------------------------------------------
// Inline-Bearbeitung gespeicherter Werte
// ---------------------------------------------------------------------------

/**
 * Zeigt ein schwebendes Edit-Modal direkt unter dem auslösenden Button.
 * fields = [{key, label, type, value, options?}]
 * onSave(updates) wird mit den geänderten Werten aufgerufen.
 */
function showEditModal(anchorEl, title, fields, onSave) {
  // Alte Modals entfernen
  document.querySelectorAll(".inline-edit-modal").forEach(m => m.remove());

  const modal = document.createElement("div");
  modal.className = "inline-edit-modal";
  modal.style.cssText = `
    position:fixed;z-index:9000;
    background:var(--surface,#151923);
    border:1px solid var(--border,#2d3448);
    border-radius:8px;padding:14px 16px;
    min-width:260px;max-width:360px;
    box-shadow:0 8px 32px rgba(0,0,0,.6);
    font-size:.875rem;`;

  let html = `<div style="font-weight:700;margin-bottom:10px;font-size:.9rem">${esc(title)}</div>`;
  for (const f of fields) {
    html += `<div style="margin-bottom:8px">
      <label style="display:block;font-size:.75rem;color:var(--muted,#888);margin-bottom:3px">${esc(f.label)}</label>`;
    if (f.type === "select" && f.options) {
      html += `<select class="form-input" data-key="${esc(f.key)}" style="width:100%">`;
      for (const [val, lbl] of Object.entries(f.options)) {
        html += `<option value="${esc(val)}" ${String(val) === String(f.value) ? "selected" : ""}>${esc(lbl)}</option>`;
      }
      html += `</select>`;
    } else if (f.type === "checkbox") {
      html += `<label style="display:flex;align-items:center;gap:6px;cursor:pointer">
        <input type="checkbox" data-key="${esc(f.key)}" ${f.value ? "checked" : ""}>
        <span style="font-size:.8rem;color:var(--text)">aktiviert</span>
      </label>`;
    } else {
      html += `<input class="form-input" type="${f.type || "text"}"
        data-key="${esc(f.key)}" value="${esc(String(f.value ?? ""))}"
        style="width:100%;box-sizing:border-box">`;
    }
    html += `</div>`;
  }
  html += `<div style="display:flex;gap:8px;margin-top:12px">
    <button class="btn-mark" id="edit-modal-save" style="flex:1;font-size:.8rem;padding:6px 0">Speichern</button>
    <button class="btn-secondary" id="edit-modal-cancel" style="font-size:.8rem;padding:6px 12px">Abbrechen</button>
  </div>`;
  modal.innerHTML = html;

  document.body.appendChild(modal);

  // Position relativ zum Anker
  const rect = anchorEl.getBoundingClientRect();
  const mw = 360;
  let left = rect.left;
  if (left + mw > window.innerWidth - 12) left = window.innerWidth - mw - 12;
  let top = rect.bottom + 6;
  modal.style.left = left + "px";
  modal.style.top  = top + "px";

  // Schließen
  const close = () => modal.remove();

  modal.querySelector("#edit-modal-cancel").addEventListener("click", close);

  modal.querySelector("#edit-modal-save").addEventListener("click", async () => {
    const updates = {};
    for (const f of fields) {
      const el = modal.querySelector(`[data-key="${f.key}"]`);
      if (!el) continue;
      if (f.type === "checkbox") {
        updates[f.key] = el.checked;
      } else if (f.type === "number") {
        const v = parseFloat(el.value);
        if (!isNaN(v)) updates[f.key] = v;
      } else {
        if (el.value.trim() !== "") updates[f.key] = el.value.trim();
      }
    }
    try {
      await onSave(updates);
      close();
    } catch (e) {
      // Fehler bereits in onSave behandelt, Modal bleibt offen
    }
  });

  // Klick außerhalb schließt
  setTimeout(() => {
    document.addEventListener("click", function outsideClick(ev) {
      if (!modal.contains(ev.target) && ev.target !== anchorEl) {
        close();
        document.removeEventListener("click", outsideClick);
      }
    });
  }, 10);
}

async function editRoomDimensions(anchorEl, roomId, room) {
  showEditModal(anchorEl, `Raummaße: ${room.name}`, [
    { key: "width_mm",  label: "Breite (mm)",  type: "number", value: room.width_mm  },
    { key: "height_mm", label: "Tiefe (mm)",   type: "number", value: room.height_mm },
  ], async (updates) => {
    await apiFetch(`/api/calibrate/room/${roomId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    showRestartHint();
    loadOverview();
  });
}

async function editSensorValues(anchorEl, sensorId, sensor) {
  showEditModal(anchorEl, `Sensor: ${sensor.name}`, [
    { key: "x_mm",         label: "Position x (mm)",    type: "number", value: sensor.x_mm         },
    { key: "y_mm",         label: "Position y (mm)",    type: "number", value: sensor.y_mm         },
    { key: "rotation_deg", label: "Rotation (°)",        type: "number", value: sensor.rotation_deg },
    { key: "flip_x",       label: "Spiegelung (flip_x)", type: "checkbox", value: !!sensor.flip_x  },
  ], async (updates) => {
    await apiFetch(`/api/calibrate/sensor/${sensorId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    showRestartHint();
    loadOverview();
  });
}

async function editFurnitureItem(anchorEl, roomId, furn, furnitureTypes) {
  const typeOptions = Object.fromEntries(
    Object.entries(furnitureTypes || {}).map(([k, v]) => [k, v.de || k])
  );
  if (!Object.keys(typeOptions).length) {
    typeOptions.sofa = "Sofa/Couch"; typeOptions.chair = "Stuhl/Sessel";
    typeOptions.table = "Tisch"; typeOptions.desk = "Schreibtisch";
    typeOptions.bed = "Bett"; typeOptions.cabinet = "Schrank"; typeOptions.other = "Sonstiges";
  }
  showEditModal(anchorEl, `Möbel: ${furn.name}`, [
    { key: "name",      label: "Name",          type: "text",   value: furn.name      },
    { key: "type",      label: "Typ",           type: "select", value: furn.type || "other", options: typeOptions },
    { key: "x_mm",      label: "Position x (mm)", type: "number", value: furn.x_mm   },
    { key: "y_mm",      label: "Position y (mm)", type: "number", value: furn.y_mm   },
    { key: "width_mm",  label: "Breite (mm)",   type: "number", value: furn.width_mm  },
    { key: "height_mm", label: "Tiefe (mm)",    type: "number", value: furn.height_mm },
  ], async (updates) => {
    await apiFetch(`/api/calibrate/room/${roomId}/furniture/${furn.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    showRestartHint();
    loadOverview();
  });
}

async function editDoorItem(anchorEl, roomId, door, allRooms) {
  const roomOptions = Object.fromEntries((allRooms || []).map(r => [r.id, r.name]));
  const wallOptions = { top: "Oben (Sensorwand)", bottom: "Unten", left: "Links", right: "Rechts" };
  showEditModal(anchorEl, `Tür: ${door.name}`, [
    { key: "name",        label: "Name",               type: "text",   value: door.name        },
    { key: "connects_to", label: "Führt zu (Raum-ID)", type: "text",   value: door.connects_to || "" },
    { key: "wall",        label: "Wand",               type: "select", value: door.wall,  options: wallOptions },
    { key: "position_mm", label: "Abstand Ecke (mm)",  type: "number", value: door.position_mm },
    { key: "width_mm",    label: "Breite (mm)",         type: "number", value: door.width_mm    },
  ], async (updates) => {
    await apiFetch(`/api/calibrate/room/${roomId}/door/${door.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    showRestartHint();
    loadOverview();
  });
}

// ---------------------------------------------------------------------------
// Möbel / Tür direkt zur gespeicherten Kalibrierung hinzufügen
// ---------------------------------------------------------------------------

async function addFurnitureToRoom(anchorEl, roomId, furnitureTypes) {
  const typeOptions = Object.fromEntries(
    Object.entries(furnitureTypes || {}).map(([k, v]) => [k, v.de || k])
  );
  if (!Object.keys(typeOptions).length) {
    typeOptions.sofa = "Sofa/Couch"; typeOptions.chair = "Stuhl/Sessel";
    typeOptions.table = "Tisch"; typeOptions.desk = "Schreibtisch";
    typeOptions.bed = "Bett"; typeOptions.cabinet = "Schrank"; typeOptions.other = "Sonstiges";
  }
  showEditModal(anchorEl, "Möbel hinzufügen", [
    { key: "name",      label: "Name",            type: "text",     value: "" },
    { key: "type",      label: "Typ",             type: "select",   value: "other", options: typeOptions },
    { key: "x_mm",      label: "Position x (mm)", type: "number",   value: 500 },
    { key: "y_mm",      label: "Position y (mm)", type: "number",   value: 500 },
    { key: "width_mm",  label: "Breite (mm)",     type: "number",   value: 800 },
    { key: "height_mm", label: "Tiefe (mm)",      type: "number",   value: 800 },
    { key: "is_zone",   label: "Als Zone",        type: "checkbox", value: false },
  ], async (fields) => {
    if (!fields.name) { alert("Bitte einen Namen eingeben."); return; }
    await apiFetch(`/api/calibrate/room/${roomId}/furniture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:      fields.name,
        type:      fields.type || "other",
        x_mm:      Number(fields.x_mm)      || 0,
        y_mm:      Number(fields.y_mm)      || 0,
        width_mm:  Number(fields.width_mm)  || 100,
        height_mm: Number(fields.height_mm) || 100,
        is_zone:   !!fields.is_zone,
      }),
    });
    showRestartHint();
    loadOverview();
  });
}

async function addDoorToRoom(anchorEl, roomId, allRooms) {
  const roomOptions = { "": "– (Außentür / kein Ziel)" };
  for (const r of (allRooms || [])) roomOptions[r.id] = r.name;
  const wallOptions = { top: "Oben (y=0-Wand)", bottom: "Unten", left: "Links", right: "Rechts" };
  showEditModal(anchorEl, "Tür hinzufügen", [
    { key: "name",        label: "Name",               type: "text",   value: "Tür" },
    { key: "connects_to", label: "Führt zu",           type: "select", value: "", options: roomOptions },
    { key: "wall",        label: "Wand",               type: "select", value: "top", options: wallOptions },
    { key: "position_mm", label: "Abstand Ecke (mm)",  type: "number", value: 500 },
    { key: "width_mm",    label: "Breite (mm)",        type: "number", value: 900 },
  ], async (fields) => {
    if (!fields.name) { alert("Bitte einen Namen eingeben."); return; }
    await apiFetch(`/api/calibrate/room/${roomId}/door`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:        fields.name,
        connects_to: fields.connects_to || "",
        wall:        fields.wall || "top",
        position_mm: Number(fields.position_mm) || 0,
        width_mm:    Number(fields.width_mm)    || 900,
      }),
    });
    showRestartHint();
    loadOverview();
  });
}

function showRestartHint() {
  // Kurze Einblendung oben auf der Seite
  let hint = document.getElementById("restart-hint-banner");
  if (!hint) {
    hint = document.createElement("div");
    hint.id = "restart-hint-banner";
    hint.style.cssText = `
      position:fixed;top:60px;left:50%;transform:translateX(-50%);
      background:#052e16;border:1px solid #22c55e;border-radius:8px;
      padding:10px 20px;font-size:.875rem;z-index:9999;
      box-shadow:0 4px 20px rgba(0,0,0,.5)`;
    document.body.appendChild(hint);
  }
  hint.innerHTML = `✅ Gespeichert &nbsp;·&nbsp; <code style="color:#86efac">sudo systemctl restart hausradar</code>`;
  hint.style.display = "block";
  clearTimeout(hint._timer);
  hint._timer = setTimeout(() => { hint.style.display = "none"; }, 6000);
}

// Wizard mit vorausgefülltem Sensor/Raum starten
function prefillWizard(room) {
  const firstSensor = (room.sensors || [])[0];
  if (firstSensor) {
    const selSensor = $("sel-sensor");
    if (selSensor) {
      selSensor.value = firstSensor.id;
      selSensor.dispatchEvent(new Event("change"));
    }
  }
  // Smooth-scroll zum Wizard
  const wizardSection = $("step-select");
  if (wizardSection) {
    wizardSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ---------------------------------------------------------------------------
// Räume & Sensoren verwalten
// ---------------------------------------------------------------------------

async function loadRoomsMgmt() {
  const body = $("rooms-mgmt-body");
  body.innerHTML = `<p class="muted">Lade …</p>`;
  try {
    const [rooms, sensors] = await Promise.all([
      apiFetch("/api/rooms"),
      apiFetch("/api/sensors"),
    ]);
    renderRoomsMgmt(rooms, sensors);
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">Fehler: ${esc(e.message)}</p>`;
  }
}

function renderRoomsMgmt(rooms, sensors) {
  const body = $("rooms-mgmt-body");
  if (!rooms.length) {
    body.innerHTML = `<p class="muted">Keine Räume konfiguriert.</p>`;
    return;
  }

  // Sensoren nach Raum gruppieren
  const sensorsByRoom = {};
  for (const s of sensors) {
    if (!sensorsByRoom[s.room_id]) sensorsByRoom[s.room_id] = [];
    sensorsByRoom[s.room_id].push(s);
  }

  body.innerHTML = `
    <div style="display:grid;gap:8px">
      ${rooms.map(r => roomMgmtRowHtml(r, sensorsByRoom[r.id] || [])).join("")}
    </div>`;

  // Events binden
  for (const room of rooms) {
    // Raum umbenennen
    const btnRename = $(`btn-rename-room-${room.id}`);
    if (btnRename) {
      btnRename.addEventListener("click", (ev) => {
        ev.stopPropagation();
        showEditModal(btnRename, `Raum umbenennen: ${room.name}`, [
          { key: "name", label: "Neuer Name", type: "text", value: room.name },
        ], async (updates) => {
          await apiFetch(`/api/rooms/${room.id}`, {
            method:  "PATCH",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(updates),
          });
          showRestartHint();
          loadRoomsMgmt();
          loadOverview();
        });
      });
    }
    // Raum löschen
    const btnDel = $(`btn-delete-room-${room.id}`);
    if (btnDel) {
      btnDel.addEventListener("click", () => confirmDeleteRoom(room.id, room.name));
    }
    // Sensor hinzufügen
    const btnAddSensor = $(`btn-add-sensor-${room.id}`);
    if (btnAddSensor) {
      btnAddSensor.addEventListener("click", (ev) => {
        ev.stopPropagation();
        showEditModal(btnAddSensor, `Sensor hinzufügen: ${room.name}`, [
          { key: "name",            label: "Sensor-Name",        type: "text",   value: `Radar ${room.name}` },
          { key: "mount_height_mm", label: "Montagehöhe (mm)",   type: "number", value: 2200 },
        ], async (updates) => {
          await apiFetch("/api/sensors", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ room_id: room.id, ...updates }),
          });
          showRestartHint();
          loadRoomsMgmt();
          loadSelectors();
        });
      });
    }
    // Sensor umbenennen / deaktivieren
    for (const s of (sensorsByRoom[room.id] || [])) {
      const btnEditSensor = $(`btn-mgmt-edit-sensor-${s.id}`);
      if (btnEditSensor) {
        btnEditSensor.addEventListener("click", (ev) => {
          ev.stopPropagation();
          showEditModal(btnEditSensor, `Sensor bearbeiten: ${s.name}`, [
            { key: "name",            label: "Name",              type: "text",     value: s.name },
            { key: "enabled",         label: "Aktiv",             type: "checkbox", value: s.enabled !== false },
            { key: "mount_height_mm", label: "Montagehöhe (mm)",  type: "number",   value: s.mount_height_mm || 2200 },
          ], async (updates) => {
            await apiFetch(`/api/sensors/${s.id}`, {
              method:  "PATCH",
              headers: { "Content-Type": "application/json" },
              body:    JSON.stringify(updates),
            });
            showRestartHint();
            loadRoomsMgmt();
            loadSelectors();
          });
        });
      }
      const btnDelSensor = $(`btn-mgmt-del-sensor-${s.id}`);
      if (btnDelSensor) {
        btnDelSensor.addEventListener("click", () => confirmDeleteSensor(s.id, s.name));
      }
    }
  }
}

function roomMgmtRowHtml(room, sensors) {
  const sensorBadges = sensors.length === 0
    ? `<span class="muted" style="font-size:.78rem">kein Sensor</span>`
    : sensors.map(s => `
        <span style="display:inline-flex;align-items:center;gap:4px;
              font-size:.78rem;background:var(--border);border-radius:4px;
              padding:2px 6px;color:${s.enabled === false ? 'var(--red)' : 'var(--text)'}">
          📡 ${esc(s.name)}
          <button class="btn-edit-icon" id="btn-mgmt-edit-sensor-${esc(s.id)}"
            title="Bearbeiten" style="font-size:.7rem">✏️</button>
          <button class="btn-edit-icon" id="btn-mgmt-del-sensor-${esc(s.id)}"
            title="Löschen" style="font-size:.7rem;color:var(--red)">✕</button>
        </span>`).join(" ");

  return `
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;
                padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius)">
      <!-- Raumname -->
      <div style="font-weight:600;min-width:130px">${esc(room.name)}</div>
      <!-- Abmessungen -->
      <div style="font-size:.78rem;color:var(--muted);white-space:nowrap">
        ${(room.width_mm/1000).toFixed(1)} m × ${(room.height_mm/1000).toFixed(1)} m
      </div>
      <!-- Sensoren -->
      <div style="display:flex;flex-wrap:wrap;gap:4px;flex:1">${sensorBadges}</div>
      <!-- Aktionen -->
      <div style="display:flex;gap:6px;flex-shrink:0;margin-left:auto">
        <button class="btn-secondary" style="font-size:.75rem;padding:4px 10px"
          id="btn-add-sensor-${esc(room.id)}" title="Sensor hinzufügen">+ Sensor</button>
        <button class="btn-edit-icon" style="padding:4px 8px"
          id="btn-rename-room-${esc(room.id)}" title="Umbenennen">✏️</button>
        <button class="btn-edit-icon"
          style="padding:4px 8px;color:var(--red)"
          id="btn-delete-room-${esc(room.id)}" title="Raum löschen">🗑</button>
      </div>
    </div>`;
}

async function confirmDeleteRoom(roomId, roomName) {
  if (!confirm(
    `Raum "${roomName}" wirklich löschen?\n\n` +
    `• Alle zugehörigen Sensoren werden ebenfalls gelöscht\n` +
    `• Türverweise anderer Räume auf diesen Raum werden geleert\n\n` +
    `Der Dienst muss danach neu gestartet werden.`
  )) return;
  try {
    await apiFetch(`/api/rooms/${roomId}`, { method: "DELETE" });
    showRestartHint();
    loadRoomsMgmt();
    loadOverview();
    loadSelectors();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

async function confirmDeleteSensor(sensorId, sensorName) {
  if (!confirm(`Sensor "${sensorName}" wirklich löschen?\n\nDer Dienst muss danach neu gestartet werden.`)) return;
  try {
    await apiFetch(`/api/sensors/${sensorId}`, { method: "DELETE" });
    showRestartHint();
    loadRoomsMgmt();
    loadSelectors();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

// Grundriss-Auto-Layout
async function recomputeLayout() {
  const btn = $("btn-layout");
  if (btn) { btn.disabled = true; btn.textContent = "🗺 Berechne …"; }
  try {
    const res = await apiFetch("/api/calibrate/layout", { method: "POST" });
    showRestartHint();
    // Hinweis mit Ergebnis
    const resultEl = document.createElement("div");
    resultEl.style.cssText = `
      position:fixed;top:60px;left:50%;transform:translateX(-50%);
      background:#0c1a2e;border:1px solid #3b82f6;border-radius:8px;
      padding:10px 20px;font-size:.875rem;z-index:9999;
      box-shadow:0 4px 20px rgba(0,0,0,.5)`;
    resultEl.innerHTML = `🗺 Grundriss neu berechnet – ${res.placed} Räume platziert<br>
      <small style="color:var(--muted)">Neustart erforderlich um die Änderungen zu sehen</small>`;
    document.body.appendChild(resultEl);
    setTimeout(() => resultEl.remove(), 6000);
  } catch (e) {
    alert("Fehler beim Layout: " + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🗺 Grundriss neu berechnen"; }
  }
}

// Neuen Raum anlegen (Formular)
async function handleCreateRoom() {
  const name   = $("new-room-name").value.trim();
  const width  = parseInt($("new-room-width").value)  || 5000;
  const height = parseInt($("new-room-height").value) || 4000;
  const sensor = $("new-room-sensor").value.trim();

  if (!name) {
    $("create-room-result").innerHTML = `<span style="color:var(--red)">Bitte Raumname eingeben.</span>`;
    return;
  }

  const btn = $("btn-create-room");
  btn.disabled = true;
  $("create-room-result").innerHTML = "";

  try {
    const res = await apiFetch("/api/rooms", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        name,
        width_mm:    width,
        height_mm:   height,
        sensor_name: sensor || null,
      }),
    });
    $("create-room-result").innerHTML = `
      <span style="color:var(--green)">
        ✓ Raum <strong>${esc(res.room.name)}</strong> angelegt
        (ID: <code>${esc(res.room.id)}</code>)
        ${res.sensor ? ` · Sensor <strong>${esc(res.sensor.name)}</strong>` : ""}
      </span>`;
    // Felder leeren
    $("new-room-name").value   = "";
    $("new-room-sensor").value = "";
    showRestartHint();
    loadRoomsMgmt();
    loadSelectors();
    loadOverview();
  } catch (e) {
    $("create-room-result").innerHTML = `<span style="color:var(--red)">Fehler: ${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadSelectors();
  loadRoomsMgmt();
  loadOverview();
  initStatusBadge();

  $("btn-reload-overview")?.addEventListener("click", loadOverview);
  $("btn-reload-rooms")?.addEventListener("click",   loadRoomsMgmt);
  $("btn-layout")?.addEventListener("click",         recomputeLayout);
  $("btn-create-room")?.addEventListener("click",    handleCreateRoom);

  // Übersicht nach erfolgreichem Speichern automatisch aktualisieren
  document.addEventListener("calibration-saved", () => {
    loadOverview();
    loadRoomsMgmt();
  });
});
