"use strict";
/**
 * HausRadar – Kalibrierung: Raumverwaltung, Möbel/Türen hinzufügen,
 *             Türerkennung, Initialisierung
 *
 * Abhängigkeiten: calibrate-core.js, calibrate-overview.js, calibrate-editors.js
 */


function floorLabel(f) {
  if (f === 0)  return "Erdgeschoss";
  if (f === -1) return "Keller";
  if (f < -1)   return `${-f}. Untergeschoss`;
  return `${f}. Stock`;
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

/**
 * Bestätigungs-Toast nach einer Kalibrierungsänderung.
 * State ist bereits in app.state aktualisiert; config/reload läuft
 * als stille Sicherheitsprüfung im Hintergrund.
 */
async function showRestartHint() {
  let hint = document.getElementById("restart-hint-banner");
  if (!hint) {
    hint = document.createElement("div");
    hint.id = "restart-hint-banner";
    hint.style.cssText = `
      position:fixed;top:60px;left:50%;transform:translateX(-50%);
      background:#052e16;border:1px solid #22c55e;border-radius:8px;
      padding:10px 20px;font-size:.875rem;z-index:9999;
      box-shadow:0 4px 20px rgba(0,0,0,.5);text-align:center;min-width:220px`;
    document.body.appendChild(hint);
  }

  // Sofort Erfolg zeigen – State wurde bereits server-seitig aktualisiert
  hint.innerHTML = `✅ Gespeichert`;
  hint.style.display = "block";
  clearTimeout(hint._timer);
  hint._timer = setTimeout(() => { hint.style.display = "none"; }, 3000);

  // Config-Reload still im Hintergrund (Sicherheitsnetz)
  apiFetch("/api/config/reload", { method: "POST" }).catch(() => {});
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
        showEditModal(btnRename, `Raum bearbeiten: ${room.name}`, [
          { key: "name",  label: "Name",                              type: "text",   value: room.name },
          { key: "floor", label: "Etage (-1=Keller, 0=EG, 1=1.Stock)", type: "number", value: room.floor ?? 0 },
        ], async (updates) => {
          if (updates.floor !== undefined) updates.floor = parseInt(updates.floor) || 0;
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
        &nbsp;·&nbsp; ${floorLabel(room.floor ?? 0)}
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

    // Konfiguration live neu laden (kein Neustart nötig)
    await showRestartHint();

    // Ergebnis-Toast
    const resultEl = document.createElement("div");
    resultEl.style.cssText = `
      position:fixed;top:110px;left:50%;transform:translateX(-50%);
      background:#0c1a2e;border:1px solid #3b82f6;border-radius:8px;
      padding:10px 20px;font-size:.875rem;z-index:9998;
      box-shadow:0 4px 20px rgba(0,0,0,.5);text-align:center`;
    resultEl.innerHTML = `🗺 Grundriss neu berechnet – ${res.placed} Räume platziert<br>
      <small style="color:var(--muted)">Grundriss-Seite neu laden um die neuen Positionen zu sehen</small>`;
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
  const floor  = parseInt($("new-room-floor")?.value ?? "0") || 0;
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
        floor,
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
// Tür-Erkennung
// ---------------------------------------------------------------------------

const _WALL_DE = {
  top:    "Obere Wand",
  bottom: "Untere Wand",
  left:   "Linke Wand",
  right:  "Rechte Wand",
  // Altnamen (Kompatibilität mit alten Einträgen)
  north: "Obere Wand",
  south: "Untere Wand",
  west:  "Linke Wand",
  east:  "Rechte Wand",
};

// Gibt ein kleines SVG zurück das den Raum als Rechteck zeigt mit der Tür als Lücke
function _doorPreviewSvg(s, room) {
  if (!room) return "";
  const W = 130, H = 90, PAD = 10;
  const rw = room.width_mm || 4000, rh = room.height_mm || 4000;
  const scale = Math.min((W - PAD * 2) / rw, (H - PAD * 2) / rh);
  const sw = rw * scale, sh = rh * scale;
  const ox = PAD + (W - PAD * 2 - sw) / 2;
  const oy = PAD + (H - PAD * 2 - sh) / 2;

  const pos = s.position_mm * scale;
  const dw  = Math.max(s.width_mm * scale, 4);
  const GAP = 3;

  // Vier Wandlinien als Segmente zeichnen (mit Lücke für die Tür)
  let walls = "", door = "";
  switch (s.wall) {
    case "top":
      walls = `<line x1="${ox}" y1="${oy}" x2="${ox + pos}" y2="${oy}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox + pos + dw}" y1="${oy}" x2="${ox + sw}" y2="${oy}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy + sh}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy}" x2="${ox}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox + sw}" y1="${oy}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>`;
      door = `<rect x="${ox + pos}" y="${oy - GAP}" width="${dw}" height="${GAP * 2}" fill="#22d3ee" rx="1"/>`;
      break;
    case "bottom":
      walls = `<line x1="${ox}" y1="${oy + sh}" x2="${ox + pos}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox + pos + dw}" y1="${oy + sh}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy}" x2="${ox + sw}" y2="${oy}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy}" x2="${ox}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox + sw}" y1="${oy}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>`;
      door = `<rect x="${ox + pos}" y="${oy + sh - GAP}" width="${dw}" height="${GAP * 2}" fill="#22d3ee" rx="1"/>`;
      break;
    case "left":
      walls = `<line x1="${ox}" y1="${oy}" x2="${ox}" y2="${oy + pos}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy + pos + dw}" x2="${ox}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox + sw}" y1="${oy}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy}" x2="${ox + sw}" y2="${oy}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy + sh}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>`;
      door = `<rect x="${ox - GAP}" y="${oy + pos}" width="${GAP * 2}" height="${dw}" fill="#22d3ee" rx="1"/>`;
      break;
    case "right":
      walls = `<line x1="${ox + sw}" y1="${oy}" x2="${ox + sw}" y2="${oy + pos}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox + sw}" y1="${oy + pos + dw}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy}" x2="${ox}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy}" x2="${ox + sw}" y2="${oy}" stroke="#4a5568" stroke-width="1.5"/>
               <line x1="${ox}" y1="${oy + sh}" x2="${ox + sw}" y2="${oy + sh}" stroke="#4a5568" stroke-width="1.5"/>`;
      door = `<rect x="${ox + sw - GAP}" y="${oy + pos}" width="${GAP * 2}" height="${dw}" fill="#22d3ee" rx="1"/>`;
      break;
    default:
      walls = `<rect x="${ox}" y="${oy}" width="${sw}" height="${sh}" fill="none" stroke="#4a5568" stroke-width="1.5"/>`;
  }

  // Raumname-Label
  const label = (room.name || "").length > 10
    ? (room.name || "").slice(0, 10) + "…"
    : (room.name || "");

  return `<svg width="${W}" height="${H}"
    style="flex-shrink:0;border-radius:6px;background:#0a0d14;border:1px solid var(--border)">
    <rect x="${ox}" y="${oy}" width="${sw}" height="${sh}" fill="#13161f"/>
    ${walls}
    ${door}
    <text x="${ox + sw / 2}" y="${oy + sh / 2}" fill="#6b7280"
      font-size="9" text-anchor="middle" dominant-baseline="middle"
      font-family="system-ui,sans-serif">${esc(label)}</text>
  </svg>`;
}

async function loadDoorSuggestions() {
  const body  = $("door-suggestions-body");
  const stats = $("door-stats");
  if (!body) return;

  try {
    const [data, rooms] = await Promise.all([
      apiFetch("/api/doors/suggestions"),
      apiFetch("/api/rooms").catch(() => []),
    ]);
    const roomMap = Object.fromEntries((rooms || []).map(r => [r.id, r]));

    const s = data.stats || {};
    if (stats) stats.textContent =
      `${s.exit_events || 0} Exit-Events · ${s.entry_events || 0} Eintritte gesammelt`;

    const suggestions = data.suggestions || [];

    if (suggestions.length === 0) {
      body.innerHTML = `
        <div style="padding:16px 0;color:var(--muted);font-size:.875rem">
          <p>Noch keine Türen erkannt.</p>
          <p style="margin-top:6px">
            Bewege dich mehrfach durch alle Türöffnungen – nach etwa
            <strong style="color:var(--text)">4–10 Durchgängen</strong>
            pro Tür erscheinen hier Vorschläge.
          </p>
          <div style="margin-top:12px;padding:10px 14px;background:var(--surface);
                      border:1px solid var(--border);border-radius:6px;font-size:.8rem">
            💡 <strong>Tipp:</strong> Geh ins Wohnzimmer rein und raus, dann in die Küche,
            dann in den Flur – je öfter desto besser.
          </div>
        </div>`;
      return;
    }

    body.innerHTML = suggestions.map((s, i) => {
      const conf    = Math.round(s.confidence * 100);
      const confCol = conf >= 70 ? "var(--green)" : conf >= 40 ? "var(--yellow)" : "var(--muted)";
      const leadsTo = s.leads_to_name
        ? `<span style="color:var(--accent)">→ ${esc(s.leads_to_name)}</span>`
        : `<span style="color:var(--muted)">→ Ziel unbekannt</span>`;
      const preview = _doorPreviewSvg(s, roomMap[s.room_id]);

      return `
        <div class="door-candidate" id="door-cand-${i}">
          <div class="door-candidate__header">
            <span class="door-candidate__icon">🚪</span>
            <div>
              <strong>${esc(s.room_name)}</strong>
              &nbsp;·&nbsp;
              <span style="color:var(--muted)">${_WALL_DE[s.wall] || s.wall}</span>
              &nbsp;·&nbsp; ${leadsTo}
            </div>
            <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
              <span style="font-size:.78rem;color:${confCol}">
                ${conf}% sicher (${s.exit_count}×)
              </span>
              <button class="btn-mark door-confirm-btn"
                style="font-size:.78rem;padding:4px 10px;background:#15803d"
                data-door-index="${i}">
                ✓ Hinzufügen
              </button>
              <button class="btn-secondary door-ignore-btn"
                style="font-size:.78rem;padding:4px 8px"
                data-door-index="${i}">
                ✕
              </button>
            </div>
          </div>
          <div class="door-candidate__body">
            ${preview}
            <div class="door-candidate__meta">
              <div><strong>${esc(s.room_name)}</strong> · ${_WALL_DE[s.wall] || s.wall}</div>
              <div style="margin-top:4px">
                Position <strong>${s.position_mm} mm</strong> von der Ecke
                &nbsp;·&nbsp; Breite <strong>${s.width_mm} mm</strong>
                (${(s.width_mm / 10).toFixed(0)} cm)
              </div>
              <div style="margin-top:4px;color:${confCol};font-size:.8rem">
                ${conf}% Konfidenz · ${s.exit_count} gemessene Durchgänge
              </div>
            </div>
          </div>
        </div>`;
    }).join("");

    // Kandidaten-Daten für Confirm merken
    window._doorSuggestions = suggestions;

    // Event-Listener nach dem Rendern setzen (kein inline-onclick wg. CSP)
    body.querySelectorAll(".door-confirm-btn").forEach(btn => {
      btn.addEventListener("click", () => confirmDoor(Number(btn.dataset.doorIndex)));
    });
    body.querySelectorAll(".door-ignore-btn").forEach(btn => {
      btn.addEventListener("click", () => ignoreDoor(Number(btn.dataset.doorIndex)));
    });

  } catch (e) {
    if (body) body.innerHTML =
      `<p class="muted error-text">Fehler: ${esc(e.message)}</p>`;
  }
}

async function confirmDoor(index) {
  const s = (window._doorSuggestions || [])[index];
  if (!s) return;

  const el = $(`door-cand-${index}`);
  if (el) el.style.opacity = "0.5";

  try {
    await apiFetch("/api/doors/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        room_id:     s.room_id,
        wall:        s.wall,
        position_mm: s.position_mm,
        width_mm:    s.width_mm,
        leads_to:    s.leads_to || null,
      }),
    });

    await apiFetch("/api/config/reload", { method: "POST" });

    if (el) {
      el.style.opacity = "1";
      el.style.background = "#052e16";
      el.style.borderColor = "#15803d";
      el.querySelector(".door-candidate__header").innerHTML =
        `<span style="color:var(--green);font-size:1.1rem">✅</span>
         <span style="color:var(--green)">Tür hinzugefügt!</span>`;
    }

    setTimeout(() => loadDoorSuggestions(), 1500);
  } catch (e) {
    if (el) el.style.opacity = "1";
    alert(`Fehler: ${e.message}`);
  }
}

function ignoreDoor(index) {
  const el = $(`door-cand-${index}`);
  if (el) el.style.display = "none";
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadSelectors();
  loadRoomsMgmt();
  loadOverview();
  loadDoorSuggestions();
  initStatusBadge();

  $("btn-reload-overview")?.addEventListener("click", loadOverview);
  $("btn-reload-rooms")?.addEventListener("click",   loadRoomsMgmt);
  $("btn-layout")?.addEventListener("click",         recomputeLayout);
  $("btn-create-room")?.addEventListener("click",    handleCreateRoom);
  $("btn-refresh-doors")?.addEventListener("click",  loadDoorSuggestions);
  $("btn-clear-door-events")?.addEventListener("click", async () => {
    if (!confirm("Alle gesammelten Tür-Messdaten löschen?")) return;
    await apiFetch("/api/doors/events", { method: "DELETE" });
    await loadDoorSuggestions();
  });

  // Übersicht nach erfolgreichem Speichern automatisch aktualisieren
  document.addEventListener("calibration-saved", () => {
    loadOverview();
    loadRoomsMgmt();
  });

  // Tür-Vorschläge alle 30s automatisch aktualisieren
  setInterval(loadDoorSuggestions, 30_000);
});
