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
    const applyBtn = document.getElementById(`auto-cal-apply-${s.sensor_id}`);
    const resetBtn = document.getElementById(`auto-cal-reset-${s.sensor_id}`);
    if (applyBtn) applyBtn.addEventListener("click", () => applyAutoCalibration(s.sensor_id));
    if (resetBtn) resetBtn.addEventListener("click", () => resetAutoCalibration(s.sensor_id));
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

  return `
    <div style="border:1px solid var(--card-border);border-radius:8px;
                padding:16px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <strong>${esc(s.sensor_name)}</strong>
        <span class="muted" style="font-size:11px">${esc(s.room_id || "–")}</span>
      </div>
      ${progressBar}
      ${suggestionHtml}
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
