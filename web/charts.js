"use strict";

// ============================================================
// Zustand
// ============================================================
let _days   = 7;
let _roomId = "";

const DAYS_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

// ============================================================
// Init
// ============================================================

async function initCharts() {
  // Raum-Filter befüllen
  try {
    const rooms = await API.rooms();
    const sel = document.getElementById("room-filter");
    rooms.forEach(r => {
      const opt = document.createElement("option");
      opt.value       = r.id;
      opt.textContent = r.name;
      sel.appendChild(opt);
    });
  } catch (_) {}

  // Tage-Buttons
  document.querySelectorAll("[data-days]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-days]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _days = parseInt(btn.dataset.days, 10);
      _refresh();
    });
  });

  // Raum-Select
  document.getElementById("room-filter").addEventListener("change", e => {
    _roomId = e.target.value;
    _refresh();
  });

  // Backend-Status
  try {
    const h = await API.health();
    const badge = document.getElementById("status-badge");
    if (badge && h.status === "ok") {
      badge.className   = "badge badge--ok";
      badge.textContent = "Verbunden";
    }
  } catch (_) {}

  _refresh();
}

function _qs(extra = {}) {
  const p = new URLSearchParams({ days: _days });
  if (_roomId) p.set("room_id", _roomId);
  Object.entries(extra).forEach(([k, v]) => p.set(k, v));
  return p.toString();
}

async function _refresh() {
  // Alle Charts parallel laden
  await Promise.allSettled([
    _loadHourly(),
    _loadRooms(),
    _loadZones(),
    _loadHeatmap(),
    _loadSessions(),
  ]);
}

// ============================================================
// Stunden-Balkendiagramm
// ============================================================

async function _loadHourly() {
  const el = document.getElementById("chart-hourly");
  if (!el) return;
  try {
    const data = await API.profile.hourly(_qs());
    _renderHourly(el, data);
  } catch (_) {
    el.innerHTML = '<p class="muted">Keine Daten.</p>';
  }
}

function _renderHourly(el, data) {
  const max = Math.max(...data.map(d => d.count), 1);
  el.innerHTML = data.map(d => {
    const pct  = (d.count / max * 100).toFixed(1);
    const tip  = `${String(d.hour).padStart(2, "0")}:00  –  ${d.count}×`;
    return `<div class="bar-col" title="${tip}">
      <div class="bar-fill" style="height:${pct}%"></div>
      <span class="bar-label">${d.hour % 3 === 0 ? d.hour : ""}</span>
    </div>`;
  }).join("");
}

// ============================================================
// Raumvergleich (horizontal bars)
// ============================================================

async function _loadRooms() {
  const el = document.getElementById("chart-rooms");
  if (!el) return;
  try {
    const data = await API.profile.rooms(_qs());
    _renderHBars(el, data, r => r.room_id, r => r.session_count,
      r => `${r.session_count} Sitzungen · Ø ${_dur(r.avg_duration_s)}`);
  } catch (_) {
    el.innerHTML = '<p class="muted">Keine Daten.</p>';
  }
}

// ============================================================
// Zonenaktivität (horizontal bars)
// ============================================================

async function _loadZones() {
  const el = document.getElementById("chart-zones");
  if (!el) return;
  try {
    const data = await API.profile.zones(_qs());
    _renderHBars(el, data, z => z.zone_id, z => z.pct,
      z => `${z.count}×  (${z.pct}%)`);
  } catch (_) {
    el.innerHTML = '<p class="muted">Keine Daten.</p>';
  }
}

function _renderHBars(el, data, labelFn, valueFn, metaFn) {
  if (!data.length) {
    el.innerHTML = '<p class="muted">Noch keine Daten für diesen Zeitraum.</p>';
    return;
  }
  const max = Math.max(...data.map(valueFn), 1);
  el.innerHTML = data.map(d => {
    const pct = (valueFn(d) / max * 100).toFixed(1);
    return `<div class="hbar-row">
      <span class="hbar-label">${esc(labelFn(d))}</span>
      <div class="hbar-track">
        <div class="hbar-fill" style="width:${pct}%"></div>
      </div>
      <span class="hbar-meta">${esc(metaFn(d))}</span>
    </div>`;
  }).join("");
}

// ============================================================
// 7×24 Heatmap
// ============================================================

async function _loadHeatmap() {
  const el = document.getElementById("chart-heatmap");
  if (!el) return;
  try {
    const data = await API.profile.heatmap(_qs());
    _renderHeatmap(el, data);
  } catch (_) {
    el.innerHTML = '<p class="muted">Keine Daten.</p>';
  }
}

function _renderHeatmap(el, data) {
  // data: [{weekday:0..6, hour:0..23, count}]
  const grid = {};
  data.forEach(d => { grid[`${d.weekday}-${d.hour}`] = d.count; });
  const max = Math.max(...data.map(d => d.count), 1);

  let html = '<div class="hm-grid">';

  // Kopfzeile: leer + Stunden
  html += '<div class="hm-corner"></div>';
  for (let h = 0; h < 24; h++) {
    html += `<div class="hm-hour-label">${h % 3 === 0 ? h : ""}</div>`;
  }

  // Zeilen: Wochentage
  for (let wd = 0; wd < 7; wd++) {
    html += `<div class="hm-day-label">${DAYS_LABELS[wd]}</div>`;
    for (let h = 0; h < 24; h++) {
      const count = grid[`${wd}-${h}`] || 0;
      const intensity = count > 0 ? Math.max(0.12, count / max) : 0;
      const tip = `${DAYS_LABELS[wd]} ${String(h).padStart(2,"0")}:00 – ${count}×`;
      html += `<div class="hm-cell" style="--i:${intensity.toFixed(3)}" title="${tip}"></div>`;
    }
  }

  html += "</div>";
  html += `<div class="hm-legend">
    <span class="hm-legend-label">wenig</span>
    <div class="hm-legend-bar"></div>
    <span class="hm-legend-label">viel</span>
  </div>`;
  el.innerHTML = html;
}

// ============================================================
// Letzte Bewegungssitzungen
// ============================================================

async function _loadSessions() {
  const el = document.getElementById("chart-sessions");
  if (!el) return;
  try {
    const data = await API.history.sessions(_qs({ limit: 20 }));
    _renderSessions(el, data);
  } catch (_) {
    el.innerHTML = '<p class="muted">Keine Daten.</p>';
  }
}

function _renderSessions(el, data) {
  if (!data.length) {
    el.innerHTML = '<p class="muted">Noch keine Sitzungen aufgezeichnet.</p>';
    return;
  }
  el.innerHTML = `<table class="sessions-table">
    <thead>
      <tr>
        <th>Raum</th>
        <th>Beginn</th>
        <th>Dauer</th>
        <th>Max. Ziele</th>
      </tr>
    </thead>
    <tbody>
      ${data.map(s => {
        const start = new Date(s.started_at_ms).toLocaleString("de-DE");
        const dur   = s.ended_at_ms
          ? _dur((s.ended_at_ms - s.started_at_ms) / 1000)
          : '<span class="badge badge--ok" style="font-size:.7rem">läuft</span>';
        return `<tr>
          <td>${esc(s.room_id)}</td>
          <td class="muted">${esc(start)}</td>
          <td>${dur}</td>
          <td>${esc(s.max_targets)}</td>
        </tr>`;
      }).join("")}
    </tbody>
  </table>`;
}

// ============================================================
// Hilfsfunktion: Dauer formatieren
// ============================================================

function _dur(seconds) {
  if (!seconds || seconds < 1) return "< 1 s";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s > 0 ? `${m} min ${s} s` : `${m} min`;
  const h = Math.floor(m / 60);
  return `${h} h ${m % 60} min`;
}

initCharts();
