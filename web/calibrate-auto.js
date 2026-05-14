"use strict";
/**
 * HausRadar – Auto-Kalibrierung
 *
 * Lädt den Kalibrierungs-Status aller Sensoren und zeigt Vorschläge an.
 * Wird automatisch beim Laden der calibrate.html ausgeführt.
 */

const AUTO_CAL_POLL_MS = 10_000;   // alle 10s neu laden
let _autoCalTimer = null;

// ──────────────────────────────────────────────────────────────────────────────
// Initialisierung
// ──────────────────────────────────────────────────────────────────────────────

async function initAutoCalibration() {
  await renderAutoCalibration();
  _autoCalTimer = setInterval(renderAutoCalibration, AUTO_CAL_POLL_MS);
}

async function renderAutoCalibration() {
  const container = document.getElementById("auto-cal-list");
  if (!container) return;

  let data;
  try {
    data = await apiFetch("/api/auto-calibration/status");
  } catch (err) {
    container.innerHTML = `<p class="muted">Fehler beim Laden: ${esc(String(err))}</p>`;
    return;
  }

  if (!data.sensors || data.sensors.length === 0) {
    container.innerHTML = `<p class="muted">Keine Sensoren gefunden.</p>`;
    return;
  }

  container.innerHTML = data.sensors.map(s => _renderSensorCard(s)).join("");

  // Event-Listener für Buttons
  for (const s of data.sensors) {
    const applyBtn     = document.getElementById(`auto-cal-apply-${s.sensor_id}`);
    const resetBtn     = document.getElementById(`auto-cal-reset-${s.sensor_id}`);
    const rsApplyBtn   = document.getElementById(`room-size-apply-${s.sensor_id}`);
    const rsSwapBtn    = document.getElementById(`room-size-swap-${s.sensor_id}`);

    if (applyBtn) applyBtn.addEventListener("click", () => applyAutoCalibration(s.sensor_id));
    if (resetBtn) resetBtn.addEventListener("click", () => resetAutoCalibration(s.sensor_id));
    if (rsApplyBtn && s.room_size_suggestion) {
      rsApplyBtn.addEventListener("click", () => applyRoomSize(s.sensor_id, s.room_size_suggestion));
    }
    if (rsSwapBtn) {
      rsSwapBtn.addEventListener("click", () => {
        _roomSizeSwapped[s.sensor_id] = !_roomSizeSwapped[s.sensor_id];
        renderAutoCalibration();
      });
    }
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Sensor-Karte rendern
// ──────────────────────────────────────────────────────────────────────────────

function _renderSensorCard(s) {
  const progressPct = Math.min(100, Math.round(s.sample_count / s.min_samples * 100));
  const progressBar = `
    <div style="background:var(--card-border);border-radius:4px;height:6px;margin:8px 0 4px">
      <div style="background:${progressPct >= 100 ? 'var(--accent)' : '#6b7280'};
                  width:${progressPct}%;height:100%;border-radius:4px;transition:width .4s"></div>
    </div>
    <p class="muted" style="font-size:11px;margin:0">
      ${s.sample_count} / ${s.min_samples} Messungen
      ${progressPct >= 100 ? '✓' : `(${progressPct}%)`}
    </p>`;

  let suggestionHtml = "";
  if (s.suggestion) {
    const sg       = s.suggestion;
    const qualCol  = sg.quality === "high" ? "#22c55e" :
                     sg.quality === "medium" ? "#f59e0b" : "#6b7280";
    const qualTxt  = sg.quality === "high" ? "Zuverlässig" :
                     sg.quality === "medium" ? "Ausreichend" : "Unsicher";
    const confPct  = Math.round(sg.confidence * 100);

    const candidateRows = sg.candidates.map(c => `
      <tr style="${c.rotation_deg === sg.rotation_deg ? 'color:var(--accent);font-weight:600' : 'color:var(--text-muted)'}">
        <td>${c.rotation_deg}°</td>
        <td>${Math.round(c.inside_ratio * 100)}% im Raum</td>
        <td>${c.sensor_x_mm} mm</td>
        <td>${c.rotation_deg === sg.rotation_deg ? '← Empfehlung' : ''}</td>
      </tr>`).join("");

    suggestionHtml = `
      <div style="margin-top:14px;border-top:1px solid var(--card-border);padding-top:14px">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px">
          <span style="font-size:13px">
            Vorschlag:&nbsp;
            <strong style="color:var(--accent)">${sg.rotation_deg}°</strong>
            &nbsp;/&nbsp;x&nbsp;=&nbsp;<strong style="color:var(--accent)">${sg.sensor_x_mm}&nbsp;mm</strong>
          </span>
          <span style="font-size:11px;padding:2px 8px;border-radius:10px;
                       background:${qualCol}22;color:${qualCol}">
            ${qualTxt} &nbsp;${confPct}%
          </span>
        </div>
        <table style="font-size:11px;border-collapse:collapse;width:100%;margin-bottom:12px">
          <thead><tr style="color:var(--text-muted)">
            <th style="text-align:left;padding-right:16px">Rotation</th>
            <th style="text-align:left;padding-right:16px">Punkte drin</th>
            <th style="text-align:left;padding-right:16px">sensor_x</th>
            <th></th>
          </tr></thead>
          <tbody>${candidateRows}</tbody>
        </table>
        <div style="display:flex;gap:8px">
          <button id="auto-cal-apply-${esc(s.sensor_id)}"
                  class="btn-mark"
                  ${sg.quality === 'low' ? 'title="Konfidenz gering – trotzdem anwendbar"' : ''}>
            ✓ Anwenden
          </button>
          <button id="auto-cal-reset-${esc(s.sensor_id)}"
                  class="btn-secondary" style="font-size:12px">
            Daten zurücksetzen
          </button>
        </div>
      </div>`;
  } else {
    suggestionHtml = `
      <p class="muted" style="margin-top:10px;font-size:12px">
        Noch kein Vorschlag – bitte im Raum bewegen bis der Puffer voll ist.
      </p>`;
  }

  // ── Raumgröße-Schätzung (M23) ──
  const roomSizeHtml = _renderRoomSizeCard(s);

  return `
    <div style="border:1px solid var(--card-border);border-radius:8px;
                padding:16px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <strong>${esc(s.sensor_name)}</strong>
        <span class="muted" style="font-size:11px">${esc(s.room_id || "–")}</span>
      </div>
      ${progressBar}
      ${suggestionHtml}
      ${roomSizeHtml}
    </div>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Raumgröße-Karte
// ──────────────────────────────────────────────────────────────────────────────

// Merkt sich die aktuelle Tausch-Richtung je Sensor
const _roomSizeSwapped = {};

function _renderRoomSizeCard(s) {
  const rs = s.room_size_suggestion;
  if (!rs) {
    return `
      <div style="margin-top:12px;border-top:1px solid var(--card-border);padding-top:12px">
        <p class="muted" style="font-size:11px;margin:0">
          📐 Raumgröße wird geschätzt – noch nicht genug Daten.
        </p>
      </div>`;
  }

  const swapped  = !!_roomSizeSwapped[s.sensor_id];
  const dispW    = swapped ? rs.height_mm : rs.width_mm;
  const dispH    = swapped ? rs.width_mm  : rs.height_mm;
  const qualCol  = rs.quality === "high"   ? "#22c55e" :
                   rs.quality === "medium" ? "#f59e0b" : "#6b7280";
  const qualTxt  = rs.quality === "high"   ? "Zuverlässig" :
                   rs.quality === "medium" ? "Ausreichend" : "Unsicher";
  const confPct  = Math.round(rs.confidence * 100);

  return `
    <div style="margin-top:12px;border-top:1px solid var(--card-border);padding-top:12px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
        <span style="font-size:12px">
          📐 Raumgröße:&nbsp;
          <strong style="color:var(--accent)">${dispW}&nbsp;×&nbsp;${dispH}&nbsp;mm</strong>
          &nbsp;<span class="muted">(B&nbsp;×&nbsp;T)</span>
        </span>
        <span style="font-size:10px;padding:1px 7px;border-radius:8px;
                     background:${qualCol}22;color:${qualCol}">
          ${qualTxt}&nbsp;${confPct}%
        </span>
      </div>
      <p class="muted" style="font-size:10px;margin:0 0 8px">
        Basiert auf ${rs.sample_count} Messungen. Typische Genauigkeit ±300&nbsp;mm.
        Wenn Breite und Tiefe vertauscht wirken, bitte tauschen und erneut anwenden.
      </p>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button id="room-size-apply-${esc(s.sensor_id)}"
                class="btn-mark" style="font-size:12px">
          ✓ Raumgröße übernehmen
        </button>
        <button id="room-size-swap-${esc(s.sensor_id)}"
                class="btn-secondary" style="font-size:12px"
                title="Breite und Tiefe tauschen">
          ⇄ Tauschen
        </button>
      </div>
    </div>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Aktionen
// ──────────────────────────────────────────────────────────────────────────────

async function applyAutoCalibration(sensorId) {
  const btn = document.getElementById(`auto-cal-apply-${sensorId}`);
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  try {
    const result = await apiFetch(
      `/api/sensors/${encodeURIComponent(sensorId)}/auto-calibration/apply`,
      { method: "POST" }
    );
    showCalToast(`✓ ${esc(sensorId)}: rotation=${result.rotation_deg}°, x=${result.sensor_x_mm} mm`);
    await renderAutoCalibration();
    // Kalibrierungs-Übersicht neu laden falls sichtbar
    if (typeof loadOverview === "function") loadOverview();
  } catch (err) {
    showCalToast(`⚠ Fehler: ${esc(String(err))}`, true);
    await renderAutoCalibration();
  }
}

async function applyRoomSize(sensorId, rs) {
  const btn = document.getElementById(`room-size-apply-${sensorId}`);
  if (btn) { btn.disabled = true; btn.textContent = "…"; }

  const swapped  = !!_roomSizeSwapped[sensorId];
  const width_mm  = swapped ? rs.height_mm : rs.width_mm;
  const height_mm = swapped ? rs.width_mm  : rs.height_mm;

  try {
    const result = await apiFetch(
      `/api/sensors/${encodeURIComponent(sensorId)}/auto-calibration/room-size/apply`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ width_mm, height_mm }),
      }
    );
    showCalToast(`✓ Raumgröße: ${result.width_mm} × ${result.height_mm} mm`);
    await renderAutoCalibration();
    if (typeof loadOverview === "function") loadOverview();
  } catch (err) {
    showCalToast(`⚠ Fehler: ${esc(String(err))}`, true);
    await renderAutoCalibration();
  }
}

async function resetAutoCalibration(sensorId) {
  try {
    await apiFetch(
      `/api/sensors/${encodeURIComponent(sensorId)}/auto-calibration/reset`,
      { method: "POST" }
    );
    showCalToast(`Datenpuffer für ${esc(sensorId)} gelöscht.`);
    await renderAutoCalibration();
  } catch (err) {
    showCalToast(`⚠ Fehler: ${esc(String(err))}`, true);
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Toast (nutzt die Funktion aus calibrate-core.js falls vorhanden)
// ──────────────────────────────────────────────────────────────────────────────

function showCalToast(msg, isError = false) {
  if (typeof showToast === "function") { showToast(msg, isError); return; }
  // Fallback
  let t = document.getElementById("cal-auto-toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "cal-auto-toast";
    t.className = "fp-toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.className = "fp-toast fp-toast--visible" + (isError ? " fp-toast--error" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("fp-toast--visible"), 3000);
}

// ──────────────────────────────────────────────────────────────────────────────
// Start
// ──────────────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", initAutoCalibration);
