"use strict";
/**
 * HausRadar – Kalibrierung: Raumform- & Layout-Editor
 *
 * Abhängigkeiten: calibrate-core.js ($, apiFetch), calibrate-rooms.js (showRestartHint, loadOverview)
 */

// ---------------------------------------------------------------------------
// Raumform-Editor: Polygon mit ziehbaren Punkten
// ---------------------------------------------------------------------------

function openRoomShapeEditor(room) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const W = 480, H = 380, PAD = 40;
  const rw = room.width_mm, rh = room.height_mm;
  const scale = Math.min((W - PAD * 2) / rw, (H - PAD * 2) / rh);
  const sw = rw * scale, sh = rh * scale;
  const ox = PAD + (W - PAD * 2 - sw) / 2;
  const oy = PAD + (H - PAD * 2 - sh) / 2;

  // Punkte in mm (relativ zum Raumursprung)
  let pts = (room.shape_points && room.shape_points.length >= 3)
    ? room.shape_points.map(p => [+p[0], +p[1]])
    : [[0, 0], [rw, 0], [rw, rh], [0, rh]];

  const toSvg  = p  => [ox + p[0] * scale, oy + p[1] * scale];
  const toMm   = (sx, sy) => [
    Math.max(0, Math.min(rw, (sx - ox) / scale)),
    Math.max(0, Math.min(rh, (sy - oy) / scale)),
  ];

  // Modal aufbauen
  const overlay = document.createElement("div");
  overlay.className = "shape-editor-overlay";
  overlay.innerHTML = `
    <div class="shape-editor-modal">
      <div class="shape-editor-title">
        🔷 Raumform: <strong>${esc(room.name)}</strong>
        <button id="shape-close" class="shape-editor-close">✕</button>
      </div>
      <p class="muted" style="font-size:.8rem;margin-bottom:12px">
        Punkte <strong>ziehen</strong> zum Verschieben ·
        auf eine <strong>Kante klicken</strong> zum Hinzufügen ·
        <strong>Doppelklick</strong> auf Punkt zum Löschen (min. 3)
      </p>
      <svg id="shape-svg" width="${W}" height="${H}"
        style="display:block;border:1px solid var(--border);border-radius:6px;
               background:#0a0d14;touch-action:none;cursor:crosshair">
      </svg>
      <div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;align-items:center">
        <button id="shape-reset" class="btn-secondary" style="font-size:.82rem">
          ↺ Rechteck
        </button>
        <button id="shape-clear" class="btn-secondary"
          style="font-size:.82rem;color:var(--red);border-color:var(--red)">
          🗑 Form löschen
        </button>
        <button id="shape-save" class="btn btn--primary" style="margin-left:auto">
          💾 Speichern
        </button>
      </div>
      <div id="shape-status" style="margin-top:8px;font-size:.8rem;color:var(--muted);min-height:18px"></div>
    </div>`;
  document.body.appendChild(overlay);

  const svg = document.getElementById("shape-svg");
  let dragging = null;

  function _el(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  }

  function _areaM2(pts) {
    let a = 0;
    for (let i = 0; i < pts.length; i++) {
      const j = (i + 1) % pts.length;
      a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1];
    }
    return Math.abs(a) / 2 / 1e6;
  }

  function _distSeg(px, py, x1, y1, x2, y2) {
    const dx = x2-x1, dy = y2-y1, l2 = dx*dx+dy*dy;
    if (!l2) return Math.hypot(px-x1, py-y1);
    const t = Math.max(0, Math.min(1, ((px-x1)*dx+(py-y1)*dy)/l2));
    return Math.hypot(px-(x1+t*dx), py-(y1+t*dy));
  }

  function getSvgXY(e) {
    const r = svg.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return [src.clientX - r.left, src.clientY - r.top];
  }

  function render() {
    svg.innerHTML = "";

    // Gitter (500 mm Schritte)
    const step = Math.max(500, Math.round(rw / 8 / 500) * 500);
    for (let x = 0; x <= rw; x += step) {
      svg.appendChild(_el("line", {
        x1: ox + x*scale, y1: oy, x2: ox + x*scale, y2: oy + sh,
        stroke: "#1a1d27", "stroke-width": 1,
      }));
    }
    for (let y = 0; y <= rh; y += step) {
      svg.appendChild(_el("line", {
        x1: ox, y1: oy + y*scale, x2: ox + sw, y2: oy + y*scale,
        stroke: "#1a1d27", "stroke-width": 1,
      }));
    }

    // Begrenzungsrechteck (gestrichelt)
    svg.appendChild(_el("rect", {
      x: ox, y: oy, width: sw, height: sh,
      fill: "none", stroke: "#2a2d3a", "stroke-width": 1, "stroke-dasharray": "4,4",
    }));

    // Dimensionsbeschriftungen
    const addTxt = (x, y, txt, anchor = "middle") => {
      const t = _el("text", {
        x, y, fill: "#4b5563", "font-size": 10,
        "text-anchor": anchor, "font-family": "system-ui,sans-serif",
      });
      t.textContent = txt;
      svg.appendChild(t);
    };
    addTxt(ox + sw/2, oy - 10, `${(rw/1000).toFixed(2)} m`);
    addTxt(ox - 10, oy + sh/2, `${(rh/1000).toFixed(2)} m`, "end");

    // Polygon-Füllung
    const polyPts = pts.map(p => toSvg(p).join(",")).join(" ");
    svg.appendChild(_el("polygon", {
      points: polyPts, fill: "#22d3ee1a",
      stroke: "#22d3ee", "stroke-width": 1.5, "stroke-linejoin": "round",
    }));

    // Unsichtbare dicke Kanten (zum Anklicken)
    for (let i = 0; i < pts.length; i++) {
      const j = (i + 1) % pts.length;
      const [x1, y1] = toSvg(pts[i]), [x2, y2] = toSvg(pts[j]);
      const hit = _el("line", {
        x1, y1, x2, y2,
        stroke: "transparent", "stroke-width": 14,
      });
      hit.dataset.edge = i;
      hit.style.cursor = "cell";
      svg.appendChild(hit);
    }

    // Punkte (Kreise)
    pts.forEach((p, i) => {
      const [cx, cy] = toSvg(p);
      const c = _el("circle", {
        cx, cy, r: 7,
        fill: dragging === i ? "#60a5fa" : "#22d3ee",
        stroke: "#0f1117", "stroke-width": 2,
      });
      c.dataset.pt = i;
      c.style.cursor = "grab";
      svg.appendChild(c);
    });

    // Status
    document.getElementById("shape-status").textContent =
      `${pts.length} Punkte · Fläche ca. ${_areaM2(pts).toFixed(1)} m²`;
  }

  // Pointer-Events
  svg.addEventListener("pointerdown", e => {
    const [sx, sy] = getSvgXY(e);

    // Treffer auf Punkt?
    for (let i = 0; i < pts.length; i++) {
      const [vx, vy] = toSvg(pts[i]);
      if (Math.hypot(sx-vx, sy-vy) <= 12) {
        dragging = i;
        svg.setPointerCapture(e.pointerId);
        e.preventDefault();
        return;
      }
    }

    // Treffer auf Kante → neuen Punkt einfügen
    for (let i = 0; i < pts.length; i++) {
      const j = (i + 1) % pts.length;
      const [x1, y1] = toSvg(pts[i]), [x2, y2] = toSvg(pts[j]);
      if (_distSeg(sx, sy, x1, y1, x2, y2) < 10) {
        pts.splice(i + 1, 0, toMm(sx, sy));
        dragging = i + 1;
        svg.setPointerCapture(e.pointerId);
        render();
        e.preventDefault();
        return;
      }
    }
  });

  svg.addEventListener("pointermove", e => {
    if (dragging === null) return;
    const [sx, sy] = getSvgXY(e);
    pts[dragging] = toMm(sx, sy);
    render();
    e.preventDefault();
  });

  svg.addEventListener("pointerup", () => { dragging = null; render(); });

  svg.addEventListener("dblclick", e => {
    if (pts.length <= 3) return;
    const [sx, sy] = getSvgXY(e);
    for (let i = 0; i < pts.length; i++) {
      const [vx, vy] = toSvg(pts[i]);
      if (Math.hypot(sx-vx, sy-vy) <= 14) {
        pts.splice(i, 1);
        render();
        return;
      }
    }
  });

  // Buttons
  document.getElementById("shape-close").addEventListener("click", () =>
    document.body.removeChild(overlay));

  overlay.addEventListener("click", e => {
    if (e.target === overlay) document.body.removeChild(overlay);
  });

  document.getElementById("shape-reset").addEventListener("click", () => {
    pts = [[0,0],[rw,0],[rw,rh],[0,rh]];
    render();
  });

  document.getElementById("shape-clear").addEventListener("click", async () => {
    const st = document.getElementById("shape-status");
    st.textContent = "Lösche individuelle Form …";
    try {
      await apiFetch(`/api/calibrate/room/${room.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shape_points: null }),
      });
      await apiFetch("/api/config/reload", { method: "POST" });
      st.textContent = "✓ Zurückgesetzt – Raum wird wieder als Rechteck angezeigt.";
      setTimeout(() => { document.body.removeChild(overlay); loadRoomsMgmt(); loadOverview(); }, 900);
    } catch (e) { st.textContent = `Fehler: ${e.message}`; }
  });

  document.getElementById("shape-save").addEventListener("click", async () => {
    const st = document.getElementById("shape-status");
    st.textContent = "Speichere …";
    try {
      await apiFetch(`/api/calibrate/room/${room.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          shape_points: pts.map(p => [Math.round(p[0]), Math.round(p[1])]),
        }),
      });
      await apiFetch("/api/config/reload", { method: "POST" });
      st.textContent = "✓ Gespeichert!";
      setTimeout(() => { document.body.removeChild(overlay); loadRoomsMgmt(); loadOverview(); }, 800);
    } catch (e) { st.textContent = `Fehler: ${e.message}`; }
  });

  render();
}

// ---------------------------------------------------------------------------
// Visueller Raum-Layout-Editor mit SVG Drag-and-Drop
// ---------------------------------------------------------------------------

function openRoomLayoutEditor(room, allRooms) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PAD    = 28;   // px Abstand zwischen SVG-Rand und Raumrechteck

  // Skalierung: Raum soll gut in den verfügbaren Platz passen
  const maxW  = Math.min(window.innerWidth  - 48, 760) - PAD * 2;
  const maxH  = Math.min(window.innerHeight - 220, 540) - PAD * 2;
  const scale = Math.min(maxW / room.width_mm, maxH / room.height_mm) * 0.94;
  const svgW  = Math.round(room.width_mm  * scale + PAD * 2);
  const svgH  = Math.round(room.height_mm * scale + PAD * 2);

  // ── Zustand (mutable, per Element) ───────────────────────────────────────
  const furnState = {};
  for (const f of (room.furniture || []))
    furnState[f.id] = { x_mm: f.x_mm, y_mm: f.y_mm,
                        orig_x: f.x_mm, orig_y: f.y_mm };

  const doorState = {};
  for (const d of (room.doors || []))
    doorState[d.id] = { position_mm: d.position_mm, orig_pos: d.position_mm,
                        wall: d.wall, width_mm: d.width_mm, name: d.name };

  // ── Overlay + Modal ───────────────────────────────────────────────────────
  document.querySelectorAll(".room-layout-overlay").forEach(e => e.remove());

  const overlay = document.createElement("div");
  overlay.className = "room-layout-overlay";

  const modal = document.createElement("div");
  modal.className = "room-layout-modal";

  const titleEl = document.createElement("div");
  titleEl.className = "room-layout-title";
  titleEl.textContent = `📐 ${room.name} – Layout verschieben`;

  const hint = document.createElement("p");
  hint.className = "room-layout-hint";
  hint.innerHTML =
    "<span style='color:var(--accent)'>Möbel</span> einzeln ziehen · " +
    "<span style='color:#f97316'>Türen</span> entlang der Wand · " +
    "<span style='color:var(--muted)'>Hintergrund ziehen = alle Möbel verschieben</span>";

  // ── SVG aufbauen ──────────────────────────────────────────────────────────
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width",   svgW);
  svg.setAttribute("height",  svgH);
  svg.style.cssText = "display:block;touch-action:none;border-radius:6px;" +
                      "background:#0d1117;flex-shrink:0";

  function el(tag, attrs) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }

  // Raumfläche
  svg.appendChild(el("rect", {
    x: PAD, y: PAD,
    width:  room.width_mm  * scale,
    height: room.height_mm * scale,
    fill: "#1a1d27", stroke: "#3b4263", "stroke-width": "2", rx: "3",
  }));

  // Gitterlinien
  const gridStep = room.width_mm > 5000 ? 1000 : 500;
  const grid = el("g", { opacity: "0.12", stroke: "#6b7280", "stroke-width": "1" });
  for (let x = gridStep; x < room.width_mm; x += gridStep) {
    const px = PAD + x * scale;
    grid.appendChild(el("line", { x1: px, y1: PAD, x2: px, y2: PAD + room.height_mm * scale }));
  }
  for (let y = gridStep; y < room.height_mm; y += gridStep) {
    const py = PAD + y * scale;
    grid.appendChild(el("line", { x1: PAD, y1: py, x2: PAD + room.width_mm * scale, y2: py }));
  }
  svg.appendChild(grid);

  // Maß-Labels
  function txt(x, y, content, extra = {}) {
    const t = el("text", { x, y, "text-anchor": "middle", "font-size": "10",
                            fill: "#6b7280", "pointer-events": "none", ...extra });
    t.textContent = content;
    return t;
  }
  svg.appendChild(txt(PAD + room.width_mm * scale / 2, svgH - 5,
    `${(room.width_mm/1000).toFixed(2)} m`));
  const ht = txt(10, PAD + room.height_mm * scale / 2,
    `${(room.height_mm/1000).toFixed(2)} m`,
    { transform: `rotate(-90,10,${PAD + room.height_mm * scale / 2})` });
  svg.appendChild(ht);

  // Sensor (nicht ziehbar, nur als Referenz)
  for (const s of (room.sensors || [])) {
    const sx = PAD + s.x_mm * scale, sy = PAD + s.y_mm * scale;
    svg.appendChild(el("circle", { cx: sx, cy: sy, r: 5, fill: "#3b82f6", opacity: "0.6" }));
    const st = el("text", { x: sx, y: sy - 8, "text-anchor": "middle",
                             "font-size": "9", fill: "#3b82f6ab", "pointer-events": "none" });
    st.textContent = "📡";
    svg.appendChild(st);
  }

  // ── Möbel-Elemente ────────────────────────────────────────────────────────
  const furnEls = {};  // id → { g, rect }
  for (const f of (room.furniture || [])) {
    const s   = furnState[f.id];
    const fw  = f.width_mm  * scale;
    const fh  = f.height_mm * scale;
    const g   = el("g", { "data-type": "furn", "data-id": f.id,
                           style: "cursor:grab" });
    const r   = el("rect", {
      x: PAD + s.x_mm * scale, y: PAD + s.y_mm * scale,
      width: fw, height: fh,
      fill: "#1e3a5f", stroke: "#3b82f6", "stroke-width": "1.5", rx: "2",
    });
    const t   = el("text", {
      x: PAD + s.x_mm * scale + fw / 2,
      y: PAD + s.y_mm * scale + fh / 2 + 4,
      "text-anchor": "middle",
      "font-size":  Math.max(9, Math.min(13, fw / 8)).toFixed(0),
      fill: "#93c5fd", "pointer-events": "none", "user-select": "none",
    });
    t.textContent = f.name;
    g.appendChild(r); g.appendChild(t);
    svg.appendChild(g);
    furnEls[f.id] = { g, rect: r, label: t, fw, fh };
  }

  // ── Tür-Elemente ──────────────────────────────────────────────────────────
  const DOOR_THICK = 10;  // px – Türdicke senkrecht zur Wand
  const doorEls = {};     // id → { g, rect }

  function doorGeometry(wall, position_mm, width_mm) {
    const dw = width_mm * scale;
    switch (wall) {
      case "top":    return { x: PAD + position_mm * scale, y: PAD - DOOR_THICK / 2,
                              w: dw, h: DOOR_THICK, cursor: "ew-resize" };
      case "bottom": return { x: PAD + position_mm * scale,
                              y: PAD + room.height_mm * scale - DOOR_THICK / 2,
                              w: dw, h: DOOR_THICK, cursor: "ew-resize" };
      case "left":   return { x: PAD - DOOR_THICK / 2, y: PAD + position_mm * scale,
                              w: DOOR_THICK, h: dw, cursor: "ns-resize" };
      case "right":  return { x: PAD + room.width_mm * scale - DOOR_THICK / 2,
                              y: PAD + position_mm * scale,
                              w: DOOR_THICK, h: dw, cursor: "ns-resize" };
      default:       return null;
    }
  }

  for (const d of (room.doors || [])) {
    const s   = doorState[d.id];
    const geo = doorGeometry(d.wall, s.position_mm, d.width_mm);
    if (!geo) continue;
    const g   = el("g", { "data-type": "door", "data-id": d.id,
                           style: `cursor:${geo.cursor}` });
    const r   = el("rect", {
      x: geo.x, y: geo.y, width: geo.w, height: geo.h,
      fill: "#f9731680", stroke: "#f97316", "stroke-width": "1.5", rx: "2",
    });
    const tt = document.createElementNS(SVG_NS, "title");
    tt.textContent = d.name;
    g.appendChild(r); g.appendChild(tt);
    svg.appendChild(g);
    doorEls[d.id] = { g, rect: r, wall: d.wall, width_mm: d.width_mm };
  }

  // ── Drag-Logik ────────────────────────────────────────────────────────────
  let drag = null;
  // Für "Alle verschieben": gespeicherte Ausgangspositionne pro Möbel
  let allOrigPositions = {};

  function getClientXY(e) {
    if (e.touches && e.touches[0]) return { cx: e.touches[0].clientX, cy: e.touches[0].clientY };
    return { cx: e.clientX, cy: e.clientY };
  }

  // Alle Möbel-SVG-Elemente auf aktuelle furnState-Position neu zeichnen
  function redrawAllFurn() {
    for (const [id, s] of Object.entries(furnState)) {
      const els = furnEls[id];
      if (!els) continue;
      const px = PAD + s.x_mm * scale, py = PAD + s.y_mm * scale;
      els.rect.setAttribute("x", px);
      els.rect.setAttribute("y", py);
      els.label.setAttribute("x", px + els.fw / 2);
      els.label.setAttribute("y", py + els.fh / 2 + 4);
    }
  }

  function onPointerDown(e) {
    const { cx, cy } = getClientXY(e);
    const g = e.target.closest("[data-type]");

    // Kein Treffer auf Möbel/Tür → Hintergrund ziehen = ALLE Möbel verschieben
    if (!g) {
      e.preventDefault();
      allOrigPositions = {};
      for (const [id, s] of Object.entries(furnState))
        allOrigPositions[id] = { x_mm: s.x_mm, y_mm: s.y_mm };
      drag = { type: "all", startCX: cx, startCY: cy };
      svg.style.cursor = "grabbing";
      return;
    }

    e.preventDefault();
    const type = g.dataset.type;
    const id   = g.dataset.id;
    g.style.cursor = "grabbing";

    if (type === "furn") {
      const s = furnState[id];
      drag = { type, id, startCX: cx, startCY: cy,
               origXmm: s.x_mm, origYmm: s.y_mm };
    } else {
      const s   = doorState[id];
      const axis = (s.wall === "top" || s.wall === "bottom") ? "x" : "y";
      drag = { type, id, startCX: cx, startCY: cy,
               origPos: s.position_mm, axis };
    }
  }

  function onPointerMove(e) {
    if (!drag) return;
    e.preventDefault();
    const { cx, cy } = getClientXY(e);
    const dxMm = (cx - drag.startCX) / scale;
    const dyMm = (cy - drag.startCY) / scale;

    if (drag.type === "all") {
      // Alle Möbel gleichzeitig verschieben
      for (const [id, orig] of Object.entries(allOrigPositions)) {
        const f   = (room.furniture || []).find(x => x.id === id);
        if (!f) continue;
        const s = furnState[id];
        s.x_mm = Math.max(0, Math.min(room.width_mm  - f.width_mm,  orig.x_mm + dxMm));
        s.y_mm = Math.max(0, Math.min(room.height_mm - f.height_mm, orig.y_mm + dyMm));
      }
      redrawAllFurn();

    } else if (drag.type === "furn") {
      const f   = (room.furniture || []).find(x => x.id === drag.id);
      const els = furnEls[drag.id];
      const s   = furnState[drag.id];

      const maxX = room.width_mm  - f.width_mm;
      const maxY = room.height_mm - f.height_mm;
      s.x_mm = Math.max(0, Math.min(maxX, drag.origXmm + dxMm));
      s.y_mm = Math.max(0, Math.min(maxY, drag.origYmm + dyMm));

      const px = PAD + s.x_mm * scale, py = PAD + s.y_mm * scale;
      els.rect.setAttribute("x", px);
      els.rect.setAttribute("y", py);
      els.label.setAttribute("x", px + els.fw / 2);
      els.label.setAttribute("y", py + els.fh / 2 + 4);

    } else {
      const s   = doorState[drag.id];
      const maxPos = (drag.axis === "x" ? room.width_mm : room.height_mm) - s.width_mm;
      const delta  = drag.axis === "x" ? dxMm : dyMm;
      s.position_mm = Math.max(0, Math.min(maxPos, drag.origPos + delta));

      const geo = doorGeometry(s.wall, s.position_mm, s.width_mm);
      if (geo) {
        const r = doorEls[drag.id].rect;
        r.setAttribute("x", geo.x); r.setAttribute("y", geo.y);
      }
    }
  }

  function onPointerUp(e) {
    if (!drag) return;
    if (drag.type === "all") {
      svg.style.cursor = "";
    } else {
      const g = svg.querySelector(`[data-id="${drag.id}"]`);
      if (g) g.style.cursor = drag.type === "furn" ? "grab" : "";
    }
    drag = null;
  }

  svg.addEventListener("mousedown",  onPointerDown);
  svg.addEventListener("touchstart", onPointerDown, { passive: false });
  window.addEventListener("mousemove",  onPointerMove);
  window.addEventListener("touchmove",  onPointerMove, { passive: false });
  window.addEventListener("mouseup",    onPointerUp);
  window.addEventListener("touchend",   onPointerUp);

  function cleanup() {
    window.removeEventListener("mousemove",  onPointerMove);
    window.removeEventListener("touchmove",  onPointerMove);
    window.removeEventListener("mouseup",    onPointerUp);
    window.removeEventListener("touchend",   onPointerUp);
  }

  // ── Footer-Buttons ────────────────────────────────────────────────────────
  const footer = document.createElement("div");
  footer.className = "room-layout-footer";

  const btnCancel = document.createElement("button");
  btnCancel.className = "btn-secondary";
  btnCancel.textContent = "Abbrechen";
  btnCancel.addEventListener("click", () => { cleanup(); overlay.remove(); });

  const btnSave = document.createElement("button");
  btnSave.className = "btn-mark";
  btnSave.textContent = "💾 Speichern";
  btnSave.addEventListener("click", async () => {
    btnSave.disabled = true;
    btnSave.textContent = "Speichert …";
    try {
      const calls = [];
      for (const [id, s] of Object.entries(furnState)) {
        if (Math.round(s.x_mm) !== s.orig_x || Math.round(s.y_mm) !== s.orig_y) {
          calls.push(apiFetch(`/api/calibrate/room/${room.id}/furniture/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ x_mm: Math.round(s.x_mm), y_mm: Math.round(s.y_mm) }),
          }));
        }
      }
      for (const [id, s] of Object.entries(doorState)) {
        if (Math.round(s.position_mm) !== s.orig_pos) {
          calls.push(apiFetch(`/api/calibrate/room/${room.id}/door/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ position_mm: Math.round(s.position_mm) }),
          }));
        }
      }
      if (calls.length) {
        await Promise.all(calls);
        showRestartHint();
        loadOverview();
      }
    } catch (err) {
      alert("Fehler beim Speichern: " + err.message);
      btnSave.disabled = false;
      btnSave.textContent = "💾 Speichern";
      return;
    }
    cleanup();
    overlay.remove();
  });

  footer.appendChild(hint);
  footer.appendChild(btnCancel);
  footer.appendChild(btnSave);

  modal.appendChild(titleEl);
  modal.appendChild(svg);
  modal.appendChild(footer);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  // Außerhalb klicken schließt
  overlay.addEventListener("click", e => {
    if (e.target === overlay) { cleanup(); overlay.remove(); }
  });
}
