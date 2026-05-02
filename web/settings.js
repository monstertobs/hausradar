"use strict";

let _healthTimer = null;

// ---------------------------------------------------------------------------
// Einstiegspunkt
// ---------------------------------------------------------------------------
async function initSettings() {
  _loadHealth();
  _loadSensors();
  _healthTimer = setInterval(_loadHealth, 5000);
}

// ---------------------------------------------------------------------------
// System-Status
// ---------------------------------------------------------------------------
async function _loadHealth() {
  const el = document.getElementById("health-grid");
  try {
    const h = await API.health();
    _renderHealth(el, h);
    const badge = document.getElementById("status-badge");
    if (badge) { badge.className = "badge badge--ok"; badge.textContent = "Backend OK"; }
  } catch {
    if (el) el.innerHTML = '<p class="muted error-text">Backend nicht erreichbar.</p>';
    const badge = document.getElementById("status-badge");
    if (badge) { badge.className = "badge badge--error"; badge.textContent = "Fehler"; }
  }
}

function _renderHealth(el, h) {
  if (!el) return;
  const version = h.version ? `v${esc(h.version)}` : "–";
  const rows = [
    ["Version",  `<strong style="color:var(--text)">${version}</strong>`],
    ["Uptime",   _fmt_uptime(h.uptime_s)],
    ["MQTT",     h.mqtt_connected ? _dot(true) + " Verbunden" : _dot(false) + " Nicht verbunden"],
    ["Datenbank", h.db_ok ? _dot(true) + " OK" : _dot(false) + " Fehler"],
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
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min ${sec} s`;
  return `${sec} s`;
}

// ---------------------------------------------------------------------------
// Sensoren
// ---------------------------------------------------------------------------
async function _loadSensors() {
  const el = document.getElementById("settings-sensors");
  try {
    const timeout = ms => new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms));
    const [sensors, rooms, liveData] = await Promise.all([
      API.sensors(),
      API.rooms(),
      Promise.race([API.live(), timeout(3000)]).catch(() => null),
    ]);
    _renderSensors(sensors, rooms, liveData);
    _initProvisioning(sensors, rooms);
  } catch (err) {
    if (el) el.innerHTML = `<p class="muted error-text">Fehler beim Laden: ${esc(err.message)}</p>`;
  }
}

function _renderSensors(sensors, rooms, liveData) {
  const el      = document.getElementById("settings-sensors");
  const summary = document.getElementById("sensors-summary");
  if (!el) return;

  const roomMap = Object.fromEntries((rooms || []).map(r => [r.id, r.name]));

  if (!sensors.length) {
    el.innerHTML = '<p class="muted">Keine Sensoren konfiguriert.</p>';
    return;
  }

  const online  = sensors.filter(s => liveData?.sensors?.[s.id]?.online).length;
  if (summary) summary.textContent = `${online} / ${sensors.length} online`;

  el.innerHTML = sensors.map(s => {
    const live      = liveData?.sensors?.[s.id];
    const isOnline  = live?.online === true;
    const disabled  = s.enabled === false;
    const dotClass  = disabled ? "dot--off" : isOnline ? "dot--ok" : "dot--warn";
    const statusTxt = disabled ? "deaktiviert" : isOnline ? "online" : "offline";
    const personTxt = isOnline && live.target_count > 0
      ? `<span style="color:var(--green)"> · ${live.target_count} Person(en)</span>` : "";
    const mqttTopic = `hausradar/sensor/${esc(s.id)}/state`;

    return `
      <div class="sensor-tile" id="sensor-tile-${esc(s.id)}">
        <div class="sensor-tile__header">
          <span><span class="dot ${dotClass}"></span> <strong>${esc(s.name)}</strong></span>
          <button class="btn-identify"
                  onclick="identifySensor('${esc(s.id)}','${esc(s.name)}')"
                  title="Sensor identifizieren">📡 Identifizieren</button>
        </div>
        <div class="sensor-tile__meta">
          <strong>${esc(roomMap[s.room_id] || s.room_id)}</strong>
          &nbsp;·&nbsp; ${statusTxt}${personTxt}<br>
          <span class="mqtt-topic"><code>${mqttTopic}</code></span>
        </div>
      </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Sensor-Identifikation via WebSocket
// ---------------------------------------------------------------------------
function identifySensor(sensorId, sensorName) {
  const overlay = document.createElement("div");
  overlay.className = "identify-overlay";
  overlay.innerHTML = `
    <div class="identify-box">
      <div class="identify-box__title">📡 Sensor identifizieren</div>
      <p>Bewege dich vor <strong>${esc(sensorName)}</strong>.<br>
         Der Sensor wird bestätigt sobald Bewegung erkannt wird.</p>
      <div class="identify-status" id="id-status">
        <span class="dot dot--warn"></span> Warte auf Signal …
      </div>
      <div id="id-detail" class="identify-detail"></div>
      <button class="btn-secondary" id="id-cancel">Abbrechen</button>
    </div>`;
  document.body.appendChild(overlay);

  let ws = null, timer = null, done = false;

  function close() {
    if (ws) { try { ws.close(); } catch(_) {} }
    clearTimeout(timer);
    overlay.remove();
  }

  document.getElementById("id-cancel").addEventListener("click", close);
  overlay.addEventListener("click", e => { if (e.target === overlay) close(); });

  try {
    ws = new WebSocket(`ws://${location.host}/ws/live`);
  } catch {
    document.getElementById("id-status").innerHTML =
      `<span style="color:var(--red)">❌ WebSocket nicht verfügbar</span>`;
    return;
  }

  timer = setTimeout(() => {
    if (done) return;
    document.getElementById("id-status").innerHTML =
      `<span style="color:var(--yellow)">⏱️ Kein Signal in 20 s – ist der Sensor online?</span>`;
    ws.close();
  }, 20_000);

  ws.onmessage = e => {
    if (done) return;
    let data;
    try { data = JSON.parse(e.data); } catch { return; }
    const s = data?.sensors?.[sensorId];
    if (!s?.online) return;
    const statusEl = document.getElementById("id-status");
    if (statusEl) statusEl.innerHTML = `<span class="dot dot--ok"></span> Sensor online …`;
    if (s.target_count > 0) {
      done = true;
      clearTimeout(timer);
      ws.close();
      if (statusEl)
        statusEl.innerHTML = `<span style="color:var(--green);font-size:1.3rem">✅ Bewegung erkannt!</span>`;
      const det = document.getElementById("id-detail");
      if (det) det.innerHTML = `
        Raum: <strong>${esc(s.room_id)}</strong> ·
        ${s.target_count} Person(en) erkannt`;
      document.getElementById("id-cancel").textContent = "Schließen";
      document.getElementById(`sensor-tile-${sensorId}`)?.classList.add("sensor-tile--flash");
    }
  };
  ws.onerror = () => {
    const el = document.getElementById("id-status");
    if (el) el.innerHTML = `<span style="color:var(--red)">❌ Verbindungsfehler</span>`;
  };
}

// ---------------------------------------------------------------------------
// Sensor-Einrichtung via WiFi-Provisioning
// ---------------------------------------------------------------------------
function _initProvisioning(sensors, rooms) {
  const sel   = document.getElementById("prov-sensor-id");
  const guide = document.getElementById("prov-guide");
  if (!sel || !guide) return;

  const roomMap = Object.fromEntries((rooms || []).map(r => [r.id, r.name]));

  sel.innerHTML = '<option value="">— Sensor wählen —</option>' +
    (sensors || []).map(s =>
      `<option value="${esc(s.id)}">${esc(s.name)} – ${esc(roomMap[s.room_id] || s.room_id)}</option>`
    ).join("");

  sel.addEventListener("change", async () => {
    const sensor = (sensors || []).find(s => s.id === sel.value);
    if (!sensor) { guide.style.display = "none"; guide.innerHTML = ""; return; }

    // SSID vom Pi holen (Pi ist im gleichen WLAN wie der Browser)
    let ssid = "";
    try {
      const info = await apiFetch("/api/network/info");
      ssid = info.ssid || "";
    } catch {}

    guide.style.display = "block";
    guide.innerHTML = _buildProvGuide(
      sensor,
      roomMap[sensor.room_id] || sensor.room_id,
      ssid,
      window.location.hostname
    );
    _bindProvEvents(sensor);
  });
}

function _buildProvGuide(sensor, roomName, ssid, host) {
  return `
    <div class="prov-guide-header">
      Einrichten: <strong>${esc(sensor.name)}</strong>
      &nbsp;·&nbsp; Raum: <strong>${esc(roomName)}</strong>
    </div>

    <p class="muted" style="font-size:.84rem;margin-bottom:14px">
      Trage hier deine WLAN-Zugangsdaten ein. Alle anderen Felder sind bereits vorausgefüllt.
      Der QR-Code überträgt alles auf einmal auf den Sensor.
    </p>

    <div class="prov-prefill">
      <div class="prov-prefill__row">
        <label class="prov-prefill__label">WLAN-Name (SSID)</label>
        <input id="prov-ssid-input" class="prov-prefill__input" type="text"
               value="${esc(ssid)}" placeholder="Dein Heimnetzwerk" autocomplete="off">
      </div>
      <div class="prov-prefill__row">
        <label class="prov-prefill__label">WLAN-Passwort</label>
        <input id="prov-pass-input" class="prov-prefill__input" type="password"
               placeholder="WLAN-Passwort eingeben" autocomplete="off">
      </div>
      <div class="prov-prefill__row prov-prefill__row--ro">
        <span class="prov-prefill__label">Pi-IP (MQTT-Host)</span>
        <span class="prov-prefill__value"><code>${esc(host)}</code></span>
      </div>
      <div class="prov-prefill__row prov-prefill__row--ro">
        <span class="prov-prefill__label">Sensor-ID</span>
        <span class="prov-prefill__value"><code>${esc(sensor.id)}</code></span>
      </div>
      <div class="prov-prefill__row prov-prefill__row--ro">
        <span class="prov-prefill__label">Raum-ID</span>
        <span class="prov-prefill__value"><code>${esc(sensor.room_id)}</code></span>
      </div>
    </div>

    <div style="margin-top:18px">
      <button id="prov-qr-btn" class="btn btn--primary">📱 QR-Code generieren</button>
    </div>
    <div id="prov-qr-result" style="display:none;margin-top:20px"></div>

    <div class="prov-steps-compact">
      <div class="prov-step-compact">
        <span class="prov-step__num">1</span>
        <span>Firmware flashen:<br>
          <code class="code-block">cd firmware/esp32-ld2450-mqtt<br>pio run -e esp32dev -t upload</code>
        </span>
      </div>
      <div class="prov-step-compact">
        <span class="prov-step__num">2</span>
        <span>Mit WLAN-Hotspot <strong>HausRadar-Setup-XXXXXX</strong> verbinden</span>
      </div>
      <div class="prov-step-compact">
        <span class="prov-step__num">3</span>
        <span>QR-Code scannen → Formular öffnet sich vorausgefüllt → nur Passwort fehlt (wenn nicht im QR)</span>
      </div>
      <div class="prov-step-compact">
        <span class="prov-step__num">4</span>
        <span><strong>Speichern</strong> tippen → ESP32 startet, verbindet, sendet Daten ✅</span>
      </div>
    </div>

    <div class="prov-reset-hint">
      <strong>Zurücksetzen:</strong> BOOT-Taste (GPIO&nbsp;0) beim Einschalten 3&nbsp;Sekunden halten
      → Hotspot öffnet sich erneut.
    </div>`;
}

function _bindProvEvents(sensor) {
  const btn = document.getElementById("prov-qr-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const ssid = document.getElementById("prov-ssid-input")?.value.trim() || "";
    const pass = document.getElementById("prov-pass-input")?.value || "";
    const host = window.location.hostname;

    const params = new URLSearchParams({
      ssid, pass, host,
      id:   sensor.id,
      room: sensor.room_id,
    });
    const provUrl = `http://192.168.4.1/?${params.toString()}`;
    const qrUrl   = `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent(provUrl)}&size=220x220&margin=10`;

    const result = document.getElementById("prov-qr-result");
    if (!result) return;
    result.style.display = "block";
    result.innerHTML = `
      <div class="prov-qr-box">
        <img src="${qrUrl}" width="220" height="220" alt="QR-Code laden…">
        <div class="prov-qr-info">
          <p style="margin-bottom:8px">Scanne diesen QR-Code mit dem Handy,
            <strong>nachdem</strong> du dich mit dem HausRadar-Hotspot verbunden hast.
            Alle Felder inkl. Passwort sind vorausgefüllt – einfach <em>Speichern</em> tippen.</p>
          <p class="muted" style="font-size:.73rem;word-break:break-all">${esc(provUrl)}</p>
          <button class="btn-copy" data-copy="${esc(provUrl)}" style="margin-top:8px">⎘ URL kopieren</button>
        </div>
      </div>`;

    result.querySelectorAll(".btn-copy").forEach(b => {
      b.addEventListener("click", () => {
        navigator.clipboard?.writeText(b.dataset.copy);
        const orig = b.textContent;
        b.textContent = "✓ Kopiert";
        setTimeout(() => { b.textContent = orig; }, 1500);
      });
    });
  });
}

// ---------------------------------------------------------------------------
// Software-Update
// ---------------------------------------------------------------------------
let _updateEs  = null;
let _updatePct = 0;

function _initUpdate() {
  document.getElementById("btn-check-update")
    ?.addEventListener("click", _checkUpdate);
}

async function _checkUpdate() {
  const btn    = document.getElementById("btn-check-update");
  const infoEl = document.getElementById("update-version-info");
  const actEl  = document.getElementById("update-actions");

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

  const curVersion = s.current.version
    ? `<strong style="color:var(--text)">v${esc(s.current.version)}</strong> &nbsp;` : "";
  infoEl.innerHTML = `
    <div style="font-size:.82rem;color:var(--muted)">
      <span style="color:var(--text);font-weight:600">Installiert:</span>
      ${curVersion}<code style="background:var(--border);border-radius:3px;padding:1px 5px">${esc(s.current.hash)}</code>
      ${esc(s.current.date)} · ${esc(s.current.message)}
    </div>` +
    (s.fetch_ok ? `
    <div style="font-size:.82rem;color:var(--muted);margin-top:4px">
      <span style="color:var(--text);font-weight:600">GitHub:</span>
      ${s.latest.version ? `<strong style="color:${s.update_available ? '#22c55e' : 'var(--text)'}">v${esc(s.latest.version)}</strong> &nbsp;` : ""}
      <code style="background:var(--border);border-radius:3px;padding:1px 5px">${esc(s.latest.hash)}</code>
      ${esc(s.latest.date)} · ${esc(s.latest.message)}
    </div>` : `<p style="color:var(--yellow);font-size:.82rem;margin-top:4px">⚠ GitHub nicht erreichbar</p>`) +
    (s.new_commits?.length ? `
    <div style="margin-top:10px;padding:10px;background:var(--border);border-radius:6px;
                font-size:.78rem;font-family:monospace">
      ${s.new_commits.map(c => `<div>↓ ${esc(c)}</div>`).join("")}
    </div>` : "");

  if (s.update_available) {
    actEl.innerHTML = `
      <button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>
      <button id="btn-install-update" class="btn-mark" style="background:#15803d">
        ⬇ Update installieren (${s.behind_by} Commit${s.behind_by > 1 ? "s" : ""})
      </button>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
    document.getElementById("btn-install-update")?.addEventListener("click", _startUpdate);
  } else if (s.fetch_ok) {
    actEl.innerHTML = `
      <button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>
      <span style="color:var(--green);font-size:.875rem">✓ Aktuell</span>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
  } else {
    actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
  }
}

async function _startUpdate() {
  const actEl   = document.getElementById("update-actions");
  const progEl  = document.getElementById("update-progress");
  const resultEl = document.getElementById("update-result");
  const logEl   = document.getElementById("update-log");
  const barEl   = document.getElementById("update-bar");

  actEl.innerHTML = `<span class="muted" style="font-size:.875rem">Update läuft …</span>`;
  progEl.style.display   = "block";
  resultEl.style.display = "none";
  logEl.innerHTML = "";
  barEl.style.width = "0%";
  _updatePct = 0;

  try {
    await apiFetch("/api/update/start", { method: "POST" });
  } catch (e) {
    _appendLog("error", "Start fehlgeschlagen: " + e.message);
    return;
  }

  if (_updateEs) _updateEs.close();
  _updateEs = new EventSource("/api/update/stream");

  _updateEs.onmessage = (ev) => {
    if (!ev.data || ev.data.startsWith(":")) return;
    try {
      const d = JSON.parse(ev.data);
      if (d.level === "phase") { _updateEs.close(); _handlePhase(d.msg); return; }
      if (d.pct >= 0) {
        _updatePct = d.pct;
        barEl.style.width      = d.pct + "%";
        barEl.style.background = d.pct >= 100 ? "#15803d" : "#3b82f6";
      }
      _appendLog(d.level, d.msg);
    } catch (_) {}
  };

  _updateEs.onerror = () => {
    _updateEs.close();
    if (_updatePct >= 88) _handlePhase("restarting");
    else { _appendLog("error", "Verbindung unterbrochen"); _handlePhase("failed"); }
  };
}

function _appendLog(level, msg) {
  const logEl = document.getElementById("update-log");
  if (!logEl) return;
  const colors = { ok:"#22c55e", error:"#ef4444", warn:"#f59e0b", info:"#94a3b8", phase:"#818cf8" };
  const icons  = { ok:"✓", error:"✗", warn:"⚠", info:"→", phase:"●" };
  const div = document.createElement("div");
  div.style.color = colors[level] || "#94a3b8";
  div.textContent = `${icons[level] || "·"} ${msg}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

function _handlePhase(phase) {
  const resultEl = document.getElementById("update-result");
  const actEl    = document.getElementById("update-actions");
  const barEl    = document.getElementById("update-bar");

  if (phase === "restarting") {
    barEl.style.width = "95%"; barEl.style.background = "#8b5cf6";
    _appendLog("info", "Server wird neu gestartet …");
    resultEl.style.display = "none";
    _pollUntilAlive();
    return;
  }
  if (phase === "done") {
    barEl.style.width = "100%"; barEl.style.background = "#15803d";
    resultEl.style.display = "block";
    resultEl.innerHTML = `
      <div style="background:#052e16;border:1px solid #22c55e;border-radius:6px;padding:12px 16px">
        <div style="font-weight:700;color:#22c55e;margin-bottom:6px">✓ Update erfolgreich</div>
        <button onclick="location.reload()" class="btn-mark" style="background:#15803d;font-size:.85rem">
          Seite neu laden
        </button>
      </div>`;
    actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
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
          Bitte starte den Dienst neu: <code style="color:#fca5a5">sudo systemctl restart hausradar</code>
        </div>
      </div>`;
    actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
    document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
    apiFetch("/api/update/cancel", { method: "POST" }).catch(() => {});
  }
}

function _pollUntilAlive() {
  const logEl    = document.getElementById("update-log");
  const barEl    = document.getElementById("update-bar");
  const resultEl = document.getElementById("update-result");
  const actEl    = document.getElementById("update-actions");
  let tries = 0;

  const iv = setInterval(async () => {
    tries++;
    try {
      const h = await apiFetch("/api/health");
      clearInterval(iv);
      barEl.style.width = "100%"; barEl.style.background = "#15803d";
      _appendLog("ok", `Server neu gestartet (${tries * 2}s) – Update abgeschlossen`);
      resultEl.style.display = "block";
      resultEl.innerHTML = `
        <div style="background:#052e16;border:1px solid #22c55e;border-radius:6px;padding:12px 16px">
          <div style="font-weight:700;color:#22c55e;margin-bottom:4px">✓ Update erfolgreich installiert</div>
          <button onclick="location.reload()" class="btn-mark" style="background:#15803d;font-size:.85rem">
            Seite neu laden
          </button>
        </div>`;
      actEl.innerHTML = `<button id="btn-check-update" class="btn-secondary">🔍 Erneut prüfen</button>`;
      document.getElementById("btn-check-update")?.addEventListener("click", _checkUpdate);
    } catch {
      let dot = logEl?.querySelector(".restart-dot");
      if (!dot && logEl) {
        dot = document.createElement("div");
        dot.className = "restart-dot"; dot.style.color = "#8b5cf6";
        logEl.appendChild(dot);
      }
      if (dot) { dot.textContent = `● Warte auf Server … (${tries * 2}s)`; logEl.scrollTop = logEl.scrollHeight; }
      if (tries >= 40) { clearInterval(iv); _appendLog("warn", "Timeout – bitte Seite manuell neu laden"); }
    }
  }, 2000);
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initSettings();
  _initUpdate();

  // Delegierter Click-Handler für ⎘ Kopieren-Buttons
  document.getElementById("provisioning-section")
    ?.addEventListener("click", e => {
      const btn = e.target.closest(".btn-copy");
      if (!btn) return;
      navigator.clipboard.writeText(btn.dataset.copy || "").then(() => {
        const orig = btn.textContent;
        btn.textContent = "✓ Kopiert";
        btn.style.color = "var(--green)";
        setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 1500);
      }).catch(() => {});
    });
});
