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

const API = {
  health:  () => apiFetch("/api/health"),
  rooms:   () => apiFetch("/api/rooms"),
  sensors: () => apiFetch("/api/sensors"),

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
