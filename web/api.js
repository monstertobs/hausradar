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

async function apiFetch(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`);
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
