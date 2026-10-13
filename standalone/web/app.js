// The standalone page. Polls the connector's view, runs its actions, and shows every failure.
//
// Rules carried over from the app's frontend: every fetch has a deadline and a visible failure, no
// `if (res.ok)` without an else, no empty catch, and the view poll stops while the tab is hidden.
"use strict";

(function () {
  const POLL_MS = 5000;
  const POLL_SLOW_MS = 15000;          // after a timeout: the connector is busy, do not hammer it
  const DEADLINE_MS = 10000;

  const state = {
    status: null,
    view: { sections: [] },
    sort: new Map(),                   // section id -> {column, direction}
    tabs: new Map(),                   // section key -> selected tab id
    pollMs: POLL_MS,
    timer: null,
    pendingFocus: null,
    icons: {},
  };

  // --- plumbing -----------------------------------------------------------

  async function api(path, options) {
    const opts = Object.assign({ headers: { "Accept-Encoding": "gzip" } }, options || {});
    const controller = new AbortController();
    const deadline = opts.timeoutMs === 0 ? null : setTimeout(() => controller.abort(), opts.timeoutMs || DEADLINE_MS);
    try {
      const res = await fetch(path, Object.assign({ signal: controller.signal }, opts));
      if (!res.ok) {
        let detail = res.status + " " + res.statusText;
        try {
          const body = await res.json();
          if (body && body.detail) detail = body.detail;
        } catch (err) {
          console.debug("no JSON body on the failure", err);
        }
        throw new Error(detail);
      }
      return opts.raw ? res : await res.json();
    } finally {
      if (deadline) clearTimeout(deadline);
    }
  }

  function showError(message) {
    const box = document.getElementById("error");
    box.textContent = String(message);
    box.hidden = false;
  }

  function clearError() {
    document.getElementById("error").hidden = true;
  }

  function showNotice(message) {
    const box = document.getElementById("notice");
    box.textContent = String(message);
    box.hidden = false;
    setTimeout(() => { box.hidden = true; }, 6000);
  }

  // --- the view -----------------------------------------------------------

  function sectionKey(section, index) {
    return section.id ? "#" + section.id : "v." + index;
  }

  const renderApi = () => ({
    document: document,
    orbit: window.Starmap ? window.Starmap.orbit : undefined,
    starmap: window.Starmap ? window.Starmap.starmap : undefined,
    onAction: runAction,
    onSort: (section, column) => {
      const key = section.id || "t";
      state.sort.set(key, window.Sections.nextSort(state.sort.get(key), column));
      drawView();
    },
    sortFor: (section) => state.sort.get(section.id || "t") || null,
    onSelectTab: (section, tabId) => {
      state.tabs.set(section.id || "tabs", tabId);
      drawView();
    },
    selectedTab: (section, tabs) => {
      const chosen = state.tabs.get(section.id || "tabs");
      if (chosen && tabs.some((tab) => tab.id === chosen)) return chosen;
      return tabs[0] ? tabs[0].id : null;
    },
    formatRemaining: (item) => (window.Timers
      ? window.Timers.formatRemaining(item, Date.now() / 1000)
      : String(item.ends_at || "")),
  });

  function drawView() {
    const host = document.getElementById("page-view");
    const rendered = window.Sections.renderSections(state.view, renderApi());
    host.textContent = "";
    host.appendChild(rendered.node);
    if (window.Timers) window.Timers.attach(host);
  }

  async function pollView() {
    try {
      state.view = await api("/api/view", { timeoutMs: 20000 });
      state.pollMs = POLL_MS;
      clearError();
      drawView();
      applyPendingFocus();
      if (window.Timers) window.Timers.check(state.view);
    } catch (err) {
      state.pollMs = POLL_SLOW_MS;
      showError("The connector did not answer: " + err.message);
    } finally {
      schedulePoll();
    }
  }

  function schedulePoll() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(() => {
      if (document.visibilityState === "visible") pollView();
      else schedulePoll();
    }, state.pollMs);
  }

  function applyPendingFocus() {
    const wanted = state.pendingFocus;
    if (!wanted) return;
    state.pendingFocus = null;
    const path = window.Sections.tabPath(state.view, wanted);
    if (!path) return;
    // Select every tab on the way, then redraw and scroll to the section.
    const walk = (sections) => {
      for (const section of sections || []) {
        if (section.type === "tabs") {
          const match = (section.tabs || []).find((tab) => path.includes(tab.id));
          if (match) {
            state.tabs.set(section.id || "tabs", match.id);
            walk(match.sections);
          }
        }
      }
    };
    walk(state.view.sections);
    drawView();
    const node = document.querySelector('[data-section-id="' + wanted + '"]');
    if (node && node.scrollIntoView) node.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function runAction(actionId, params, options) {
    if (!actionId) return;
    try {
      const result = await api("/api/actions/" + encodeURIComponent(actionId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: params || {} }),
        timeoutMs: 130000,
      });
      clearError();
      if (options && options.quiet === false && result.message) showNotice(result.message);
      if (result.focus) state.pendingFocus = result.focus;
      await pollView();
    } catch (err) {
      showError("The action " + actionId + " failed: " + err.message);
    }
  }

  // --- navigation ---------------------------------------------------------

  const PAGES = ["view", "chat", "codex", "settings", "updates"];

  function showPage(name) {
    for (const page of PAGES) {
      const section = document.getElementById("page-" + page);
      if (section) section.hidden = page !== name;
      const button = document.getElementById("nav-" + page);
      if (button) button.classList.toggle("on", page === name);
    }
    if (name === "settings" && window.Settings) window.Settings.draw();
    if (name === "updates" && window.Updates) window.Updates.draw();
    if (name === "codex" && window.CodexPage) window.CodexPage.draw();
  }

  function wireNav() {
    for (const page of PAGES) {
      const button = document.getElementById("nav-" + page);
      if (button) button.addEventListener("click", () => showPage(page));
    }
    const alerts = document.getElementById("nav-alerts");
    if (alerts && window.Timers) {
      alerts.addEventListener("click", () => window.Timers.requestPermission().then((text) => showNotice(text)));
    } else if (alerts) {
      alerts.hidden = true;
    }
  }

  // --- start --------------------------------------------------------------

  async function start() {
    wireNav();
    try {
      state.status = await api("/api/status");
      document.getElementById("version").textContent = "v" + state.status.version;
      if (state.status.ai_enabled) document.getElementById("nav-chat").hidden = false;
      if (state.status.codex_enabled) document.getElementById("nav-codex").hidden = false;
      if (window.Chat) window.Chat.init({ api: api, status: state.status, showError: showError });
    } catch (err) {
      showError("The host did not answer /api/status: " + err.message);
    }
    try {
      state.icons = (await api("/api/item-icons")).icons || {};
      if (window.Chat) window.Chat.setIcons(state.icons);
    } catch (err) {
      console.debug("no item icons available", err);
    }
    await pollView();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") pollView();
    });
  }

  window.App = { api: api, showError: showError, showNotice: showNotice, state: state, showPage: showPage };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
