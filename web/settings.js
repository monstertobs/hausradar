"use strict";

let _healthTimer = null;

// ---------------------------------------------------------------------------
// Einstiegspunkt
// ---------------------------------------------------------------------------

async function initSettings() {
  _loadHealth();
  _loadConfig();
  _healthTimer = setInterval(_loadHealth, 5000);
}

// ---------------------------------------------------------------------------
// System-Status (Health-Endpoint)
// ---------------------------------------------------------------------------

async function _loadHealth() {
  const el = document.getElementById("health-grid");
  try {
    const h = await API.health();
    _renderHealth(el, h);
    // Topbar-Badge mitführen
    const badge = document.getElementById("status-badge");
    if (badge) {
      badge.className = "badge badge--ok";
      badge.textContent = "Backend OK";
    }
  } catch {
    el.innerHTML = '<p class="muted error-text">Backend nicht erreichbar.</p>';
    const badge = document.getElementById("status-badge");
    if (badge) { badge.className = "badge badge--error"; badge.textContent = "Fehler"; }
  }
}

function _renderHealth(el, h) {
  const version = h.version ? `v${esc(h.version)}` : "–";
  const rows = [
    ["Version",           `<strong style="color:var(--text);font-size:1rem">${version}</strong>`],
    ["Backend",           _dot(true) + " OK"],
    ["Uptime",            _fmt_uptime(h.uptime_s)],
    ["Datenbank",         h.db_ok          ? _dot(true)  + " OK"        : _dot(false) + " Fehler"],
    ["MQTT",              h.mqtt_connected ? _dot(true) + " Verbunden"  : _dot(false) + " Kein Broker"],
    ["WebSocket-Clients", String(h.ws_clients)],
  ];

  el.innerHTML = rows.map(([label, value]) =>
    `<div class="health-row">
       <span class="health-label">${label}</span>
       <span class="health-value">${value}</span>
     </div>`
  ).join("");
}

function _dot(ok) {
  return `<span class="dot dot--${ok ? "ok" : "off"}"></span>`;
}

function _fmt_uptime(s) {
  if (s == null) return "–";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min ${sec} s`;
  return `${sec} s`;
}

// ---------------------------------------------------------------------------
// Räume und Sensoren
// ---------------------------------------------------------------------------

async function _loadConfig() {
  try {
    const [rooms, sensors, liveData] = await Promise.all([
      API.rooms(), API.sensors(), API.live().catch(() => null),
    ]);
    _renderRooms(rooms);
    _renderSensors(sensors, rooms, liveData);
  } catch {
    document.getElementById("settings-rooms").innerHTML =
      '<p class="muted error-text">Fehler beim Laden der Konfiguration.</p>';
    document.getElementById("settings-sensors").innerHTML = "";
  }
}

function _renderRooms(rooms) {
  const el = document.getElementById("settings-rooms");
  if (!rooms.length) { el.innerHTML = '<p class="muted">Keine Räume konfiguriert.</p>'; return; }

  el.innerHTML = rooms.map(r => {
    const zones = (r.zones || []).map(z =>
      `<span class="chip">${esc(z.name)}</span>`
    ).join(" ");
    return `
      <div class="room-tile">
        <strong>${esc(r.name)}</strong>
        <div class="room-tile__meta">
          ${(r.width_mm / 1000).toFixed(1)} m × ${(r.height_mm / 1000).toFixed(1)} m
          &nbsp;·&nbsp; ${(r.zones || []).length} Zone(n)
        </div>
        ${zones ? `<div class="chip-row">${zones}</div>` : ""}
      </div>`;
  }).join("");
}

function _renderSensors(sensors, rooms, liveData) {
  const el      = document.getElementById("settings-sensors");
  const roomMap = Object.fromEntries((rooms || []).map(r => [r.id, r.name]));
  if (!sensors.length) { el.innerHTML = '<p class="muted">Keine Sensoren konfiguriert.</p>'; return; }

  el.innerHTML = sensors.map(s => {
    const roomName   = roomMap[s.room_id] || s.room_id;
    const live       = liveData?.sensors?.[s.id];
    const isOnline   = live?.online === true;
    const isDisabled = s.enabled === false;
    const liveClass  = isDisabled  ? "dot dot--off"
                     : isOnline    ? "dot dot--ok"
                     :              "dot dot--warn";
    const liveLabel  = isDisabled  ? "deaktiviert"
                     : isOnline    ? "online – sendet"
                     :              "offline";
    const lastSeen   = live?.last_seen_seconds_ago != null
      ? `<br>Zuletzt: vor ${Math.round(live.last_seen_seconds_ago)} s`
      : "";
    const targets    = isOnline && live.target_count > 0
      ? `<br><span style="color:var(--green)">${live.target_count} Person(en) erkannt</span>`
      : "";
    const mqttTopic  = `hausradar/sensor/${esc(s.id)}/state`;

    return `
      <div class="sensor-tile" id="sensor-tile-${esc(s.id)}">
        <div class="sensor-tile__header">
          <span><span class="${liveClass}"></span> <strong>${esc(s.name)}</strong></span>
          <button class="btn-identify" onclick="identifySensor('${esc(s.id)}','${esc(s.name)}')"
                  title="Sensor identifizieren">📡 Identifizieren</button>
        </div>
        <div class="sensor-tile__meta">
          Raum: <strong>${esc(roomName)}</strong><br>
          Status: ${liveLabel}${lastSeen}${targets}<br>
          Position: ${esc(s.x_mm)} / ${esc(s.y_mm)} mm · Höhe: ${esc(s.mount_height_mm)} mm<br>
          Drehung: ${esc(s.rotation_deg)}°<br>
          <span class="mqtt-topic" title="Diese ID in der ESP32-Firmware eintragen (config.h → SENSOR_ID)">
            MQTT: <code>${mqttTopic}</code>
          </span>
        </div>
      </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Sensor-Identifikation via WebSocket
// ---------------------------------------------------------------------------

function identifySensor(sensorId, sensorName) {
  // Overlay aufbauen
  const overlay = document.createElement("div");
  overlay.className = "identify-overlay";
  overlay.innerHTML = `
    <div class="identify-box">
      <div class="identify-box__title">📡 Sensor identifizieren</div>
      <p>Bewege dich jetzt vor <strong>${esc(sensorName)}</strong>.<br>
         Der Sensor wird bestätigt sobald Bewegung erkannt wird.</p>
      <div class="identify-status" id="id-status">
        <span class="dot dot--warn"></span> Warte auf Signal …
      </div>
      <div id="id-detail" class="identify-detail"></div>
      <button class="btn-secondary" id="id-cancel">Abbrechen</button>
    </div>`;
  document.body.appendChild(overlay);

  let ws      = null;
  let timer   = null;
  let done    = false;

  function close() {
    if (ws) { try { ws.close(); } catch(_) {} }
    clearTimeout(timer);
    overlay.remove();
  }

  document.getElementById("id-cancel").addEventListener("click", close);
  overlay.addEventListener("click", e => { if (e.target === overlay) close(); });

  // WebSocket öffnen
  try {
    ws = new WebSocket(`ws://${location.host}/ws/live`);
  } catch(e) {
    document.getElementById("id-status").innerHTML =
      `<span style="color:var(--red)">❌ WebSocket nicht verfügbar</span>`;
    return;
  }

  // Timeout nach 20 Sekunden
  timer = setTimeout(() => {
    if (done) return;
    document.getElementById("id-status").innerHTML =
      `<span style="color:var(--yellow)">⏱️ Kein Signal in 20 s – ist der Sensor online?</span>`;
    ws.close();
  }, 20_000);

  ws.onmessage = e => {
    if (done) return;
    let data;
    try { data = JSON.parse(e.data); } catch(_) { return; }
    const s = data?.sensors?.[sensorId];
    if (!s?.online) return;

    // Online aber noch keine Bewegung → zeige "online"
    const statusEl = document.getElementById("id-status");
    if (statusEl) {
      statusEl.innerHTML = `<span class="dot dot--ok"></span> Sensor online …`;
    }

    if (s.target_count > 0) {
      done = true;
      clearTimeout(timer);
      ws.close();
      if (statusEl) {
        statusEl.innerHTML =
          `<span style="color:var(--green);font-size:1.3rem">✅ Bewegung erkannt!</span>`;
      }
      const det = document.getElementById("id-detail");
      if (det) {
        det.innerHTML = `
          <span class="dot dot--ok"></span> Raum: <strong>${esc(s.room_id)}</strong><br>
          ${s.target_count} Person(en) in Sensorreichweite<br>
          Zuletzt gesehen: vor ${Math.round(s.last_seen_seconds_ago ?? 0)} s`;
      }
      document.getElementById("id-cancel").textContent = "Schließen";

      // Zugehörige Kachel kurz aufleuchten lassen
      const tile = document.getElementById(`sensor-tile-${sensorId}`);
      if (tile) {
        tile.classList.add("sensor-tile--flash");
        setTimeout(() => tile.classList.remove("sensor-tile--flash"), 2000);
      }
    }
  };

  ws.onerror = () => {
    const statusEl = document.getElementById("id-status");
    if (statusEl) statusEl.innerHTML =
      `<span style="color:var(--red)">❌ Verbindungsfehler</span>`;
  };
}

// ---------------------------------------------------------------------------
// Software-Update
// ---------------------------------------------------------------------------

let _updateEs  = null;   // EventSource
let _updatePct = 0;

function _initUpdate() {
  document.getElementById("btn-check-update")
    ?.addEventListener("click", _checkUpdate);
}

async function _checkUpdate() {
  const btn     = document.getElementById("btn-check-update");
  const infoEl  = document.getElementById("update-version-info");
  const actEl   = document.getElementById("update-actions");

  btn.disabled    = true;
  btn.textContent = "🔍 Prüfe …";
  infoEl.innerHTML = `<p class="muted">Verbinde mit GitHub …</p>`;

  try {
    const s = await apiFetch("/api/update/status");
    _renderVersionInfo(s);
  } catch (e) {
    infoEl.innerHTML = `<p style="color:var(--red)">Fehler: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled    = false;
    btn.textContent = "🔍 Auf Updates prüfen";
  }
}

function _renderVersionInfo(s) {
  const infoEl = document.getElementById("update-version-info");
  const actEl  = document.getElementById("update-actions");

  const curVersion = s.current.version ? `<strong style="color:var(--text)">v${esc(s.current.version)}</strong> &nbsp;` : "";
  const curHtml = `
    <div style="font-size:.82rem;color:var(--muted)">
      <span style="color:var(--text);font-weight:600">Installiert:</span>
      ${curVersion}<code style="background:var(--border);border-radius:3px;padding:1px 5px">${esc(s.current.hash)}</code>
      ${esc(s.current.date)}
      &nbsp;·&nbsp; ${esc(s.current.message)}
    </div>`;

  let latestHtml = "";
  if (s.fetch_ok) {
    const remVersion = s.latest.version ? `<strong style="color:${s.update_available ? '#22c55e' : 'var(--text)'}">v${esc(s.latest.version)}</strong> &nbsp;` : "";
    latestHtml = `
      <div style="font-size:.82rem;color:var(--muted);margin-top:4px">
        <span style="color:var(--text);font-weight:600">GitHub:</span>
        ${remVersion}<code style="background:var(--border);border-radius:3px;padding:1px 5px">${esc(s.latest.hash)}</code>
        ${esc(s.latest.date)}
        &nbsp;·&nbsp; ${esc(s.latest.message)}
      </div>`;
  } else {
    latestHtml = `<p style="color:var(--yellow);font-size:.82rem;margin-top:4px">
      ⚠ GitHub nicht erreichbar – Version konnte nicht abgerufen werden.</p>`;
  }

  let commitsHtml = "";
  if (s.new_commits && s.new_commits.length > 0) {
    commitsHtml = `
      <div style="margin-top:10px;padding:10px;background:var(--border);
                  border-radius:6px;font-size:.78rem;font-family:monospace">
        ${s.new_commits.map(c => `<div>↓ ${esc(c)}</div>`).join("")}
      </div>`;
  }

  infoEl.innerHTML = curHtml + latestHtml + commitsHtml;

  // Aktions-Buttons aktualisieren
  if (s.update_available) {
    actEl.innerHTML = `
      <button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>
      <button id="btn-install-update" class="btn-mark" style="background:#15803d">
        ⬇ Update installieren (${s.behind_by} Commit${s.behind_by > 1 ? "s" : ""})
      </button>`;
    document.getElementById("btn-check-update")
      ?.addEventListener("click", _checkUpdate);
    document.getElementById("btn-install-update")
      ?.addEventListener("click", _startUpdate);
  } else if (s.fetch_ok) {
    actEl.innerHTML = `
      <button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>
      <span style="color:var(--green);font-size:.875rem">✓ Aktuell – kein Update verfügbar</span>`;
    document.getElementById("btn-check-update")
      ?.addEventListener("click", _checkUpdate);
  } else {
    actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
    document.getElementById("btn-check-update")
      ?.addEventListener("click", _checkUpdate);
  }
}

async function _startUpdate() {
  // UI in Update-Modus schalten
  const actEl     = document.getElementById("update-actions");
  const progEl    = document.getElementById("update-progress");
  const resultEl  = document.getElementById("update-result");
  const logEl     = document.getElementById("update-log");
  const barEl     = document.getElementById("update-bar");

  actEl.innerHTML = `<span class="muted" style="font-size:.875rem">Update läuft …</span>`;
  progEl.style.display  = "block";
  resultEl.style.display = "none";
  logEl.innerHTML = "";
  barEl.style.width = "0%";
  _updatePct = 0;

  // Update starten
  try {
    await apiFetch("/api/update/start", { method: "POST" });
  } catch (e) {
    _appendLog("error", "Start fehlgeschlagen: " + e.message);
    return;
  }

  // SSE-Stream öffnen
  if (_updateEs) _updateEs.close();
  _updateEs = new EventSource("/api/update/stream");

  _updateEs.onmessage = (ev) => {
    if (!ev.data || ev.data.startsWith(":")) return;
    try {
      const d = JSON.parse(ev.data);

      if (d.level === "phase") {
        _updateEs.close();
        _handlePhase(d.msg);
        return;
      }

      if (d.pct >= 0) {
        _updatePct = d.pct;
        barEl.style.width = d.pct + "%";
        // Farbe: blau während läuft, grün bei 100%
        barEl.style.background = d.pct >= 100 ? "#15803d" : "#3b82f6";
      }

      _appendLog(d.level, d.msg);
    } catch (_) {}
  };

  _updateEs.onerror = () => {
    _updateEs.close();
    // Verbindungsabbruch = entweder Fehler oder Neustart (erwünscht)
    if (_updatePct >= 88) {
      _handlePhase("restarting");
    } else {
      _appendLog("error", "Verbindung unterbrochen (pct=" + _updatePct + ")");
      _handlePhase("failed");
    }
  };
}

function _appendLog(level, msg) {
  const logEl = document.getElementById("update-log");
  if (!logEl) return;
  const colors = {
    ok:    "#22c55e",
    error: "#ef4444",
    warn:  "#f59e0b",
    info:  "#94a3b8",
    phase: "#818cf8",
  };
  const color = colors[level] || "#94a3b8";
  const icon  = { ok: "✓", error: "✗", warn: "⚠", info: "→", phase: "●" }[level] || "·";
  const div   = document.createElement("div");
  div.style.color = color;
  div.textContent = `${icon} ${msg}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

function _handlePhase(phase) {
  const resultEl = document.getElementById("update-result");
  const actEl    = document.getElementById("update-actions");
  const barEl    = document.getElementById("update-bar");

  if (phase === "restarting") {
    barEl.style.width      = "95%";
    barEl.style.background = "#8b5cf6";
    _appendLog("info", "Server wird neu gestartet – warte auf Verbindung …");
    resultEl.style.display = "none";
    _pollUntilAlive();
    return;
  }

  if (phase === "done") {
    barEl.style.width      = "100%";
    barEl.style.background = "#15803d";
    resultEl.style.display = "block";
    resultEl.innerHTML = `
      <div style="background:#052e16;border:1px solid #22c55e;border-radius:6px;padding:12px 16px">
        <div style="font-weight:700;color:#22c55e;margin-bottom:6px">✓ Update erfolgreich</div>
        <button onclick="location.reload()" class="btn-mark"
          style="background:#15803d;margin-top:8px;font-size:.85rem">
          Seite neu laden
        </button>
      </div>`;
    actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
    // Neustart-Hint ausblenden falls noch sichtbar
    apiFetch("/api/update/cancel", { method: "POST" }).catch(() => {});
    return;
  }

  if (phase === "failed") {
    barEl.style.background = "#dc2626";
    resultEl.style.display = "block";
    resultEl.innerHTML = `
      <div style="background:#1c0a0a;border:1px solid #dc2626;border-radius:6px;padding:12px 16px">
        <div style="font-weight:700;color:#ef4444;margin-bottom:6px">✗ Update fehlgeschlagen – Rollback durchgeführt</div>
        <div style="font-size:.82rem;color:var(--muted)">
          Die vorherige Version wurde wiederhergestellt.<br>
          Bitte prüfe den Log oben und starte den Dienst ggf. neu:<br>
          <code style="color:#fca5a5">sudo systemctl restart hausradar</code>
        </div>
      </div>`;
    actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
    apiFetch("/api/update/cancel", { method: "POST" }).catch(() => {});
  }
}

function _pollUntilAlive() {
  const logEl   = document.getElementById("update-log");
  const barEl   = document.getElementById("update-bar");
  const resultEl = document.getElementById("update-result");
  const actEl   = document.getElementById("update-actions");

  let tries = 0;
  const MAX  = 40;   // 40 × 2 s = 80 s Timeout

  const interval = setInterval(async () => {
    tries++;
    try {
      const h = await apiFetch("/api/health");
      clearInterval(interval);
      barEl.style.width      = "100%";
      barEl.style.background = "#15803d";
      if (logEl) {
        const div = document.createElement("div");
        div.style.color = "#22c55e";
        div.textContent = `✓ Server neu gestartet (${tries * 2}s) – Update abgeschlossen`;
        logEl.appendChild(div);
        logEl.scrollTop = logEl.scrollHeight;
      }
      resultEl.style.display = "block";
      resultEl.innerHTML = `
        <div style="background:#052e16;border:1px solid #22c55e;border-radius:6px;padding:12px 16px">
          <div style="font-weight:700;color:#22c55e;margin-bottom:4px">✓ Update erfolgreich installiert</div>
          <div style="font-size:.82rem;color:var(--muted)">Server läuft wieder · Uptime ${h.uptime_s}s</div>
          <button onclick="location.reload()" class="btn-mark"
            style="background:#15803d;margin-top:10px;font-size:.85rem">
            Seite neu laden
          </button>
        </div>`;
      actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
      document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
    } catch (_) {
      // Server noch nicht da
      if (logEl) {
        // Puls-Punkt updaten statt viele Zeilen
        let dot = logEl.querySelector(".restart-dot");
        if (!dot) {
          dot = document.createElement("div");
          dot.className    = "restart-dot";
          dot.style.color  = "#8b5cf6";
          logEl.appendChild(dot);
        }
        dot.textContent = `● Warte auf Server … (${tries * 2}s)`;
        logEl.scrollTop = logEl.scrollHeight;
      }
      if (tries >= MAX) {
        clearInterval(interval);
        if (logEl) {
          const div = document.createElement("div");
          div.style.color = "#f59e0b";
          div.textContent = "⚠ Timeout – Seite bitte manuell neu laden";
          logEl.appendChild(div);
        }
      }
    }
  }, 2000);
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  initSettings();
  _initUpdate();
});
