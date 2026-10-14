// The `orbit` (system map) and `starmap` (galaxy map) sections, drawn as SVG.
//
// The geometry is pure and Node-tested; the drawing part is a port of the app's PluginView.Starmap:
// the viewBox is the view, drag pans, the wheel zooms around the cursor through a NON-passive listener
// (React's and the browser's defaults are passive), and point radii scale with the view so they keep
// their screen size.
"use strict";

const COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const DEFAULT_BODY_COLOR = "#8899aa";
const ORBIT_WIDTH = 900;
const ORBIT_HEIGHT = 420;
const MAX_BODIES = 24;                 // the app's views._orbit limit
const MAX_LABELLED = 60;
const MIN_VIEW = 10;
const MAX_FIND_HITS = 8;

// --------------------------------------------------------------------------- orbit

function bodyColor(value) {
  return typeof value === "string" && COLOR_RE.test(value) ? value : DEFAULT_BODY_COLOR;
}

function clampSize(value) {
  const size = Number(value);
  return Number.isFinite(size) ? Math.min(3, Math.max(0.3, size)) : 1;
}

function orbitLayout(section) {
  const bodies = ((section && section.bodies) || []).slice(0, MAX_BODIES);
  const step = (ORBIT_WIDTH - 140) / Math.max(1, bodies.length);
  const center = (section && section.center) || {};
  return {
    width: ORBIT_WIDTH,
    height: ORBIT_HEIGHT,
    center: { cx: 60, cy: ORBIT_HEIGHT / 2, label: center.label, sublabel: center.sublabel,
              items: center.items, badges: center.badges },
    bodies: bodies.map((body, i) => ({
      cx: 120 + i * step,
      cy: ORBIT_HEIGHT / 2 + (i % 2 === 0 ? -1 : 1) * (60 + (i % 3) * 28),
      r: 10 * clampSize(body.size),
      color: bodyColor(body.color),
      ring: Boolean(body.ring),
      label: body.label,
      sublabel: body.sublabel,
      items: body.items,
      badges: body.badges,
    })),
  };
}

// --------------------------------------------------------------------------- starmap geometry

function axes(mode) {
  return mode === "side" ? ["x", "y", -1] : ["x", "z", 1];
}

function starmapProject(view, point, mode) {
  const parts = axes(mode);
  const ax = parts[0], ay = parts[1], sign = parts[2];
  return {
    sx: (Number(point[ax]) - (view.cx - view.w / 2)) / view.w,
    sy: (sign * Number(point[ay]) - (view.cy - view.h / 2)) / view.h,
  };
}

function starmapFit(points, mode) {
  const parts = axes(mode);
  const ax = parts[0], ay = parts[1], sign = parts[2];
  if (!points || !points.length) return { cx: 0, cy: 0, w: MIN_VIEW * 10, h: MIN_VIEW * 10 };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const point of points) {
    const x = Number(point[ax]);
    const y = sign * Number(point[ay]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  if (!Number.isFinite(minX)) return { cx: 0, cy: 0, w: MIN_VIEW * 10, h: MIN_VIEW * 10 };
  const w = Math.max((maxX - minX) * 1.1, MIN_VIEW);
  const h = Math.max((maxY - minY) * 1.1, MIN_VIEW);
  return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, w: w, h: h };
}

function starmapZoom(view, cursor, factor) {
  // `cursor` is in world units; the point under it must stay under it.
  const w = view.w * factor;
  const h = view.h * factor;
  return {
    cx: cursor.x - (cursor.x - view.cx) * factor,
    cy: cursor.y - (cursor.y - view.cy) * factor,
    w: w,
    h: h,
  };
}

function starmapGridStep(width) {
  const raw = width / 6;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalised = raw / magnitude;
  const factor = normalised >= 5 ? 5 : (normalised >= 2 ? 2 : 1);
  return Number((factor * magnitude).toPrecision(12));
}

function starmapFind(points, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return [];
  const starts = [];
  const contains = [];
  for (const point of points || []) {
    const label = String(point.label || "").toLowerCase();
    const sub = String(point.sublabel || "").toLowerCase();
    if (label.startsWith(needle)) starts.push(point);
    else if (label.includes(needle) || sub.includes(needle)) contains.push(point);
  }
  return starts.concat(contains).slice(0, MAX_FIND_HITS);
}

// --------------------------------------------------------------------------- drawing

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(doc, tag, attrs) {
  const node = doc.createElementNS ? doc.createElementNS(SVG_NS, tag) : doc.createElement(tag);
  for (const name of Object.keys(attrs || {})) {
    if (attrs[name] !== undefined && attrs[name] !== null) node.setAttribute(name, String(attrs[name]));
  }
  return node;
}

function details(doc, body, api) {
  const box = api.el(doc, "div", "stc-point-details");
  box.appendChild(api.el(doc, "strong", null, body.label || ""));
  if (body.sublabel) box.appendChild(api.el(doc, "div", "stc-muted", body.sublabel));
  const list = api.el(doc, "dl", "stc-kv");
  for (const item of body.items || []) {
    list.appendChild(api.el(doc, "dt", null, item.label || ""));
    const value = api.el(doc, "dd", null);
    api.appendCell(doc, value, item.value);
    list.appendChild(value);
  }
  box.appendChild(list);
  const badges = api.el(doc, "div", "stc-badges");
  for (const badge of body.badges || []) {
    api.appendCell(doc, badges, badge);
  }
  box.appendChild(badges);
  return box;
}

function orbit(doc, section, api) {
  const layout = orbitLayout(section);
  const box = api.el(doc, "div", "stc-orbit");
  const canvas = svg(doc, "svg", { viewBox: "0 0 " + layout.width + " " + layout.height,
                                   role: "img", "aria-label": section.title || "System map" });
  canvas.appendChild(svg(doc, "circle", { cx: layout.center.cx, cy: layout.center.cy, r: 26,
                                          fill: "#f2c75c" }));
  const star = svg(doc, "text", { x: layout.center.cx, y: layout.center.cy + 46, fill: "#dfe5ec",
                                  "font-size": 14, "text-anchor": "middle" });
  star.textContent = layout.center.label || "";
  canvas.appendChild(star);
  const panel = api.el(doc, "div", null);
  for (const body of layout.bodies) {
    canvas.appendChild(orbitBody(doc, body, layout, panel, api));
  }
  box.appendChild(canvas);
  box.appendChild(panel);
  return box;
}

function orbitBody(doc, body, layout, panel, api) {
  const group = svg(doc, "g", { role: "button", tabindex: "0", class: "stc-body" });
  group.appendChild(svg(doc, "line", { x1: layout.center.cx, y1: layout.center.cy, x2: body.cx,
                                       y2: body.cy, stroke: "#2a323d" }));
  if (body.ring) {
    group.appendChild(svg(doc, "ellipse", { cx: body.cx, cy: body.cy, rx: body.r * 1.9, ry: body.r * 0.6,
                                            fill: "none", stroke: body.color }));
  }
  group.appendChild(svg(doc, "circle", { cx: body.cx, cy: body.cy, r: body.r, fill: body.color }));
  const label = svg(doc, "text", { x: body.cx, y: body.cy - body.r - 8, fill: "#dfe5ec",
                                   "font-size": 12, "text-anchor": "middle" });
  label.textContent = body.label || "";
  group.appendChild(label);
  const title = svg(doc, "title", {});
  title.textContent = [body.label, body.sublabel].filter(Boolean).join(" - ");
  group.appendChild(title);
  if (group.addEventListener) {
    group.addEventListener("click", () => {
      panel.textContent = "";
      panel.appendChild(details(doc, body, api));
    });
  }
  return group;
}

function starmap(doc, section, api) {
  const box = api.el(doc, "div", "stc-starmap");
  const points = (section.points || []).filter((p) => Number.isFinite(Number(p.x)));
  const state = { mode: "top", view: section.bounds
    ? starmapFit([section.bounds.min, section.bounds.max], "top")
    : starmapFit(points, "top"), selected: section.selected_key || null };
  const canvas = svg(doc, "svg", { role: "img", "aria-label": section.title || "Galaxy map" });
  const panel = api.el(doc, "div", null);
  box.appendChild(starmapControls(doc, section, state, () => redraw(), api));
  box.appendChild(canvas);
  box.appendChild(panel);

  function redraw() {
    drawStarmapInto(doc, canvas, panel, section, points, state, api);
  }

  if (canvas.addEventListener) wireStarmap(canvas, state, points, redraw);
  redraw();
  return box;
}

function starmapControls(doc, section, state, redraw, api) {
  const bar = api.el(doc, "div", "stc-starmap-controls");
  const addButton = (text, hint, onClick) => {
    const button = api.el(doc, "button", null, text);
    button.setAttribute("type", "button");
    button.setAttribute("title", hint);
    if (button.addEventListener) button.addEventListener("click", onClick);
    bar.appendChild(button);
    return button;
  };
  addButton("Top", "Look at the galaxy from above (x/z)", () => {
    state.mode = "top";
    redraw();
  });
  addButton("Side", "Look at the galaxy from the side (x/-y)", () => {
    state.mode = "side";
    redraw();
  });
  addButton("Fit", "Show every point", () => {
    state.view = starmapFit(section.points || [], state.mode);
    redraw();
  });
  const you = (section.points || []).filter((p) => p.marker === "current")[0];
  if (you) {
    addButton("You", "Centre on where you are", () => {
      state.selected = you.key;
      state.view = centerOn(state.view, you, state.mode);
      redraw();
    });
  }
  return bar;
}

function centerOn(view, point, mode) {
  const parts = axes(mode);
  const width = Math.min(view.w, 40);
  return { cx: Number(point[parts[0]]), cy: parts[2] * Number(point[parts[1]]),
           w: width, h: width * (view.h / view.w) };
}

function drawStarmapInto(doc, canvas, panel, section, points, state, api) {
  const view = state.view;
  canvas.setAttribute("viewBox", [view.cx - view.w / 2, view.cy - view.h / 2, view.w, view.h].join(" "));
  while (canvas.firstChild) canvas.removeChild(canvas.firstChild);
  const step = starmapGridStep(view.w);
  for (let x = Math.ceil((view.cx - view.w / 2) / step) * step; x < view.cx + view.w / 2; x += step) {
    canvas.appendChild(svg(doc, "line", { x1: x, y1: view.cy - view.h / 2, x2: x,
                                          y2: view.cy + view.h / 2, stroke: "#18202a",
                                          "stroke-width": view.w / 1200 }));
  }
  for (const line of (section.lines || []).slice(0, 50)) {
    canvas.appendChild(starmapLine(doc, line, state.mode));
  }
  const radius = view.w / 180;
  const labelled = points.length <= MAX_LABELLED;
  for (const point of points) {
    canvas.appendChild(starmapPoint(doc, point, state, radius, labelled, panel, section, api));
  }
}

function starmapLine(doc, line, mode) {
  const parts = axes(mode);
  const pairs = (line.points || []).map((p) => Number(p[parts[0]]) + "," + parts[2] * Number(p[parts[1]]));
  return svg(doc, "polyline", { points: pairs.join(" "), fill: "none",
                                stroke: COLOR_RE.test(line.color || "") ? line.color : "#44526b",
                                "stroke-width": 0.4 });
}

function starmapPoint(doc, point, state, radius, labelled, panel, section, api) {
  const parts = axes(state.mode);
  const cx = Number(point[parts[0]]);
  const cy = parts[2] * Number(point[parts[1]]);
  const group = svg(doc, "g", { role: "button", tabindex: "0" });
  group.appendChild(svg(doc, "circle", {
    cx: cx, cy: cy, r: radius * clampSize(point.size),
    fill: bodyColor(point.color),
    stroke: point.key === state.selected ? "#d9a13b" : null,
    "stroke-width": point.key === state.selected ? radius / 2 : null,
  }));
  if (labelled) {
    const text = svg(doc, "text", { x: cx + radius * 2, y: cy, fill: "#94a3b4",
                                    "font-size": radius * 3 });
    text.textContent = point.label || "";
    group.appendChild(text);
  }
  const title = svg(doc, "title", {});
  title.textContent = [point.label, point.sublabel].filter(Boolean).join(" - ");
  group.appendChild(title);
  if (group.addEventListener) {
    group.addEventListener("click", () => {
      state.selected = point.key;
      panel.textContent = "";
      const box = details(doc, point, api);
      if (section.action) {
        const open = api.el(doc, "button", null, section.action_label || "Open");
        open.setAttribute("type", "button");
        open.setAttribute("title", "Run " + (section.action_label || "Open") + " for this point");
        open.addEventListener("click", () => api.onAction(section.action, { key: point.key }));
        box.appendChild(open);
      }
      panel.appendChild(box);
    });
    group.addEventListener("dblclick", () => {
      if (section.action) api.onAction(section.action, { key: point.key });
    });
  }
  return group;
}

function wireStarmap(canvas, state, points, redraw) {
  let dragging = null;
  canvas.addEventListener("pointerdown", (event) => {
    dragging = { x: event.clientX, y: event.clientY, view: state.view };
    if (canvas.setPointerCapture) canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const rect = canvas.getBoundingClientRect();
    const dx = (event.clientX - dragging.x) / rect.width * dragging.view.w;
    const dy = (event.clientY - dragging.y) / rect.height * dragging.view.h;
    state.view = { cx: dragging.view.cx - dx, cy: dragging.view.cy - dy,
                   w: dragging.view.w, h: dragging.view.h };
    redraw();
  });
  canvas.addEventListener("pointerup", () => { dragging = null; });
  // Non-passive: a passive listener cannot preventDefault, so the page would scroll instead of zoom.
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const cursor = {
      x: state.view.cx - state.view.w / 2 + (event.clientX - rect.left) / rect.width * state.view.w,
      y: state.view.cy - state.view.h / 2 + (event.clientY - rect.top) / rect.height * state.view.h,
    };
    state.view = starmapZoom(state.view, cursor, event.deltaY > 0 ? 1.2 : 1 / 1.2);
    redraw();
  }, { passive: false });
}

const starmapExported = {
  orbit, starmap, orbitLayout, bodyColor, clampSize, axes, starmapProject, starmapFit, starmapZoom,
  starmapGridStep, starmapFind, centerOn,
  DEFAULT_BODY_COLOR, ORBIT_WIDTH, ORBIT_HEIGHT, MAX_BODIES, MAX_LABELLED,
};
if (typeof module !== "undefined" && module.exports) module.exports = starmapExported;
if (typeof window !== "undefined") window.Starmap = starmapExported;
