// Markdown as the standalone page draws it: the Codex documents and their search hits.
//
// The app renders a Codex hit with react-markdown; this page has no build step and no dependency, so it gets a
// small renderer of its own for what Codex documents use - headings, paragraphs, bullet and numbered lists,
// tables, fenced code, quotes and rules, with **bold**, *italic*, `code` and links (their text only). It builds
// DOM nodes with createElement/createTextNode and never sets innerHTML: Codex text is plugin and user text, and
// on this page plugin text is never HTML. `terms` marks the words that were searched for (word starts, any case),
// as the app marks a hit's matches. The same rules as the app overlay's parser (src/overlay/markdown.py there).

const MD_HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const MD_BULLET = /^(\s*)[-*+]\s+(.*)$/;
const MD_NUMBERED = /^(\s*)(\d+)[.)]\s+(.*)$/;
const MD_RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const MD_TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const MD_FENCE = /^\s*(```|~~~)/;
// code first (nothing inside it is markup), then links, bold, italic; underscore emphasis only at word borders,
// so item ids (FOOD_DNUT_1) stay as written
const MD_INLINE = /`([^`]+)`|!?\[([^\]]*)\]\([^)]*\)|\*\*(.+?)\*\*|(?<!\w)__(.+?)__(?!\w)|(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)/g;

function lineKind(raw) {
  const stripped = raw.trim();
  if (MD_HEADING.test(stripped)) return "heading";
  if (MD_RULE.test(raw)) return "rule";
  if (stripped.startsWith("|") || (stripped.match(/\|/g) || []).length >= 2) {
    return MD_TABLE_SEP.test(stripped) ? "sep" : "row";
  }
  if (MD_BULLET.test(raw) || MD_NUMBERED.test(raw)) return "item";
  return stripped.startsWith(">") ? "quote" : null;
}

function tableCells(line) {
  let core = line.trim();
  if (core.startsWith("|")) core = core.slice(1);
  if (core.endsWith("|")) core = core.slice(0, -1);
  return core.split("|").map((c) => c.trim());
}

/** The blocks of a Markdown text: [{kind, text|cells|lines, level, ordered, number, header}] (pure, tested). */
function markdownBlocks(text) {
  const out = [];
  let para = [];
  let code = null;
  let tableRows = 0;
  const flush = () => { if (para.length) { out.push({ kind: "p", text: para.join(" ") }); para = []; } };
  for (const raw of String(text || "").split(/\r?\n/)) {
    if (MD_FENCE.test(raw)) {
      flush();
      if (code) { out.push({ kind: "code", lines: code }); code = null; } else code = [];
      continue;
    }
    if (code) { code.push(raw); continue; }
    if (!raw.trim()) { flush(); tableRows = 0; continue; }
    const kind = lineKind(raw);
    if (kind === null) { tableRows = 0; para.push(raw.trim()); continue; }
    flush();
    if (kind !== "row" && kind !== "sep") tableRows = 0;
    const block = blockOf(kind, raw);
    if (block && kind === "row") { tableRows += 1; block.header = tableRows === 1; }
    if (block) out.push(block);
  }
  flush();
  if (code) out.push({ kind: "code", lines: code });       // an unclosed fence (a cut snippet) still shows
  return out;
}

function blockOf(kind, raw) {
  const stripped = raw.trim();
  if (kind === "heading") {
    const m = MD_HEADING.exec(stripped);
    return { kind: "h" + Math.min(4, m[1].length), text: m[2] };
  }
  if (kind === "rule") return { kind: "rule" };
  if (kind === "row") return { kind: "row", cells: tableCells(stripped) };
  if (kind === "quote") return { kind: "quote", text: stripped.replace(/^>+\s?/, "") };
  if (kind === "item") {
    const n = MD_NUMBERED.exec(raw);
    const m = n || MD_BULLET.exec(raw);
    const level = Math.floor(m[1].replace(/\t/g, "    ").length / 2);
    return n ? { kind: "li", ordered: true, number: Number(n[2]), level: level, text: n[3] }
      : { kind: "li", ordered: false, level: level, text: m[2] };
  }
  return null;                                               // "sep": the |---| line under a table's header
}

/** Inline Markdown -> [{text, bold, italic, code}] (pure, tested). */
function inlineRuns(text, style) {
  const base = style || {};
  const runs = [];
  let pos = 0;
  const plain = (t) => { if (t) runs.push({ text: t, bold: !!base.bold, italic: !!base.italic, code: false }); };
  const re = new RegExp(MD_INLINE.source, "g");
  let m;
  while ((m = re.exec(text)) !== null) {
    plain(text.slice(pos, m.index));
    if (m[1] !== undefined) runs.push({ text: m[1], bold: !!base.bold, italic: !!base.italic, code: true });
    else if (m[2] !== undefined) plain(m[2]);
    else if (m[3] !== undefined || m[4] !== undefined) runs.push(...inlineRuns(m[3] ?? m[4], { ...base, bold: true }));
    else runs.push(...inlineRuns(m[5] ?? m[6], { ...base, italic: true }));
    pos = re.lastIndex;
  }
  plain(text.slice(pos));
  return runs;
}

function termPattern(terms) {
  const words = (terms || []).map((t) => String(t).trim()).filter((t) => t.length >= 2)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return words.length ? new RegExp("(?<![\\p{L}\\p{N}])(" + words.join("|") + ")", "giu") : null;
}

function appendText(doc, parent, text, marks) {
  if (!marks) { parent.appendChild(doc.createTextNode(text)); return; }
  let pos = 0;
  const re = new RegExp(marks.source, marks.flags);
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > pos) parent.appendChild(doc.createTextNode(text.slice(pos, m.index)));
    const mark = doc.createElement("mark");
    mark.textContent = m[0];
    parent.appendChild(mark);
    pos = m.index + m[0].length;
  }
  if (pos < text.length) parent.appendChild(doc.createTextNode(text.slice(pos)));
}

function appendInline(doc, parent, text, marks) {
  for (const run of inlineRuns(text)) {
    let target = parent;
    for (const [on, tag] of [[run.code, "code"], [run.bold, "strong"], [run.italic, "em"]]) {
      if (!on) continue;
      const node = doc.createElement(tag);
      target.appendChild(node);
      target = node;
    }
    appendText(doc, target, run.text, marks);
  }
}

function appendBlock(doc, root, block, state) {
  if (block.kind === "li") {
    const tag = block.ordered ? "ol" : "ul";
    if (!state.list || state.list.tag !== tag || state.list.level !== block.level) {
      const list = doc.createElement(tag);
      list.setAttribute("class", "md-level-" + Math.min(block.level, 4));
      if (block.ordered && block.number !== 1) list.setAttribute("start", block.number);
      root.appendChild(list);
      state.list = { tag: tag, level: block.level, node: list };
    }
    const item = doc.createElement("li");
    appendInline(doc, item, block.text, state.marks);
    state.list.node.appendChild(item);
    return;
  }
  state.list = null;
  if (block.kind !== "row") state.table = null;
  const node = blockNode(doc, block, state);
  if (node) root.appendChild(node);
}

function blockNode(doc, block, state) {
  if (block.kind === "rule") return doc.createElement("hr");
  if (block.kind === "code") {
    const pre = doc.createElement("pre");
    const code = doc.createElement("code");
    code.textContent = block.lines.join("\n");
    pre.appendChild(code);
    return pre;
  }
  if (block.kind === "row") return tableRow(doc, block, state);
  const tag = block.kind === "quote" ? "blockquote" : block.kind;   // h1..h4, p
  const node = doc.createElement(tag);
  appendInline(doc, node, block.text, state.marks);
  return node;
}

function tableRow(doc, block, state) {
  let table = null;
  if (!state.table) {
    table = doc.createElement("table");
    state.table = table;
  }
  const row = doc.createElement("tr");
  for (const cell of block.cells) {
    const td = doc.createElement(block.header ? "th" : "td");
    appendInline(doc, td, cell, state.marks);
    row.appendChild(td);
  }
  state.table.appendChild(row);
  return table;                                              // appended once, with its first row
}

/** Markdown -> a <div class="md"> of real elements (never innerHTML); `terms` are marked where they start a word. */
function renderMarkdown(doc, text, terms) {
  const root = doc.createElement("div");
  root.setAttribute("class", "md");
  const state = { list: null, table: null, marks: termPattern(terms) };
  for (const block of markdownBlocks(text)) appendBlock(doc, root, block, state);
  return root;
}

/** The first `max` characters of a document, cut after a whole line (a table row or list item is never cut in
 * half), with "…" when something was left out. */
function leadingLines(text, max) {
  const all = String(text || "");
  if (all.length <= max) return all;
  const cut = all.lastIndexOf("\n", max);
  return (cut > max / 3 ? all.slice(0, cut) : all.slice(0, max)).trimEnd() + "\n\n…";
}

const markdownExported = { renderMarkdown, markdownBlocks, inlineRuns, leadingLines };
if (typeof module !== "undefined" && module.exports) module.exports = markdownExported;
if (typeof window !== "undefined") window.Markdown = markdownExported;
