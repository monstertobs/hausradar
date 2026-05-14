const API_BASE = "";

// ---------------------------------------------------------------------------
// HTML-Escaping (HR-SEC-006 – XSS-Schutz für innerHTML-Inserts)
// ---------------------------------------------------------------------------
function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function apiFetch(path, options = {}) {
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail ?? ""; } catch (_) {}
    throw new Error(detail || `HTTP ${res.status}: ${path}`);
  }
  // DELETE/204 oder leere Antwort
  const ct = res.headers.get("content-type") || "";
  if (res.status === 204 || !ct.includes("application/json")) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Version-Badge  – wird beim Laden jeder Seite in die .logo-Überschrift eingefügt
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  try {
    const h = await apiFetch("/api/health");
    if (!h || !h.version) return;
    const logo = document.querySelector(".logo");
    if (!logo) return;
    const badge = document.createElement("span");
    badge.className = "version-badge";
    badge.textContent = "v" + h.version;
    logo.appendChild(badge);
  } catch (_) {}
});

const API = {
  health:  () => apiFetch("/api/health"),
  live:    () => apiFetch("/api/live"),
  rooms:   () => apiFetch("/api/rooms"),
  sensors: () => apiFetch("/api/sensors"),

  connections: {
    list:   ()    => apiFetch("/api/connections"),
    delete: (id)  => apiFetch(`/api/connections/${encodeURIComponent(id)}`, { method: "DELETE" }),
    reset:  (id)  => apiFetch(`/api/connections/${encodeURIComponent(id)}/reset`, { method: "POST" }),
  },

  orientations: {
    all:    ()    => apiFetch("/api/sensors/orientations"),
    sensor: (id)  => apiFetch(`/api/sensors/${encodeURIComponent(id)}/orientation`),
  },

  furniture: {
    zones:  (roomId) => apiFetch(`/api/furniture/zones${roomId ? "?room_id=" + encodeURIComponent(roomId) : ""}`),
    delete: (id)     => apiFetch(`/api/furniture/zones/${encodeURIComponent(id)}`, { method: "DELETE" }),
    patch:  (id, body) => apiFetch(`/api/furniture/zones/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    prune:  ()       => apiFetch("/api/furniture/prune", { method: "POST" }),
  },

  profile: {
    hourly:  (qs) => apiFetch(`/api/profile/hourly?${qs}`),
    heatmap: (qs) => apiFetch(`/api/profile/heatmap?${qs}`),
    zones:   (qs) => apiFetch(`/api/profile/zones?${qs}`),
    rooms:   (qs) => apiFetch(`/api/profile/rooms?${qs}`),
  },

  history: {
    sessions: (qs) => apiFetch(`/api/history/sessions?${qs}`),
  },
};
