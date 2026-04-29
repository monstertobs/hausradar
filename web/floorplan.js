"use strict";

/**
 * Floorplan – SVG-Grundrissdarstellung für HausRadar
 *
 * Koordinaten:
 *   floorplan.x/y/width/height aus rooms.json sind direkte SVG-Pixel.
 *   floorplan_x / floorplan_y aus dem WebSocket-Payload können direkt
 *   als SVG-Koordinaten für Zielpunkte verwendet werden.
 *
 * Nutzung:
 *   const fp = new Floorplan("floorplan-container");
 *   fp.init(rooms, sensors);      // einmalig nach API-Load
 *   fp.update(wsLiveData);        // bei jedem WebSocket-Frame
 */

const SVG_NS = "http://www.w3.org/2000/svg";

// Farben für bis zu 3 gleichzeitig erkannte Personen
const PERSON_COLORS = ["#3b82f6", "#f97316", "#22c55e"];

class Floorplan {
  constructor(containerId) {
    this._container   = document.getElementById(containerId);
    this._svg         = null;
    this._rooms       = [];
    this._sensors     = [];
    this._roomRects   = {};   // room_id → <rect> element
    this._trailLayer  = null;
    this._targetLayer = null;
    this._roomLastActive = {}; // room_id → Date.now()
    this._trails      = {};   // "sensorId.targetId" → [{x, y, ts}]
    this.recentTimeoutMs = 30_000;
    this.trailMaxAgeMs   = 30_000;
    this.trailMaxPoints  = 150;
  }

  // ----------------------------------------------------------------
  // Öffentliche API
  // ----------------------------------------------------------------

  init(rooms, sensors) {
    this._rooms   = rooms;
    this._sensors = sensors;
    this._build();
  }

  update(liveData) {
    if (!this._svg || !liveData || !liveData.sensors) return;

    const now        = Date.now();
    const roomStatus = {};
    const targets    = [];

    for (const [sensorId, sdata] of Object.entries(liveData.sensors)) {
      const rid = sdata.room_id;
      if (!rid) continue;

      if (!sdata.online) {
        // Offline überschreibt nur idle, nicht active/recent
        if (!roomStatus[rid]) roomStatus[rid] = "offline";
        continue;
      }

      if (sdata.target_count > 0) {
        this._roomLastActive[rid] = now;
        roomStatus[rid] = "active";
        for (const t of sdata.targets) {
          if (!t.inside_room) continue;
          targets.push(t);

          // Spur nur für echte Messungen (keine Ghost-Frames)
          if (t.ghost) continue;
          const key = `${sensorId}.track_${t.track_id ?? t.id}`;
          if (!this._trails[key]) this._trails[key] = [];
          this._trails[key].push({
            x: t.floorplan_x, y: t.floorplan_y, ts: now,
            color_idx: t.color_idx ?? 0,
          });
          if (this._trails[key].length > this.trailMaxPoints) {
            this._trails[key].shift();
          }
        }
      }
    }

    // Veraltete Spurpunkte entfernen (> 30 Sekunden)
    const cutoff = now - this.trailMaxAgeMs;
    for (const key of Object.keys(this._trails)) {
      this._trails[key] = this._trails[key].filter(p => p.ts >= cutoff);
      if (this._trails[key].length === 0) delete this._trails[key];
    }

    // Fehlende Räume: idle oder recent
    for (const room of this._rooms) {
      if (roomStatus[room.id]) continue;
      const last = this._roomLastActive[room.id];
      roomStatus[room.id] =
        (last && now - last < this.recentTimeoutMs) ? "recent" : "idle";
    }

    // Raumfarben aktualisieren
    for (const [rid, st] of Object.entries(roomStatus)) {
      const rect = this._roomRects[rid];
      if (rect) rect.setAttribute("class", `room-rect room-${st}`);
    }

    // Spuren und Zielpunkte neu zeichnen
    this._renderTrails();
    this._renderTargets(targets);
  }

  // ----------------------------------------------------------------
  // SVG aufbauen
  // ----------------------------------------------------------------

  _build() {
    // ViewBox aus Raumdaten berechnen
    let maxX = 0, maxY = 0;
    for (const r of this._rooms) {
      const fp = r.floorplan;
      maxX = Math.max(maxX, fp.x + fp.width);
      maxY = Math.max(maxY, fp.y + fp.height);
    }
    const pad = 20;
    const vw = maxX + pad;
    const vh = maxY + pad;

    const svg = this._el("svg", {
      viewBox:    `0 0 ${vw} ${vh}`,
      class:      "floorplan-svg",
      role:       "img",
      "aria-label": "Hausgrundriss",
    });

    // Filter-Definitionen
    const defs = this._el("defs");
    defs.innerHTML = `
      <filter id="fp-glow" x="-60%" y="-60%" width="220%" height="220%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur"/>
        <feMerge>
          <feMergeNode in="blur"/>
          <feMergeNode in="SourceGraphic"/>
        </feMerge>
      </filter>`;
    svg.appendChild(defs);

    // Hintergrund
    svg.appendChild(this._el("rect", {
      x: 0, y: 0, width: vw, height: vh, class: "fp-bg",
    }));

    // Räume (unterste Ebene)
    for (const room of this._rooms) this._buildRoom(svg, room);

    // Sensoren (mittlere Ebene)
    for (const sensor of this._sensors) {
      if (sensor.enabled !== false) this._buildSensor(svg, sensor);
    }

    // Spur-Ebene (unter Zielpunkten – wird bei jedem Update neu gezeichnet)
    this._trailLayer = this._el("g", { class: "trail-layer" });
    svg.appendChild(this._trailLayer);

    // Ziel-Ebene (oberste Ebene – wird bei jedem Update geleert)
    this._targetLayer = this._el("g", { class: "target-layer" });
    svg.appendChild(this._targetLayer);

    this._svg = svg;
    this._container.innerHTML = "";
    this._container.appendChild(svg);
  }

  _buildRoom(svg, room) {
    const fp = room.floorplan;
    const g  = this._el("g", { class: "room-group" });

    // Haupt-Rechteck
    const rect = this._el("rect", {
      x: fp.x, y: fp.y, width: fp.width, height: fp.height,
      class: "room-rect room-idle",
      rx: 3,
    });
    g.appendChild(rect);
    this._roomRects[room.id] = rect;

    const scX = fp.width  / room.width_mm;
    const scY = fp.height / room.height_mm;

    // Türen als Lücken in den Wänden
    for (const door of (room.doors || [])) {
      this._buildDoor(g, fp, scX, scY, door);
    }

    // Möbel (unterhalb Zonen, damit Zonen-Labels sichtbar bleiben)
    for (const furn of (room.furniture || [])) {
      const fx = fp.x + furn.x_mm * scX;
      const fy = fp.y + furn.y_mm * scY;
      const fw = furn.width_mm  * scX;
      const fh = furn.height_mm * scY;
      g.appendChild(this._el("rect", {
        x: fx, y: fy, width: fw, height: fh,
        class: `furniture-rect furniture-${furn.type || "other"}`,
        rx: 2,
      }));
      if (fw > 20 && fh > 10) {
        const ft = this._el("text", {
          x: fx + fw / 2, y: fy + fh / 2,
          class: "furniture-label",
          "text-anchor": "middle",
          "dominant-baseline": "middle",
        });
        ft.textContent = furn.name;
        g.appendChild(ft);
      }
    }

    // Zonen
    for (const zone of (room.zones || [])) {
      const zx = fp.x + zone.x_mm * scX;
      const zy = fp.y + zone.y_mm * scY;
      const zw = zone.width_mm * scX;
      const zh = zone.height_mm * scY;

      g.appendChild(this._el("rect", {
        x: zx, y: zy, width: zw, height: zh,
        class: "zone-rect",
      }));

      // Zonen-Beschriftung nur wenn genug Platz
      if (zw > 28 && zh > 12) {
        const zt = this._el("text", {
          x: zx + zw / 2, y: zy + zh / 2,
          class: "zone-label",
          "text-anchor": "middle",
          "dominant-baseline": "middle",
        });
        zt.textContent = zone.name;
        g.appendChild(zt);
      }
    }

    // Raumname (oben zentriert)
    const label = this._el("text", {
      x: fp.x + fp.width / 2,
      y: fp.y + Math.min(14, fp.height * 0.22),
      class: "room-label",
      "text-anchor": "middle",
    });
    label.textContent = room.name;
    g.appendChild(label);

    svg.appendChild(g);
  }

  _buildDoor(g, fp, scX, scY, door) {
    // Tür als Lücke in der Wand + kleines Symbol + Label
    const GAP = 3;   // px – Breite der "Wand" zum Überdecken
    const pos = door.position_mm;
    const w   = door.width_mm;

    let dx, dy, dw, dh, lx, ly;
    switch (door.wall) {
      case "top":
        dx = fp.x + pos * scX;  dy = fp.y - GAP;
        dw = w * scX;           dh = GAP * 2 + 1;
        lx = dx + dw / 2;       ly = fp.y + 9;
        break;
      case "bottom":
        dx = fp.x + pos * scX;  dy = fp.y + fp.height - GAP;
        dw = w * scX;           dh = GAP * 2 + 1;
        lx = dx + dw / 2;       ly = fp.y + fp.height - 3;
        break;
      case "left":
        dx = fp.x - GAP;        dy = fp.y + pos * scY;
        dw = GAP * 2 + 1;       dh = w * scY;
        lx = fp.x + 8;          ly = dy + dh / 2;
        break;
      case "right":
        dx = fp.x + fp.width - GAP; dy = fp.y + pos * scY;
        dw = GAP * 2 + 1;           dh = w * scY;
        lx = fp.x + fp.width - 8;   ly = dy + dh / 2;
        break;
      default: return;
    }

    // Lücke (überdeckt die Wand mit Hintergrundfarbe)
    g.appendChild(this._el("rect", {
      x: dx, y: dy, width: dw, height: dh,
      class: "door-gap",
    }));

    // Türsymbol (dünner Bogen / Linie)
    g.appendChild(this._el("rect", {
      x: dx + 0.5, y: dy + 0.5,
      width: Math.max(dw - 1, 1), height: Math.max(dh - 1, 1),
      class: "door-symbol",
    }));

    // Label wenn genug Platz
    const labelLen = (door.wall === "top" || door.wall === "bottom") ? dw : dh;
    if (labelLen > 18) {
      const lt = this._el("text", {
        x: lx, y: ly,
        class: "door-label",
        "text-anchor": "middle",
        "dominant-baseline": "middle",
      });
      lt.textContent = door.connects_to ? `→ ${door.connects_to}` : "Tür";
      g.appendChild(lt);
    }
  }

  _buildSensor(svg, sensor) {
    const room = this._rooms.find(r => r.id === sensor.room_id);
    if (!room) return;

    const fp  = room.floorplan;
    const scX = fp.width  / room.width_mm;
    const scY = fp.height / room.height_mm;
    const sx  = fp.x + sensor.x_mm * scX;
    const sy  = fp.y + sensor.y_mm * scY;

    // Sensorpunkt
    svg.appendChild(this._el("circle", {
      cx: sx, cy: sy, r: 3.5,
      class: "sensor-dot",
    }));

    // Richtungspfeil (Dreieck zeigt standardmäßig in +y = nach unten)
    // rotation_deg=0 → Pfeil zeigt nach unten (in den Raum hinein)
    const sz  = 5;
    const pts = [
      `${sx},${sy + sz * 1.6}`,
      `${sx - sz * 0.75},${sy - sz * 0.4}`,
      `${sx + sz * 0.75},${sy - sz * 0.4}`,
    ].join(" ");
    svg.appendChild(this._el("polygon", {
      points: pts,
      class:  "sensor-arrow",
      transform: `rotate(${sensor.rotation_deg}, ${sx}, ${sy})`,
    }));
  }

  _renderTrails() {
    while (this._trailLayer.firstChild) {
      this._trailLayer.removeChild(this._trailLayer.firstChild);
    }

    for (const points of Object.values(this._trails)) {
      if (points.length < 2) continue;

      const color = PERSON_COLORS[points[points.length - 1].color_idx ?? 0];
      const mid   = Math.floor(points.length / 2);

      // Ältere Hälfte (blasser)
      if (mid >= 2) {
        const el = this._el("polyline", {
          points: points.slice(0, mid + 1).map(p => `${p.x},${p.y}`).join(" "),
          class:  "trail-line trail-line--old",
        });
        el.style.stroke = color;
        this._trailLayer.appendChild(el);
      }

      // Neuere Hälfte (heller)
      const el = this._el("polyline", {
        points: points.slice(mid).map(p => `${p.x},${p.y}`).join(" "),
        class:  "trail-line trail-line--new",
      });
      el.style.stroke = color;
      this._trailLayer.appendChild(el);
    }
  }

  _renderTargets(targets) {
    // Ziel-Ebene leeren
    while (this._targetLayer.firstChild) {
      this._targetLayer.removeChild(this._targetLayer.firstChild);
    }

    for (const t of targets) {
      const x     = t.floorplan_x;
      const y     = t.floorplan_y;
      const color = PERSON_COLORS[t.color_idx ?? 0];
      const alpha = t.ghost ? 0.3 : 1.0;

      // Äußerer Pulsring
      const ring = this._el("circle", { cx: x, cy: y, r: 8, class: "target-ring" });
      ring.style.stroke  = color;
      ring.style.opacity = alpha;
      this._targetLayer.appendChild(ring);

      // Innerer Punkt mit Glow
      const dot = this._el("circle", {
        cx: x, cy: y, r: 4.5,
        class:  "target-dot",
        filter: "url(#fp-glow)",
      });
      dot.style.fill    = color;
      dot.style.opacity = alpha;
      this._targetLayer.appendChild(dot);
    }
  }

  // ----------------------------------------------------------------
  // Hilfsmethode
  // ----------------------------------------------------------------

  _el(tag, attrs = {}) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  }
}
