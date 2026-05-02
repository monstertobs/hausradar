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
 *   fp.enableEditMode();          // Möbel/Türen per Drag-and-Drop verschieben
 *   fp.disableEditMode();
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
    this._roomScales  = {};   // room_id → { fp, scX, scY, room }
    this._trailLayer  = null;
    this._targetLayer = null;
    this._roomLastActive = {}; // room_id → Date.now()
    this._trails      = {};   // "sensorId.targetId" → [{x, y, ts}]
    this.recentTimeoutMs = 30_000;
    this.trailMaxAgeMs   = 30_000;
    this.trailMaxPoints  = 150;

    // Edit-Modus
    this._editMode = false;
    this._drag     = null;
    this._boundOnPtrDown = null;
    this._boundOnPtrMove = null;
    this._boundOnPtrUp   = null;
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
  // Edit-Modus: Möbel & Türen per Drag-and-Drop verschieben
  // ----------------------------------------------------------------

  enableEditMode() {
    if (!this._svg || this._editMode) return;
    this._editMode = true;
    this._svg.classList.add("fp-edit-mode");
    this._boundOnPtrDown = this._onEditPtrDown.bind(this);
    this._svg.addEventListener("pointerdown", this._boundOnPtrDown);
  }

  disableEditMode() {
    if (!this._svg || !this._editMode) return;
    this._editMode = false;
    this._svg.classList.remove("fp-edit-mode");
    this._svg.removeEventListener("pointerdown", this._boundOnPtrDown);
    if (this._drag) {
      window.removeEventListener("pointermove", this._boundOnPtrMove);
      window.removeEventListener("pointerup",   this._boundOnPtrUp);
      this._drag = null;
    }
  }

  _svgCoords(e) {
    const pt  = this._svg.createSVGPoint();
    const src = e.changedTouches ? e.changedTouches[0] : e;
    pt.x = src.clientX;
    pt.y = src.clientY;
    return pt.matrixTransform(this._svg.getScreenCTM().inverse());
  }

  _onEditPtrDown(e) {
    // Dreh-Handle hat Vorrang vor Drag
    if (e.target.dataset.action === "rotate") {
      e.preventDefault();
      const furnG = e.target.closest("[data-drag='furniture']");
      if (furnG && furnG.dataset.id) this._rotateFurniture(furnG, 90);
      return;
    }

    const el = e.target.closest("[data-drag]");
    if (!el) return;

    // Nur Elemente mit ID können gespeichert werden
    if (!el.dataset.id) return;

    e.preventDefault();

    const roomId = el.dataset.roomId;
    const sc = this._roomScales[roomId];
    if (!sc) return;

    const pt   = this._svgCoords(e);
    const type = el.dataset.drag;

    this._drag = { el, type, roomId, sc, id: el.dataset.id,
                   startX: pt.x, startY: pt.y, dirty: false };

    if (type === "furniture") {
      this._drag.origXMm = parseFloat(el.dataset.xMm);
      this._drag.origYMm = parseFloat(el.dataset.yMm);
      this._drag.wMm     = parseFloat(el.dataset.wMm);
      this._drag.hMm     = parseFloat(el.dataset.hMm);
    } else { // door
      this._drag.origPosMm = parseFloat(el.dataset.posMm);
      this._drag.wall      = el.dataset.wall;
      this._drag.wMm       = parseFloat(el.dataset.wMm);
    }

    this._boundOnPtrMove = this._onEditPtrMove.bind(this);
    this._boundOnPtrUp   = this._onEditPtrUp.bind(this);
    window.addEventListener("pointermove", this._boundOnPtrMove);
    window.addEventListener("pointerup",   this._boundOnPtrUp);
  }

  _onEditPtrMove(e) {
    if (!this._drag) return;
    e.preventDefault();

    const pt = this._svgCoords(e);
    const d  = this._drag;
    const { fp, scX, scY } = d.sc;
    const dx = pt.x - d.startX;
    const dy = pt.y - d.startY;

    if (d.type === "furniture") {
      const origFx = fp.x + d.origXMm * scX;
      const origFy = fp.y + d.origYMm * scY;
      const wPx    = d.wMm * scX;
      const hPx    = d.hMm * scY;

      const newFx = Math.max(fp.x, Math.min(fp.x + fp.width  - wPx, origFx + dx));
      const newFy = Math.max(fp.y, Math.min(fp.y + fp.height - hPx, origFy + dy));

      const rect = d.el.querySelector("rect");
      const text = d.el.querySelector("text");
      rect.setAttribute("x", newFx);
      rect.setAttribute("y", newFy);
      if (text) {
        text.setAttribute("x", newFx + wPx / 2);
        text.setAttribute("y", newFy + hPx / 2);
      }
      // Rotations-Transform mitführen (Zentrum folgt dem Möbel)
      const rotDeg = parseFloat(d.el.dataset.rotDeg) || 0;
      if (rotDeg) {
        d.el.setAttribute("transform",
          `rotate(${rotDeg}, ${newFx + wPx / 2}, ${newFy + hPx / 2})`);
      }
      // Dreh-Handle-Position aktualisieren
      const rotHandle = d.el.querySelector("[data-action='rotate']");
      const rotIcon   = d.el.querySelector(".fp-rot-handle-icon");
      if (rotHandle) { rotHandle.setAttribute("cx", newFx + wPx); rotHandle.setAttribute("cy", newFy); }
      if (rotIcon)   { rotIcon.setAttribute("x",   newFx + wPx); rotIcon.setAttribute("y",   newFy + 0.5); }
      d.curFx = newFx;
      d.curFy = newFy;

      // Zugehörige Zone (gleiche ID) mitbewegen
      const zoneRect = d.el.closest(".room-group")
        ?.querySelector(`[data-zone-id="${d.id}"]`);
      if (zoneRect) {
        zoneRect.setAttribute("x", newFx);
        zoneRect.setAttribute("y", newFy);
      }

    } else { // door
      const wall       = d.wall;
      const origPosMm  = d.origPosMm;
      const wMm        = d.wMm;

      let newPosMm;
      if (wall === "top" || wall === "bottom") {
        const origPosPx = fp.x + origPosMm * scX;
        const maxPosPx  = fp.x + fp.width - wMm * scX;
        const newPosPx  = Math.max(fp.x, Math.min(maxPosPx, origPosPx + dx));
        newPosMm = Math.round((newPosPx - fp.x) / scX);
      } else {
        const origPosPx = fp.y + origPosMm * scY;
        const maxPosPx  = fp.y + fp.height - wMm * scY;
        const newPosPx  = Math.max(fp.y, Math.min(maxPosPx, origPosPx + dy));
        newPosMm = Math.round((newPosPx - fp.y) / scY);
      }

      this._updateDoorElements(d.el, fp, scX, scY, {
        wall,
        position_mm:  newPosMm,
        width_mm:     wMm,
        connects_to:  d.el.dataset.connectsTo || "",
      });
      d.curPosMm = newPosMm;
    }

    d.dirty = true;
  }

  async _onEditPtrUp(e) {
    window.removeEventListener("pointermove", this._boundOnPtrMove);
    window.removeEventListener("pointerup",   this._boundOnPtrUp);

    const d = this._drag;
    this._drag = null;
    if (!d || !d.dirty) return;

    if (d.type === "furniture") {
      const { fp, scX, scY } = d.sc;
      const newXMm = Math.round((d.curFx - fp.x) / scX);
      const newYMm = Math.round((d.curFy - fp.y) / scY);
      d.el.dataset.xMm  = newXMm;
      d.el.dataset.yMm  = newYMm;
      d.el.dataset.cxSvg = d.curFx + d.wMm * d.sc.scX / 2;
      d.el.dataset.cySvg = d.curFy + d.hMm * d.sc.scY / 2;

      try {
        await apiFetch(`/api/calibrate/room/${d.roomId}/furniture/${d.id}`, {
          method:  "PATCH",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ x_mm: newXMm, y_mm: newYMm }),
        });
        _fpToast("✓ Möbel gespeichert");
      } catch (err) {
        console.error("Fehler beim Speichern des Möbelstücks:", err);
        _fpToast("⚠ Speichern fehlgeschlagen", true);
      }

    } else { // door
      d.el.dataset.posMm = d.curPosMm;

      try {
        await apiFetch(`/api/calibrate/room/${d.roomId}/door/${d.id}`, {
          method:  "PATCH",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ position_mm: d.curPosMm }),
        });
        _fpToast("✓ Tür gespeichert");
      } catch (err) {
        console.error("Fehler beim Speichern der Tür:", err);
        _fpToast("⚠ Speichern fehlgeschlagen", true);
      }
    }
  }

  // Möbelstück um deltaDeg Grad im Uhrzeigersinn drehen und speichern
  async _rotateFurniture(furnG, deltaDeg) {
    const roomId = furnG.dataset.roomId;
    const curr   = parseFloat(furnG.dataset.rotDeg) || 0;
    const newRot = ((curr + deltaDeg) % 360 + 360) % 360;
    const cx     = parseFloat(furnG.dataset.cxSvg);
    const cy     = parseFloat(furnG.dataset.cySvg);

    furnG.dataset.rotDeg = newRot;
    if (newRot === 0) {
      furnG.removeAttribute("transform");
    } else {
      furnG.setAttribute("transform", `rotate(${newRot}, ${cx}, ${cy})`);
    }

    try {
      await apiFetch(`/api/calibrate/room/${roomId}/furniture/${furnG.dataset.id}`, {
        method:  "PATCH",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ rotation_deg: newRot }),
      });
      _fpToast(`↻ ${newRot}° gespeichert`);
    } catch (err) {
      console.error("Fehler beim Drehen:", err);
      _fpToast("⚠ Speichern fehlgeschlagen", true);
    }
  }

  // Türkinder (gap, symbol, label) in-place neu aufbauen
  _updateDoorElements(doorG, fp, scX, scY, door) {
    while (doorG.firstChild) doorG.removeChild(doorG.firstChild);

    const GAP = 3;
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

    doorG.appendChild(this._el("rect", { x: dx, y: dy, width: dw, height: dh, class: "door-gap" }));
    doorG.appendChild(this._el("rect", {
      x: dx + 0.5, y: dy + 0.5,
      width: Math.max(dw - 1, 1), height: Math.max(dh - 1, 1),
      class: "door-symbol",
    }));

    const labelLen = (door.wall === "top" || door.wall === "bottom") ? dw : dh;
    if (labelLen > 18) {
      const lt = this._el("text", {
        x: lx, y: ly, class: "door-label",
        "text-anchor": "middle", "dominant-baseline": "middle",
      });
      lt.textContent = door.connects_to ? `→ ${door.connects_to}` : "Tür";
      doorG.appendChild(lt);
    }
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
    const fp  = room.floorplan;
    const g   = this._el("g", { class: "room-group" });
    const scX = fp.width  / room.width_mm;
    const scY = fp.height / room.height_mm;

    // Skalierungsfaktoren für Edit-Modus merken
    this._roomScales[room.id] = { fp, scX, scY, room };

    // Raumform: Polygon wenn shape_points vorhanden, sonst Rechteck
    let roomShape;
    if (room.shape_points && room.shape_points.length >= 3) {
      const pts = room.shape_points
        .map(([xMm, yMm]) => `${fp.x + xMm * scX},${fp.y + yMm * scY}`)
        .join(" ");
      roomShape = this._el("polygon", { points: pts, class: "room-rect room-idle" });
    } else {
      roomShape = this._el("rect", {
        x: fp.x, y: fp.y, width: fp.width, height: fp.height,
        class: "room-rect room-idle", rx: 3,
      });
    }
    g.appendChild(roomShape);
    this._roomRects[room.id] = roomShape;

    // Türen als Lücken in den Wänden (jetzt als <g> mit data-attrs)
    for (const door of (room.doors || [])) {
      const doorG = this._buildDoor(fp, scX, scY, door, room.id);
      g.appendChild(doorG);
    }

    // Möbel (als <g> mit data-attrs für den Edit-Modus)
    for (const furn of (room.furniture || [])) {
      const fx     = fp.x + furn.x_mm * scX;
      const fy     = fp.y + furn.y_mm * scY;
      const fw     = furn.width_mm  * scX;
      const fh     = furn.height_mm * scY;
      const rotDeg = furn.rotation_deg || 0;
      const cx_svg = fx + fw / 2;
      const cy_svg = fy + fh / 2;

      const furnAttrs = {
        class:           "fp-draggable",
        "data-drag":     "furniture",
        "data-room-id":  room.id,
        "data-x-mm":     furn.x_mm,
        "data-y-mm":     furn.y_mm,
        "data-w-mm":     furn.width_mm,
        "data-h-mm":     furn.height_mm,
        "data-rot-deg":  rotDeg,
        "data-cx-svg":   cx_svg,
        "data-cy-svg":   cy_svg,
      };
      if (furn.id) furnAttrs["data-id"] = furn.id;
      if (rotDeg)  furnAttrs["transform"] = `rotate(${rotDeg}, ${cx_svg}, ${cy_svg})`;

      const furnG = this._el("g", furnAttrs);
      furnG.appendChild(this._el("rect", {
        x: fx, y: fy, width: fw, height: fh,
        class: `furniture-rect furniture-${furn.type || "other"}`,
        rx: 2,
      }));
      if (fw > 20 && fh > 10) {
        const ft = this._el("text", {
          x: cx_svg, y: cy_svg,
          class: "furniture-label",
          "text-anchor": "middle",
          "dominant-baseline": "middle",
        });
        ft.textContent = furn.name;
        furnG.appendChild(ft);
      }

      // Dreh-Handle (nur im Edit-Modus sichtbar, via CSS)
      if (furn.id) {
        furnG.appendChild(this._el("circle", {
          cx: fx + fw, cy: fy, r: 7,
          class: "fp-rot-handle",
          "data-action": "rotate",
        }));
        const rTxt = this._el("text", {
          x: fx + fw, y: fy + 0.5,
          class: "fp-rot-handle-icon",
          "text-anchor": "middle",
          "dominant-baseline": "middle",
          "font-size": 8,
          "pointer-events": "none",
        });
        rTxt.textContent = "↻";
        furnG.appendChild(rTxt);
      }

      g.appendChild(furnG);
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
        "data-zone-id": zone.id || "",
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

  _buildDoor(fp, scX, scY, door, roomId) {
    const doorAttrs = {
      class: "fp-draggable",
      "data-drag":        "door",
      "data-room-id":     roomId,
      "data-wall":        door.wall,
      "data-pos-mm":      door.position_mm,
      "data-w-mm":        door.width_mm,
      "data-connects-to": door.connects_to || "",
    };
    if (door.id) doorAttrs["data-id"] = door.id;

    const doorG = this._el("g", doorAttrs);
    this._updateDoorElements(doorG, fp, scX, scY, door);
    return doorG;
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

// ----------------------------------------------------------------
// Toast-Benachrichtigung (modul-global, ohne Framework)
// ----------------------------------------------------------------
function _fpToast(msg, isError = false) {
  let toast = document.getElementById("fp-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "fp-toast";
    toast.className = "fp-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.className   = "fp-toast fp-toast--visible" + (isError ? " fp-toast--error" : "");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.classList.remove("fp-toast--visible");
  }, 2000);
}
