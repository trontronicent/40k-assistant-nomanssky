// Renders the connector's declarative view sections for the standalone page.
//
// Plugin text is only ever set through textContent - never innerHTML (the app's PluginView is guarded
// the same way). The pure parts (cells, sorting, tab paths, form values) are exported so Node can test
// them without a browser.
//
// Every section type listed in standalone/context.SECTION_TYPES must have a builder here;
// tests/test_host_contract.py compares the two lists.
"use strict";

const ICON_NAME_RE = /^[a-z0-9][a-z0-9._-]{0,119}\.png$/;
const NOWRAP_CHARS = 30;
const EMPTY_TEXTS = ["–", "-", ""];

// --------------------------------------------------------------------------- cells

function cellText(cell) {
  if (cell === null || cell === undefined) return "–";
  if (typeof cell === "object") return cell.text === undefined || cell.text === null ? "–" : String(cell.text);
  return String(cell);
}

function cellIcon(cell) {
  if (!cell || typeof cell !== "object" || typeof cell.icon !== "string") return null;
  if (!ICON_NAME_RE.test(cell.icon)) return null;
  return "/api/assets/" + cell.icon;
}

function cellHint(cell) {
  if (!cell || typeof cell !== "object") return null;
  const hint = cell.hint;
  return typeof hint === "string" && hint.trim() ? hint.trim().slice(0, 1200) : null;
}

// --------------------------------------------------------------------------- sorting

function sortKey(cell) {
  if (cell && typeof cell === "object" && typeof cell.sort === "number" && Number.isFinite(cell.sort)) {
    return cell.sort;
  }
  const text = cellText(cell);
  if (EMPTY_TEXTS.indexOf(text) >= 0) return null;
  const numeric = text.replace(/['  ,\s]/g, "").replace(/%$/, "");
  if (/^-?\d+(\.\d+)?$/.test(numeric)) return Number(numeric);
  return text;
}

function sortRows(rows, column, direction) {
  const indices = rows.map((_, i) => i);
  const sign = direction === "desc" ? -1 : 1;
  indices.sort((a, b) => {
    const ka = sortKey(rows[a][column]);
    const kb = sortKey(rows[b][column]);
    if (ka === null && kb === null) return a - b;
    if (ka === null) return 1;                  // empty cells last in both directions
    if (kb === null) return -1;
    if (typeof ka === "number" && typeof kb === "number") return sign * (ka - kb) || a - b;
    return sign * String(ka).localeCompare(String(kb), undefined, { numeric: true, sensitivity: "base" })
      || a - b;
  });
  return indices;
}

function nextSort(current, column) {
  // asc -> desc -> the plugin's own order, per column (the app's pluginModel.nextSort).
  if (!current || current.column !== column) return { column: column, direction: "asc" };
  if (current.direction === "asc") return { column: column, direction: "desc" };
  return null;
}

// --------------------------------------------------------------------------- tabs

function tabPath(view, sectionId) {
  const walk = (sections, path) => {
    for (const section of sections || []) {
      if (section.id === sectionId) return path;
      if (section.type === "tabs") {
        for (const tab of section.tabs || []) {
          const found = walk(tab.sections, path.concat([tab.id]));
          if (found) return found;
        }
      }
    }
    return null;
  };
  return walk(view && view.sections, []);
}

// --------------------------------------------------------------------------- form values
// Kept per form id, so the 5 s view poll cannot wipe what the user is typing. A field adopts the
// plugin's value only when that value itself changed (the app's useFormValues rule).

const formState = new Map();

function setFormValue(formId, fieldId, value) {
  const entry = formState.get(formId) || { values: {}, seen: {} };
  entry.values[fieldId] = value;
  formState.set(formId, entry);
}

function formValues(formId, fields) {
  const entry = formState.get(formId) || { values: {}, seen: {} };
  for (const field of fields || []) {
    const fromPlugin = field.value === undefined ? "" : field.value;
    const firstSight = !Object.prototype.hasOwnProperty.call(entry.seen, field.id);
    if (firstSight) {
      // Keep anything the user typed before this field was first rendered.
      if (entry.values[field.id] === undefined) entry.values[field.id] = fromPlugin;
    } else if (entry.seen[field.id] !== fromPlugin) {
      entry.values[field.id] = fromPlugin;            // the plugin changed it, so follow
    }
    entry.seen[field.id] = fromPlugin;
  }
  formState.set(formId, entry);
  return entry.values;
}

function resetForms() {
  formState.clear();
}

// --------------------------------------------------------------------------- node factory
// The browser passes its document; Node gets a minimal stand-in so the renderer stays testable.

function nodeFactory(doc) {
  if (doc) return doc;
  const make = (tag) => ({
    tag: tag, children: [], attrs: {}, text: "", style: {},
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    addEventListener() {},
    classList: { add() {}, remove() {}, toggle() {} },
    set textContent(value) { this.text = value === null || value === undefined ? "" : String(value); },
    get textContent() { return this.text; },
  });
  return { createElement: make, createTextNode: (t) => ({ tag: "#text", text: String(t), attrs: {}, children: [] }) };
}

function el(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.setAttribute("class", className);
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const VOID_TAGS = ["img", "input", "br", "hr"];

function toHtml(node) {
  if (!node) return "";
  if (node.tag === "#text") return escapeHtml(node.text);
  const attrs = Object.keys(node.attrs).map((k) => " " + k + '="' + escapeHtml(node.attrs[k]) + '"').join("");
  if (VOID_TAGS.indexOf(node.tag) >= 0) return "<" + node.tag + attrs + ">";
  const inner = node.text ? escapeHtml(node.text) : (node.children || []).map(toHtml).join("");
  return "<" + node.tag + attrs + ">" + inner + "</" + node.tag + ">";
}

// --------------------------------------------------------------------------- builders

function buildNotice(doc, section) {
  const box = el(doc, "div", "stc-notice stc-notice-" + (section.level || "info"));
  if (section.title) box.appendChild(el(doc, "strong", null, section.title));
  box.appendChild(el(doc, "p", null, section.text || ""));
  return box;
}

function buildStats(doc, section) {
  const box = el(doc, "div", "stc-stats");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  const grid = el(doc, "div", "stc-stats-grid");
  for (const item of section.items || []) {
    const cell = el(doc, "div", "stc-stat");
    cell.appendChild(el(doc, "span", "stc-stat-value", cellText(item.value)));
    cell.appendChild(el(doc, "span", "stc-stat-label", item.label || ""));
    grid.appendChild(cell);
  }
  box.appendChild(grid);
  return box;
}

function buildKv(doc, section) {
  const box = el(doc, "div", "stc-kv-box");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  const list = el(doc, "dl", "stc-kv");
  for (const item of section.items || []) {
    list.appendChild(el(doc, "dt", null, item.label || ""));
    const value = el(doc, "dd", null);
    appendCell(doc, value, item.value);
    list.appendChild(value);
  }
  box.appendChild(list);
  return box;
}

function appendCell(doc, host, cell) {
  const url = cellIcon(cell);
  if (url) {
    const img = doc.createElement("img");
    img.setAttribute("src", url);
    img.setAttribute("alt", "");
    img.setAttribute("class", "stc-icon");
    host.appendChild(img);
  }
  const text = cellText(cell);
  const span = el(doc, "span", text.length <= NOWRAP_CHARS ? "stc-nowrap" : null, text);
  const hint = cellHint(cell);
  if (hint) {
    span.setAttribute("title", hint);
    span.setAttribute("class", (text.length <= NOWRAP_CHARS ? "stc-nowrap " : "") + "stc-hinted");
  }
  host.appendChild(span);
  return host;
}

function buildTable(doc, section, api) {
  const box = el(doc, "div", "stc-table-box");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  const table = el(doc, "table", "stc-table");
  const head = el(doc, "tr", null);
  (section.columns || []).forEach((column, index) => {
    const th = el(doc, "th", null);
    const button = el(doc, "button", "stc-sort", String(column));
    button.setAttribute("type", "button");
    button.setAttribute("title", "Sort by " + column);
    button.addEventListener("click", () => api.onSort(section, index));
    th.appendChild(button);
    head.appendChild(th);
  });
  table.appendChild(head);
  const order = api.sortFor(section);
  const rows = section.rows || [];
  const indices = order ? sortRows(rows, order.column, order.direction) : rows.map((_, i) => i);
  for (const index of indices) {
    table.appendChild(buildRow(doc, section, index, api));
  }
  box.appendChild(table);
  return box;
}

function buildRow(doc, section, index, api) {
  const row = el(doc, "tr", null);
  const keys = section.row_keys || [];
  const key = keys[index] === undefined ? null : keys[index];
  (section.rows[index] || []).forEach((cell, column) => {
    const td = el(doc, "td", null);
    appendCell(doc, td, cell);
    if (column === 0 && section.row_hint && !cellHint(cell)) td.setAttribute("title", section.row_hint);
    row.appendChild(td);
  });
  if (section.row_action && key !== null) {
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("class", "stc-clickable");
    row.addEventListener("click", () => api.onAction(section.row_action, { key: key }));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") api.onAction(section.row_action, { key: key });
    });
  }
  if (section.selected_key && key === section.selected_key) row.setAttribute("data-selected", "1");
  return row;
}

function buildList(doc, section) {
  const box = el(doc, "div", "stc-list-box");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  const list = el(doc, "ul", "stc-list");
  for (const item of section.items || []) {
    const li = el(doc, "li", null);
    appendCell(doc, li, item);
    list.appendChild(li);
  }
  box.appendChild(list);
  return box;
}

function buildText(doc, section) {
  const box = el(doc, "div", "stc-text-box");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  box.appendChild(el(doc, "p", "stc-text", section.text || ""));
  return box;
}

function buildForm(doc, section, api) {
  const box = el(doc, "form", "stc-form");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  const formId = section.id || section.action || "form";
  const values = formValues(formId, section.fields);
  for (const field of section.fields || []) {
    box.appendChild(buildField(doc, formId, field, values));
  }
  const submit = el(doc, "button", "stc-submit", section.submit_label || "Submit");
  submit.setAttribute("type", "submit");
  submit.setAttribute("title", section.submit_label || "Submit this form");
  box.appendChild(submit);
  box.addEventListener("submit", (event) => {
    if (event && event.preventDefault) event.preventDefault();
    api.onAction(section.action, formValues(formId, section.fields), { quiet: false });
  });
  return box;
}

function buildField(doc, formId, field, values) {
  const wrap = el(doc, "label", "stc-field");
  wrap.appendChild(el(doc, "span", "stc-field-label", field.label || field.id));
  const input = doc.createElement(field.type === "select" ? "select" : "input");
  input.setAttribute("name", field.id);
  input.setAttribute("title", field.hint || field.label || field.id);
  if (field.type === "select") {
    for (const option of field.options || []) {
      const node = el(doc, "option", null, String(option));
      node.setAttribute("value", String(option));
      input.appendChild(node);
    }
    input.setAttribute("value", String(values[field.id] === undefined ? "" : values[field.id]));
  } else {
    input.setAttribute("type", field.type === "number" ? "number" : (field.type === "checkbox" ? "checkbox" : "text"));
    if (field.placeholder) input.setAttribute("placeholder", field.placeholder);
    if (field.max_length) input.setAttribute("maxlength", field.max_length);
    if (field.min !== undefined) input.setAttribute("min", field.min);
    if (field.max !== undefined) input.setAttribute("max", field.max);
    if (field.step !== undefined) input.setAttribute("step", field.step);
    input.setAttribute("value", String(values[field.id] === undefined ? "" : values[field.id]));
  }
  input.addEventListener("input", (event) => setFormValue(formId, field.id,
    field.type === "checkbox" ? Boolean(event.target.checked) : event.target.value));
  input.addEventListener("change", (event) => setFormValue(formId, field.id,
    field.type === "checkbox" ? Boolean(event.target.checked) : event.target.value));
  wrap.appendChild(input);
  if (field.hint) wrap.appendChild(el(doc, "small", "stc-field-hint", field.hint));
  return wrap;
}

function buildTimers(doc, section, api) {
  const box = el(doc, "div", "stc-timers");
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  for (const item of section.items || []) {
    const row = el(doc, "div", "stc-timer");
    row.setAttribute("data-timer-key", String(item.key || ""));
    row.setAttribute("data-ends-at", String(item.ends_at || 0));
    if (item.started_at) row.setAttribute("data-started-at", String(item.started_at));
    row.appendChild(el(doc, "span", "stc-timer-label", item.label || ""));
    row.appendChild(el(doc, "span", "stc-timer-remaining", api.formatRemaining(item)));
    if (item.detail) row.appendChild(el(doc, "small", "stc-timer-detail", item.detail));
    const bar = el(doc, "div", "stc-timer-bar");
    bar.appendChild(el(doc, "div", "stc-timer-fill"));
    row.appendChild(bar);
    box.appendChild(row);
  }
  return box;
}

function buildTabs(doc, section, api) {
  const box = el(doc, "div", "stc-tabs");
  const strip = el(doc, "div", "stc-tabstrip");
  const tabs = section.tabs || [];
  const selected = api.selectedTab(section, tabs);
  for (const tab of tabs) {
    const button = el(doc, "button", "stc-tab" + (tab.id === selected ? " stc-tab-on" : ""), tab.label || tab.id);
    button.setAttribute("type", "button");
    button.setAttribute("title", "Show " + (tab.label || tab.id));
    if (tab.badge !== undefined && tab.badge !== null) {
      button.appendChild(el(doc, "span", "stc-badge", String(tab.badge)));
    }
    button.addEventListener("click", () => api.onSelectTab(section, tab.id));
    strip.appendChild(button);
  }
  box.appendChild(strip);
  const current = tabs.filter((tab) => tab.id === selected)[0] || tabs[0];
  if (current) {
    const panel = el(doc, "div", "stc-tabpanel");
    panel.setAttribute("data-tab", String(current.id));
    const inner = renderSections({ sections: current.sections }, api);
    panel.appendChild(inner.node);
    box.appendChild(panel);
  }
  return box;
}

function buildPlaceholder(doc, section) {
  // The orbit/starmap drawers live in starmap.js; without them the section still occupies its place.
  const box = el(doc, "div", "stc-" + section.type);
  if (section.title) box.appendChild(el(doc, "h3", null, section.title));
  return box;
}

const BUILDERS = {
  notice: buildNotice,
  stats: buildStats,
  kv: buildKv,
  table: buildTable,
  list: buildList,
  text: buildText,
  form: buildForm,
  timers: buildTimers,
  tabs: buildTabs,
  orbit: (doc, section, api) => api.orbit(doc, section, api),
  starmap: (doc, section, api) => api.starmap(doc, section, api),
};

function defaultApi(options) {
  const api = Object.assign({
    document: null,
    orbit: buildPlaceholder,
    starmap: buildPlaceholder,
    onAction: () => {},
    onSort: () => {},
    onSelectTab: () => {},
    sortFor: () => null,
    selectedTab: (section, tabs) => (tabs[0] ? tabs[0].id : null),
    formatRemaining: (item) => String(item.ends_at || ""),
  }, options || {});
  return api;
}

function renderSections(view, options) {
  const api = defaultApi(options);
  const doc = nodeFactory(api.document);
  const root = doc.createElement("div");
  root.setAttribute("class", "stc-sections");
  const types = [];
  for (const section of (view && view.sections) || []) {
    const builder = BUILDERS[section.type];
    if (!builder) continue;                    // an unknown type is skipped, never guessed at
    types.push(section.type);
    const node = builder(doc, section, api);
    if (section.id) node.setAttribute("data-section-id", section.id);
    root.appendChild(node);
  }
  return { node: root, children: root.children || [], types: types, html: toHtml(root) };
}

const exported = {
  renderSections, cellText, cellIcon, cellHint, sortKey, sortRows, nextSort, tabPath,
  formValues, setFormValue, resetForms, escapeHtml, toHtml, nodeFactory, el, appendCell, BUILDERS,
};
if (typeof module !== "undefined" && module.exports) module.exports = exported;
if (typeof window !== "undefined") window.Sections = exported;
