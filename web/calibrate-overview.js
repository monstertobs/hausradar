"use strict";
/**
 * HausRadar – Kalibrierung: Übersicht & Inline-Editoren
 *
 * Abhängigkeiten: calibrate-core.js (STATE, $, apiFetch)
 */

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
    // Layout-Editor
    const btnLayout = $(`btn-layout-room-${room.id}`);
    if (btnLayout) {
      btnLayout.addEventListener("click", () => openRoomLayoutEditor(room, rooms));
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
    // Alle Zonen löschen
    const btnClearZones = $(`btn-clear-zones-${room.id}`);
    if (btnClearZones) {
      btnClearZones.addEventListener("click", (ev) => {
        ev.stopPropagation();
        confirmClearZones(room.id, room.name);
      });
    }
    // Einzelne Zonen löschen
    const standaloneZones = (room.zones || []).filter(z => {
      const furnIds = new Set((room.furniture || []).map(f => f.id));
      return !furnIds.has(z.id);
    });
    for (const z of standaloneZones) {
      const btnDelZone = $(`btn-del-zone-${room.id}-${z.id}`);
      if (btnDelZone) {
        btnDelZone.addEventListener("click", (ev) => {
          ev.stopPropagation();
          confirmDeleteZone(room.id, z.id, z.name);
        });
      }
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
    // Raumform bearbeiten
    const btnEditShape = $(`btn-edit-room-shape-${room.id}`);
    if (btnEditShape) {
      btnEditShape.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openRoomShapeEditor(room);
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
          <button class="btn-edit-icon" title="Raumform bearbeiten"
            id="btn-edit-room-shape-${esc(room.id)}">🔷</button>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${(room.furniture||[]).length || (room.doors||[]).length ? `
          <button class="btn-secondary" style="font-size:.78rem"
            id="btn-layout-room-${esc(room.id)}">
            📐 Layout verschieben
          </button>` : ""}
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

      <!-- Zonen -->
      ${overviewZonesHtml(room)}
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

function overviewZonesHtml(room) {
  const zones = (room.zones || []).filter(z => {
    // Nur Zonen zeigen die NICHT aus einem Möbelstück stammen
    // (Möbel-Zonen haben dieselbe id wie das Möbelstück)
    const furnIds = new Set((room.furniture || []).map(f => f.id));
    return !furnIds.has(z.id);
  });
  if (!zones.length) return "";

  return `
    <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">
          Zonen (${zones.length})
        </div>
        <button class="btn-secondary"
          style="font-size:.72rem;padding:2px 10px;color:var(--red);border-color:var(--red)"
          id="btn-clear-zones-${esc(room.id)}">🗑 Alle löschen</button>
      </div>
      <div class="furniture-list" style="margin-top:6px">
        ${zones.map(z => `
          <div class="furniture-item">
            <div class="furniture-item-info">
              <div class="furniture-item-name">${esc(z.name)}</div>
              <div class="furniture-item-meta">
                ${(z.width_mm/1000).toFixed(2)} m × ${(z.height_mm/1000).toFixed(2)} m
                · Position (${(z.x_mm/1000).toFixed(2)} m, ${(z.y_mm/1000).toFixed(2)} m)
              </div>
            </div>
            <button class="btn-secondary"
              style="font-size:.75rem;padding:3px 10px;color:var(--red);border-color:var(--red);flex-shrink:0"
              id="btn-del-zone-${esc(room.id)}-${esc(z.id)}">🗑</button>
          </div>`).join("")}
      </div>
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

async function confirmDeleteZone(roomId, zoneId, zoneName) {
  if (!confirm(`Zone "${zoneName}" wirklich löschen?\n\nDer Dienst muss danach neu gestartet werden.`)) return;
  try {
    await apiFetch(`/api/calibrate/room/${roomId}/zone/${zoneId}`, { method: "DELETE" });
    showRestartHint();
    loadOverview();
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

async function confirmClearZones(roomId, roomName) {
  if (!confirm(`Alle Zonen aus "${roomName}" löschen?\n\nDer Dienst muss danach neu gestartet werden.`)) return;
  try {
    await apiFetch(`/api/calibrate/room/${roomId}/zones`, { method: "DELETE" });
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

