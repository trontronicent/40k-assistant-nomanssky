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
  // Text first, then the children, as a real element behaves: `el()` sets textContent and a builder may
  // then append to it (a sort button is its label plus the arrow). Taking the text alone hid the arrow
  // from the tests while the browser drew it.
  const inner = escapeHtml(node.text || "") + (node.children || []).map(toHtml).join("");
  return "<" + node.tag + attrs + ">" + inner + "</" + node.tag + ">";
}

// --------------------------------------------------------------------------- builders

function buildNotice(doc, section) {
  // Not carded, as in the app: a bordered line in its level's colour, the sign drawn by the CSS.
  const box = el(doc, "div", "stc-notice stc-notice-" + (section.level || "info"));
  const text = el(doc, "div", "stc-notice-text");
  if (section.title) text.appendChild(el(doc, "strong", null, section.title));
  text.appendChild(el(doc, "p", null, section.text || ""));
  box.appendChild(text);
  return box;
}

function buildStats(doc, section) {
  const box = el(doc, "div", "stc-stats");
  const grid = el(doc, "div", "stc-stats-grid");
  for (const item of section.items || []) {
    const cell = el(doc, "div", "stc-stat");
    // The app shows a stat's own explanation as a tooltip; here it is the title, as for a cell hint.
    if (item.hint) cell.setAttribute("title", item.hint);
    cell.appendChild(el(doc, "span", "stc-stat-label", item.label || ""));
    cell.appendChild(el(doc, "span", "stc-stat-value", cellText(item.value)));
    grid.appendChild(cell);
  }
  box.appendChild(grid);
  return box;
}

function buildKv(doc, section) {
  const box = el(doc, "div", "stc-kv-box");
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

/** True when this cell is short enough never to wrap - the app's `pluginModel.cellNoWrap`.
 *
 *  In the app the answer lands on the `<td>` (its `white-space` and its 20ch minimum), not on the text
 *  inside it, so `appendCell` leaves this to `buildRow` and a key/value or list entry wraps freely in
 *  both hosts, as it does in the app. */
function cellNoWrap(cell) {
  const raw = cell && typeof cell === "object" ? cell.text : cell;
  return typeof raw !== "string" || raw.length <= NOWRAP_CHARS;
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
  const hint = cellHint(cell);
  const span = el(doc, "span", hint ? "stc-hinted" : null, cellText(cell));
  if (hint) span.setAttribute("title", hint);
  host.appendChild(span);
  return host;
}

// The arrows the app draws in a column header (lucide ChevronUp/ChevronDown/ChevronsUpDown); a glyph each,
// because the standalone install ships no icon set.
const SORT_MARKS = { asc: "↑", desc: "↓", none: "⇅" };

function sortTitle(column, direction) {
  // The app's wording, so the same header explains itself the same way in both hosts.
  if (direction === "asc") return "Sort by " + column + ", descending";
  if (direction === "desc") return "Show the rows in their original order";
  return "Sort by " + column + ", ascending";
}

function buildHead(doc, section, api) {
  const order = api.sortFor(section);
  const head = el(doc, "tr", null);
  (section.columns || []).forEach((column, index) => {
    const direction = order && order.column === index ? order.direction : null;
    const th = el(doc, "th", direction ? "stc-sorted" : null);
    th.setAttribute("aria-sort", direction === "asc" ? "ascending"
      : direction === "desc" ? "descending" : "none");
    const button = el(doc, "button", "stc-sort", String(column));
    button.setAttribute("type", "button");
    button.setAttribute("title", sortTitle(column, direction));
    const mark = el(doc, "span", "stc-sort-mark" + (direction ? "" : " stc-sort-mark-off"),
                    SORT_MARKS[direction || "none"]);
    mark.setAttribute("aria-hidden", "true");
    button.appendChild(mark);
    button.addEventListener("click", () => api.onSort(section, index));
    th.appendChild(button);
    head.appendChild(th);
  });
  return head;
}

function rowOrder(section, api) {
  const order = api.sortFor(section);
  const rows = section.rows || [];
  return order ? sortRows(rows, order.column, order.direction) : rows.map((_, i) => i);
}

function truncatedNote(doc, section) {
  // The app's line under a table the connector cut short, so a missing row is never silent.
  if (!section.truncated) return null;
  return el(doc, "div", "stc-truncated",
            "Only the first " + (section.rows || []).length + " rows are shown.");
}

function buildTableBox(doc, section, api) {
  const box = el(doc, "div", "stc-table-box");
  const table = el(doc, "table", "stc-table");
  const thead = el(doc, "thead", null);
  thead.appendChild(buildHead(doc, section, api));
  table.appendChild(thead);
  const body = el(doc, "tbody", null);
  for (const index of rowOrder(section, api)) {
    body.appendChild(buildRow(doc, section, index, api));
  }
  table.appendChild(body);
  box.appendChild(table);
  const note = truncatedNote(doc, section);
  if (note) box.appendChild(note);
  return box;
}

/** A table section: the hint above it, then the table or - on a narrow page - the cards.
 *
 *  The app decides between the two from the measured width (`pluginModel.tableAsCards`), which no builder
 *  can know while it builds; `measureTables` does that pass once the nodes are in the document and swaps
 *  this box's contents. `api.layout` forces one of them, as the app's `layout` prop does for tests. */
function buildTable(doc, section, api) {
  const outer = el(doc, "div", "stc-table-outer");
  if (!(section.rows || []).length) {
    outer.appendChild(el(doc, "div", "stc-muted", section.empty || "No entries."));
    return outer;
  }
  if (section.row_action && section.row_hint) {
    outer.appendChild(el(doc, "div", "stc-hint", section.row_hint));
  }
  const inner = el(doc, "div", "stc-table-inner");
  inner.appendChild(api.layout === "cards" ? buildCards(doc, section, api)
                                           : buildTableBox(doc, section, api));
  inner.setAttribute("data-layout", api.layout === "cards" ? "cards" : "table");
  outer.appendChild(inner);
  if (api.layout === "auto" && inner.ownerDocument) measured.set(inner, { section: section, api: api });
  return outer;
}

// --------------------------------------------------------------------------- cards (the phone layout)

const CARD_BREAKPOINT = 560;
const CARD_OVERFLOW_MAX = 1024;
const EMPTY_CELL = "–";

// What each table needed the last time it was shown as a table, kept per section id so switching to cards
// does not forget it (the app keeps it in the component's state for the same reason).
const neededWidths = new Map();
// Boxes whose layout `measureTables` may still change: node -> {section, api}.
const measured = new WeakMap();

/** True when a table `width` px wide with `columnCount` columns reads better as cards - the app's
 *  `pluginModel.tableAsCards`, including its measured thresholds, so neither host switches first. */
function tableAsCards(width, columnCount, needed) {
  const need = needed || 0;
  if (!(width > 0) || columnCount < 3) return false;
  if (width < CARD_BREAKPOINT) return true;
  if (need > width * 1.25) return true;
  return width < CARD_OVERFLOW_MAX && need > width * 1.1;
}

/** The label/value pairs of one card: every column after the first, empty cells left out (the app's
 *  `pluginModel.cardFields` - a "–" is noise in a card where it is a placeholder in a table). */
function cardFields(columns, row) {
  return (columns || []).slice(1)
    .map((label, i) => ({ label: label, column: i + 1, cell: (row || [])[i + 1] }))
    .filter((field) => cellText(field.cell) !== EMPTY_CELL);
}

function buildCardSort(doc, section, api) {
  // The phone layout's stand-in for the column headers: pick a column, then flip the direction.
  const order = api.sortFor(section);
  const bar = el(doc, "div", "stc-card-sort");
  const label = el(doc, "label", "stc-field");
  label.appendChild(el(doc, "span", "stc-field-label", "Sort by"));
  const select = doc.createElement("select");
  select.setAttribute("title", "Order the entries by one of the table's columns");
  const none = el(doc, "option", null, "The plugin's order");
  none.setAttribute("value", "");
  select.appendChild(none);
  (section.columns || []).forEach((column, index) => {
    const option = el(doc, "option", null, String(column));
    option.setAttribute("value", String(index));
    if (order && order.column === index) option.setAttribute("selected", "selected");
    select.appendChild(option);
  });
  select.addEventListener("change", (event) => api.setSort(section, event.target.value === ""
    ? null
    : { column: Number(event.target.value), direction: "asc" }));
  label.appendChild(select);
  bar.appendChild(label);
  if (order) bar.appendChild(buildDirectionButton(doc, section, api, order));
  return bar;
}

function buildDirectionButton(doc, section, api, order) {
  const asc = order.direction !== "desc";
  const button = el(doc, "button", "stc-card-dir", asc ? "↑ Asc" : "↓ Desc");
  button.setAttribute("type", "button");
  button.setAttribute("title", asc ? "Ascending - tap for descending" : "Descending - tap for ascending");
  button.addEventListener("click", () => api.setSort(section,
    { column: order.column, direction: asc ? "desc" : "asc" }));
  return button;
}

function buildCard(doc, section, index, api) {
  const row = (section.rows || [])[index] || [];
  const keys = section.row_keys || [];
  const key = keys[index] === undefined ? null : keys[index];
  const open = Boolean(section.row_action) && key !== null;
  const card = el(doc, "div", "stc-card" + (open ? " stc-clickable" : ""));
  const title = el(doc, "div", "stc-card-title");
  appendCell(doc, title, row[0]);
  if (open && section.row_hint && !cellHint(row[0])) title.setAttribute("title", section.row_hint);
  card.appendChild(title);
  const fields = cardFields(section.columns, row);
  if (fields.length) card.appendChild(buildCardFields(doc, fields));
  if (open) {
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.addEventListener("click", () => api.onAction(section.row_action, { key: key }));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") api.onAction(section.row_action, { key: key });
    });
  }
  if (section.row_menu && key !== null) {
    card.addEventListener("contextmenu", (event) => openRowMenu(doc, section, key, event, api));
  }
  if (section.selected_key && key === section.selected_key) card.setAttribute("data-selected", "1");
  return card;
}

function buildCardFields(doc, fields) {
  const list = el(doc, "dl", "stc-card-fields");
  for (const field of fields) {
    list.appendChild(el(doc, "dt", null, String(field.label)));
    const value = el(doc, "dd", null);
    appendCell(doc, value, field.cell);
    list.appendChild(value);
  }
  return list;
}

function buildCards(doc, section, api) {
  const box = el(doc, "div", "stc-cards-box");
  if ((section.rows || []).length > 1) box.appendChild(buildCardSort(doc, section, api));
  const list = el(doc, "div", "stc-cards");
  list.setAttribute("role", "list");
  for (const index of rowOrder(section, api)) {
    list.appendChild(buildCard(doc, section, index, api));
  }
  box.appendChild(list);
  const note = truncatedNote(doc, section);
  if (note) list.appendChild(note);
  return box;
}

/** How much room this table needs: what it measures now, else what it needed when it was last a table.
 *
 *  A box showing cards has no table to measure, so without the memory the page would find that the table
 *  fits, swap back, measure, swap to cards again - a flicker on every poll. Only a section with an id can
 *  be remembered: without that check every id-less table would share one entry and answer for the others.
 */
function neededFor(sectionId, measuredWidth) {
  const key = sectionId || null;
  if (!key) return measuredWidth;
  if (measuredWidth) neededWidths.set(key, measuredWidth);
  return neededWidths.get(key) || 0;
}

/** Decide table-or-cards for every table under `root` now that it has a width, and swap what differs.
 *
 *  Called after the page inserted the sections and again on a resize. A table that is shown keeps its
 *  measured `scrollWidth` in `neededWidths`, so a box that is already cards still knows how much room its
 *  table wanted - without that, switching to cards would make the page think the table fits and it would
 *  flip back and forth. */
function measureTables(root) {
  if (!root || !root.querySelectorAll) return;
  for (const inner of root.querySelectorAll(".stc-table-inner")) {
    const entry = measured.get(inner);
    if (!entry) continue;
    const table = inner.querySelector("table");
    const needed = neededFor(entry.section.id, table ? Math.round(table.scrollWidth) : 0);
    const width = Math.round(inner.getBoundingClientRect().width);
    const wanted = tableAsCards(width, (entry.section.columns || []).length, needed);
    const shown = inner.getAttribute("data-layout") === "cards";
    if (wanted === shown) continue;
    const doc = inner.ownerDocument;
    inner.textContent = "";
    inner.setAttribute("data-layout", wanted ? "cards" : "table");
    inner.appendChild(wanted ? buildCards(doc, entry.section, entry.api)
                             : buildTableBox(doc, entry.section, entry.api));
  }
}

function rowMenuItems(section) {
  // The app's `pluginModel.rowMenuItems`: only plain {id, label} entries reach the page.
  return (section.row_menu || [])
    .filter((item) => item && typeof item.id === "string")
    .map((item) => ({ id: item.id, label: item.label || item.id, description: item.description || null }));
}

function menuPosition(x, y, menu, viewport, margin) {
  // The app's `pluginModel.menuPosition`: a menu at the right or bottom edge flips back onto the page.
  const pad = margin === undefined ? 8 : margin;
  const left = x + menu.width + pad > viewport.width ? Math.max(pad, x - menu.width) : x;
  const top = y + menu.height + pad > viewport.height ? Math.max(pad, y - menu.height) : y;
  return { left: Math.round(left), top: Math.round(top) };
}

function openRowMenu(doc, section, key, event, api) {
  // The menu is appended to the body, not into the table: the table box scrolls and would clip it.
  if (!doc.body || !event.preventDefault) return;
  event.preventDefault();
  closeRowMenu();
  const items = rowMenuItems(section);
  if (!items.length || key === null || key === undefined) return;
  const box = el(doc, "div", "stc-row-menu");
  box.setAttribute("role", "menu");
  for (const item of items) {
    const button = el(doc, "button", "stc-row-menu-item", item.label);
    button.setAttribute("type", "button");
    button.setAttribute("role", "menuitem");
    button.setAttribute("title", item.description || item.label);
    button.addEventListener("click", () => {
      closeRowMenu();
      api.onAction(item.id, { key: key }, { quiet: false });
    });
    box.appendChild(button);
  }
  doc.body.appendChild(box);
  const rect = box.getBoundingClientRect ? box.getBoundingClientRect() : { width: 0, height: 0 };
  const at = menuPosition(event.clientX || 0, event.clientY || 0, { width: rect.width, height: rect.height },
                          { width: window.innerWidth, height: window.innerHeight });
  box.style.left = at.left + "px";
  box.style.top = at.top + "px";
  openMenu = box;
  // One listener each, removed with the menu: a click outside, a scroll or Escape closes it.
  setTimeout(() => {
    window.addEventListener("pointerdown", pointerCloses, true);
    window.addEventListener("scroll", closeRowMenu, true);
    window.addEventListener("keydown", escapeCloses);
  }, 0);
}

let openMenu = null;

function escapeCloses(event) {
  if (event.key === "Escape") closeRowMenu();
}

/** A pointer-down closes the menu - unless it landed on the menu itself.
 *
 *  This is a capture-phase listener, so it runs before the entry's own click handler. Closing here would
 *  remove the button from the document before the browser dispatches `click`, and the entry would never
 *  run: the menu opened, an entry did nothing, and nothing was logged. */
function pointerCloses(event) {
  if (openMenu && openMenu.contains && event && openMenu.contains(event.target)) return;
  closeRowMenu();
}

function closeRowMenu() {
  if (!openMenu) return;
  if (openMenu.parentNode) openMenu.parentNode.removeChild(openMenu);
  openMenu = null;
  window.removeEventListener("pointerdown", pointerCloses, true);
  window.removeEventListener("scroll", closeRowMenu, true);
  window.removeEventListener("keydown", escapeCloses);
}

function buildRow(doc, section, index, api) {
  const row = el(doc, "tr", null);
  const keys = section.row_keys || [];
  const key = keys[index] === undefined ? null : keys[index];
  (section.rows[index] || []).forEach((cell, column) => {
    // The app puts the no-wrap decision and the 20ch minimum on the cell, not on the text inside it.
    const td = el(doc, "td", cellNoWrap(cell) ? "stc-nowrap" : null);
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
  if (section.row_menu && key !== null) {
    row.addEventListener("contextmenu", (event) => openRowMenu(doc, section, key, event, api));
  }
  if (section.selected_key && key === section.selected_key) row.setAttribute("data-selected", "1");
  return row;
}

function buildList(doc, section) {
  const box = el(doc, "div", "stc-list-box");
  if (!(section.items || []).length) {
    box.appendChild(el(doc, "div", "stc-muted", section.empty || "No entries."));
    return box;
  }
  const list = el(doc, "ul", "stc-list");
  for (const item of section.items || []) {
    const li = el(doc, "li", null);
    appendCell(doc, li, item);
    list.appendChild(li);
  }
  box.appendChild(list);
  return box;
}

// --------------------------------------------------------------------------- clipboard

const COPY_FROM_CHARS = 200;

/** Put text on the clipboard; false when the browser refused it.
 *
 *  Two paths, because neither works everywhere. `navigator.clipboard` needs a secure context, and this
 *  page is often opened over a plain LAN address, where it does not exist at all. `execCommand` works
 *  there, but only while the click that asked for it still counts as user activation - so call this from
 *  a click handler, not after an awaited request. The Copy button on a text section is that reliable path.
 */
async function copyText(text) {
  if (typeof text !== "string" || !text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) {
    console.debug("the clipboard API refused, falling back to a textarea", err);
  }
  const area = document.createElement("textarea");
  try {
    area.value = text;
    area.setAttribute("readonly", "");
    // Off-screen but selectable: a hidden or undisplayed textarea cannot be selected at all.
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, text.length);
    return document.execCommand("copy");
  } catch (err) {
    console.warn("could not copy to the clipboard", err);
    return false;
  } finally {
    if (area.parentNode) document.body.removeChild(area);
  }
}

function buildText(doc, section) {
  const box = el(doc, "div", "stc-text-box");
  const text = section.text || "";
  // Data - several lines, and long enough not to be a sentence - gets a Copy button and a selectable
  // block; prose stays prose. On length alone, 13 explanations in the view became monospace blocks.
  if (text.length <= COPY_FROM_CHARS || !text.includes("\n")) {
    box.appendChild(el(doc, "p", "stc-text", text));
    return box;
  }
  const row = el(doc, "div", "stc-copy-row");
  const said = el(doc, "span", "stc-copy-said", "");
  const button = el(doc, "button", "stc-copy-button", "Copy");
  button.setAttribute("type", "button");
  button.setAttribute("title", "Copy this text to the clipboard");
  if (button.addEventListener) {
    button.addEventListener("click", async () => {
      said.textContent = (await copyText(text))
        ? "Copied."
        : "This browser refused the clipboard - select the text and press Ctrl+C.";
    });
  }
  row.appendChild(said);
  row.appendChild(button);
  box.appendChild(row);
  box.appendChild(el(doc, "pre", "stc-copy-block", text));
  return box;
}

function buildForm(doc, section, api) {
  const box = el(doc, "form", "stc-form");
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
    const current = String(values[field.id] === undefined ? "" : values[field.id]);
    for (const option of field.options || []) {
      const node = el(doc, "option", null, option.label);
      node.setAttribute("value", String(option.value));
      if (String(option.value) === current) node.setAttribute("selected", "selected");
      input.appendChild(node);
    }
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
  if (!(section.items || []).length) {
    box.appendChild(el(doc, "div", "stc-muted", section.empty || "No timers running."));
    return box;
  }
  for (const item of section.items || []) {
    box.appendChild(buildTimerRow(doc, item, api));
  }
  return box;
}

/** One timer, in the app's shape: what it is on the left, the countdown and when it ends on the right,
 *  and the progress bar across the bottom while it runs (TimersSection's TimerRow).
 *
 *  The app has a bell per timer, because its notifications are per timer and reach other devices. Here
 *  one page-wide switch under *Alerts* does that for every timer, so there is no bell to draw. */
function buildTimerRow(doc, item, api) {
  const row = el(doc, "div", "stc-timer");
  row.setAttribute("data-timer-key", String(item.key || ""));
  row.setAttribute("data-ends-at", String(item.ends_at || 0));
  if (item.started_at) row.setAttribute("data-started-at", String(item.started_at));
  const what = el(doc, "div", "stc-timer-what");
  what.appendChild(el(doc, "div", "stc-timer-label", item.label || ""));
  if (item.detail) what.appendChild(el(doc, "div", "stc-timer-detail", item.detail));
  row.appendChild(what);
  const when = el(doc, "div", "stc-timer-when");
  when.appendChild(el(doc, "div", "stc-timer-remaining", api.formatRemaining(item)));
  when.appendChild(el(doc, "div", "stc-timer-at", api.formatEndLabel(item)));
  row.appendChild(when);
  const bar = el(doc, "div", "stc-timer-bar");
  bar.appendChild(el(doc, "div", "stc-timer-fill"));
  row.appendChild(bar);
  return row;
}

function buildTabs(doc, section, api) {
  // Depth 0 is the underlined strip, deeper ones are bordered chips - the app's tabs and sub-tabs.
  const depth = api.depth || 0;
  const box = el(doc, "div", "stc-tabs");
  const strip = el(doc, "div", depth > 0 ? "stc-tabstrip stc-subtabs" : "stc-tabstrip");
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
    const inner = renderSections({ sections: current.sections }, Object.assign({}, api, { depth: depth + 1 }));
    panel.appendChild(inner.node);
    box.appendChild(panel);
  }
  return box;
}

// --------------------------------------------------------------------------- recipe diagrams

/** The asset URL of one diagram card's icon, or null: the connector names the file (`icon`), and the
 *  older chat path only knew the item's name, so a name -> file map may be passed instead. */
function recipeIconUrl(item, icons) {
  const file = (item && item.icon) || (icons && icons[item && item.name]);
  return file ? "/api/assets/" + file : null;
}

/** One card of a diagram: the icon box above "amount x name". */
function recipeCard(doc, item, icons) {
  const wrap = el(doc, "div", "recipe-item");
  const box = el(doc, "div", "box");
  const url = recipeIconUrl(item, icons);
  if (url) {
    const img = doc.createElement("img");
    img.setAttribute("src", url);
    img.setAttribute("alt", "");
    box.appendChild(img);
  }
  wrap.appendChild(box);
  wrap.appendChild(el(doc, "small", null, (item.amount || 1) + " x " + (item.name || "")));
  return wrap;
}

/** One recipe as a diagram: ingredient cards, "+" between them, the arrow, the result, the station.
 *
 *  The chat (chat.js) and the `recipes` sections of the page draw recipes with this one builder, so a
 *  recipe looks the same wherever it appears - the app does the same with its RecipeDiagramView. */
function recipeRow(doc, recipe, icons) {
  const row = el(doc, "div", "recipe");
  (recipe.ingredients || []).forEach((item, index) => {
    if (index) row.appendChild(el(doc, "span", null, "+"));
    row.appendChild(recipeCard(doc, item, icons));
  });
  row.appendChild(el(doc, "span", null, "→"));
  if (recipe.result) row.appendChild(recipeCard(doc, recipe.result, icons));
  if (recipe.station) row.appendChild(el(doc, "small", "recipe-station", recipe.station));
  return row;
}

/** A `recipes` section (app 3.19.0): one diagram per recipe, or the plugin's own empty text. */
function buildRecipes(doc, section) {
  const box = el(doc, "div", "stc-recipes");
  const recipes = section.recipes || [];
  if (!recipes.length) {
    box.appendChild(el(doc, "div", "stc-muted", section.empty || "No recipes."));
    return box;
  }
  for (const recipe of recipes) box.appendChild(recipeRow(doc, recipe));
  return box;
}

function buildPlaceholder(doc, section) {
  // The orbit/starmap drawers live in starmap.js; without them the section still occupies its place.
  const box = el(doc, "div", "stc-" + section.type);
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
  recipes: buildRecipes,
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
    // The card layout sets a sort outright (a column, or none) instead of cycling through it.
    setSort: () => {},
    // "auto" measures (measureTables); "cards"/"table" force one, as the app's `layout` prop does.
    layout: "auto",
    onSelectTab: () => {},
    sortFor: () => null,
    selectedTab: (section, tabs) => (tabs[0] ? tabs[0].id : null),
    formatRemaining: (item) => String(item.ends_at || ""),
    formatEndLabel: () => "",
    // The orbit/starmap drawers build their panels with these, so the render api always carries them:
    // a page that only overrides `orbit`/`starmap` must not have to remember them.
    el: el,
    appendCell: appendCell,
  }, options || {});
  return api;
}

function cardSection(doc, section, inner) {
  // The app wraps every section in a card whose head carries the title (PluginView's SectionList); a
  // notice and a tab strip are the two it leaves bare, so they are the two this skips.
  if (section.type === "notice" || section.type === "tabs") return inner;
  const card = el(doc, "div", "stc-section");
  if (section.title) card.appendChild(el(doc, "div", "stc-section-head", section.title));
  const body = el(doc, "div", "stc-section-body");
  body.appendChild(inner);
  card.appendChild(body);
  return card;
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
    const node = cardSection(doc, section, builder(doc, section, api));
    // The id goes on the outer node: it is what `focus` scrolls to (app.js applyPendingFocus).
    if (section.id) node.setAttribute("data-section-id", section.id);
    root.appendChild(node);
  }
  // `html` is only read by the Node-side tests (via the fake nodeFactory stand-in); a real
  // browser `document` has no `.attrs`, so toHtml(root) throws there - compute it lazily so
  // the live page, which only ever reads `.node`, never pays for it.
  return {
    node: root, children: root.children || [], types: types,
    get html() { return toHtml(root); },
  };
}

const sectionsExported = {
  renderSections, cardSection, cellText, cellIcon, cellHint, cellNoWrap, sortKey, sortRows, nextSort,
  tabPath, rowMenuItems, menuPosition, copyText, COPY_FROM_CHARS,
  measureTables, tableAsCards, cardFields, neededFor, CARD_BREAKPOINT, CARD_OVERFLOW_MAX,
  formValues, setFormValue, resetForms, escapeHtml, toHtml, nodeFactory, el, appendCell, BUILDERS,
  recipeRow, recipeCard, recipeIconUrl,
};
if (typeof module !== "undefined" && module.exports) module.exports = sectionsExported;
if (typeof window !== "undefined") window.Sections = sectionsExported;
