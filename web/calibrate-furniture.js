"use strict";
/**
 * HausRadar – Möbel-Erkennung (M22)
 *
 * Zeigt erkannte Dwell-Zonen mit Möbeltyp-Vorschlägen an.
 * Lädt alle 15s neu. Ermöglicht manuelles Bestätigen oder Löschen.
 */

const FURNITURE_POLL_MS = 15_000;
let _furnitureTimer = null;

const FURNITURE_TYPE_LABEL = {
  sofa:  "Sofa / Couch",
  chair: "Stuhl / Sessel",
  table: "Esstisch",
  desk:  "Schreibtisch",
  bed:   "Bett",
  other: "Sonstiges",
};

const FURNITURE_TYPE_ICON = {
  sofa:  "🛋",
  chair: "🪑",
  table: "🍽",
  desk:  "💻",
  bed:   "🛏",
  other: "📦",
};

// ──────────────────────────────────────────────────────────────────────────────
// Initialisierung
// ──────────────────────────────────────────────────────────────────────────────

async function initFurnitureList() {
  await renderFurnitureList();
  _furnitureTimer = setInterval(renderFurnitureList, FURNITURE_POLL_MS);
}

async function renderFurnitureList() {
  const container = document.getElementById("furniture-zones-body");
  if (!container) return;

  let data;
  try {
    data = await apiFetch("/api/furniture/zones");
  } catch (err) {
    container.innerHTML = `<p class="muted">Fehler beim Laden: ${esc(String(err))}</p>`;
    return;
  }

  const zones = data.zones || [];
  if (zones.length === 0) {
    container.innerHTML = `
      <p class="muted" style="font-size:.85rem">
        Noch keine Zonen erkannt. Bewege dich im Raum und halte dich an verschiedenen Stellen
        auf – nach einigen Minuten erscheinen hier Möbel-Vorschläge.
      </p>`;
    return;
  }

  // Gruppieren nach Raum
  const byRoom = {};
  for (const z of zones) {
    (byRoom[z.room_id] = byRoom[z.room_id] || []).push(z);
  }

  container.innerHTML = Object.entries(byRoom).map(([roomId, roomZones]) => `
    <div style="margin-bottom:20px">
      <h3 style="font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;
                 color:var(--muted);margin:0 0 10px">${esc(roomId)}</h3>
      <div style="display:grid;gap:8px">
        ${roomZones.map(z => _renderZoneCard(z)).join("")}
      </div>
    </div>`).join("");

  // Event-Listener
  for (const z of zones) {
    const delBtn = document.getElementById(`furn-del-${z.id}`);
    if (delBtn) delBtn.addEventListener("click", () => deleteFurnitureZone(z.id));

    const selEl = document.getElementById(`furn-type-${z.id}`);
    if (selEl) selEl.addEventListener("change", () => confirmFurnitureType(z.id, selEl.value));
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Karte für eine Dwell-Zone
// ──────────────────────────────────────────────────────────────────────────────

function _renderZoneCard(z) {
  const icon     = FURNITURE_TYPE_ICON[z.suggested_type] || "📦";
  const confPct  = Math.round(z.confidence * 100);
  const confCol  = z.confidence >= 0.55 ? "#22c55e" :
                   z.confidence >= 0.35 ? "#f59e0b" : "#6b7280";
  const avg      = z.avg_dwell_s;
  const avgStr   = avg >= 60 ? `${Math.round(avg / 60)} min` : `${Math.round(avg)} s`;
  const confirmed = z.confirmed_type;

  const typeOptions = Object.entries(FURNITURE_TYPE_LABEL).map(([val, lbl]) => `
    <option value="${val}" ${(confirmed || z.suggested_type) === val ? "selected" : ""}>${lbl}</option>
  `).join("");

  return `
    <div style="display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;
                padding:10px 14px;border:1px solid var(--card-border);border-radius:8px;
                ${confirmed ? 'background:var(--card-bg)' : ''}">
      <span style="font-size:1.6rem;line-height:1">${icon}</span>
      <div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
          <strong style="font-size:.9rem">${esc(FURNITURE_TYPE_LABEL[z.suggested_type] || z.suggested_type)}</strong>
          <span style="font-size:10px;padding:1px 7px;border-radius:8px;
                       background:${confCol}22;color:${confCol}">${confPct}%</span>
          ${confirmed ? `<span style="font-size:10px;color:var(--accent)">✓ bestätigt</span>` : ""}
        </div>
        <div style="font-size:11px;color:var(--text-muted);display:flex;gap:12px;flex-wrap:wrap">
          <span>Ø ${avgStr} Verweildauer</span>
          <span>${z.visit_count}× besucht</span>
          <span>r = ${Math.round(z.radius_mm)} mm</span>
        </div>
        <div style="margin-top:6px;display:flex;align-items:center;gap:8px">
          <label style="font-size:11px;color:var(--text-muted)">Typ:</label>
          <select id="furn-type-${esc(z.id)}" class="form-select" style="font-size:11px;padding:2px 6px">
            ${typeOptions}
          </select>
        </div>
      </div>
      <button id="furn-del-${esc(z.id)}"
              class="btn-secondary"
              style="font-size:11px;color:var(--red);border-color:var(--red)"
              title="Zone löschen">🗑</button>
    </div>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Aktionen
// ──────────────────────────────────────────────────────────────────────────────

async function confirmFurnitureType(zoneId, type) {
  try {
    await apiFetch(`/api/furniture/zones/${encodeURIComponent(zoneId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed_type: type }),
    });
    showCalToast(`✓ Typ als "${FURNITURE_TYPE_LABEL[type] || type}" gespeichert`);
    await renderFurnitureList();
  } catch (err) {
    showCalToast(`⚠ Fehler: ${esc(String(err))}`, true);
  }
}

async function deleteFurnitureZone(zoneId) {
  try {
    await apiFetch(`/api/furniture/zones/${encodeURIComponent(zoneId)}`, { method: "DELETE" });
    showCalToast("Zone gelöscht.");
    await renderFurnitureList();
  } catch (err) {
    showCalToast(`⚠ Fehler: ${esc(String(err))}`, true);
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Start
// ──────────────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", initFurnitureList);
