// Timer countdowns and browser notifications for the standalone page.
//
// `newState`, `collect`, `due` and `GRACE_S` are the JavaScript half of standalone/alerts.py; both are
// run against tests/alert_cases.json so they cannot drift. The tray's balloons use the Python half,
// which is what alerts the user when no page is open.
"use strict";

(function () {
  const GRACE_S = 3600;
  const STORE_KEY = "nms-companion.alerts";

  function newState() {
    let sent = {};
    try {
      const stored = typeof window === "undefined" ? null : window.localStorage.getItem(STORE_KEY);
      if (stored) sent = JSON.parse(stored) || {};
    } catch (err) {
      // Private windows, blocked site data and thumbnail capture all throw or return nothing.
      console.debug("alert state is not available in this browser", err);
    }
    return { sent: sent };
  }

  function remember(state) {
    try {
      if (typeof window === "undefined") return;
      window.localStorage.setItem(STORE_KEY, JSON.stringify(state.sent));
    } catch (err) {
      console.debug("alert state could not be stored", err);
    }
  }

  function collect(payload) {
    const source = payload && typeof payload === "object" ? payload : {};
    const timers = (source.timers || []).slice();
    for (const area of source.areas || []) {
      if (area && typeof area === "object") timers.push.apply(timers, area.timers || []);
    }
    return timers.filter((timer) => timer && typeof timer === "object");
  }

  function collectSections(view) {
    // The page's own source: `timers` sections anywhere in the view, including inside nested tabs.
    const out = [];
    const walk = (sections) => {
      for (const section of sections || []) {
        if (section.type === "timers") out.push.apply(out, section.items || []);
        if (section.type === "tabs") {
          for (const tab of section.tabs || []) walk(tab.sections);
        }
      }
    };
    walk(view && view.sections);
    return out;
  }

  function due(state, timers, now) {
    const out = [];
    for (const timer of timers || []) {
      const key = timer.key;
      const endsAt = timer.ends_at;
      if (!key || typeof endsAt !== "number" || !Number.isFinite(endsAt)) continue;
      if (!(now - endsAt >= 0 && now - endsAt <= GRACE_S)) continue;
      if (state.sent[key] === endsAt) continue;
      state.sent[key] = endsAt;
      out.push(timer);
    }
    return out;
  }

  function formatRemaining(timer, now) {
    const endsAt = timer.ends_at;
    if (typeof endsAt !== "number") return "";
    const left = Math.floor(endsAt - now);
    if (left <= 0) return "done";
    const hours = Math.floor(left / 3600);
    const minutes = Math.floor((left % 3600) / 60);
    const seconds = left % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return hours ? hours + " h " + pad(minutes) + ":" + pad(seconds) : pad(minutes) + ":" + pad(seconds);
  }

  function progress(timer, now) {
    const startedAt = timer.started_at;
    if (typeof startedAt !== "number" || typeof timer.ends_at !== "number") return 0;
    const span = timer.ends_at - startedAt;
    if (span <= 0) return 1;
    return Math.min(1, Math.max(0, (now - startedAt) / span));
  }

  // --- the page's use of it ----------------------------------------------

  let pageState = null;
  let ticking = null;

  function state() {
    if (pageState === null) pageState = newState();
    return pageState;
  }

  function attach(host) {
    // Count the rendered timers down once a second, without re-rendering the whole view.
    if (ticking) clearInterval(ticking);
    const rows = host.querySelectorAll("[data-timer-key]");
    if (!rows.length) return;
    const tick = () => {
      const now = Date.now() / 1000;
      for (const row of rows) {
        const timer = { key: row.dataset.timerKey, ends_at: Number(row.dataset.endsAt),
                        started_at: row.dataset.startedAt ? Number(row.dataset.startedAt) : undefined };
        const remaining = row.querySelector(".stc-timer-remaining");
        if (remaining) remaining.textContent = formatRemaining(timer, now);
        const fill = row.querySelector(".stc-timer-fill");
        if (fill) fill.style.width = (progress(timer, now) * 100).toFixed(1) + "%";
      }
    };
    tick();
    ticking = setInterval(tick, 1000);
  }

  function notify(timer) {
    try {
      if (typeof Notification === "undefined" || Notification.permission !== "granted") return false;
      new Notification(timer.label || "Timer", { body: "finished", tag: String(timer.key) });
      return true;
    } catch (err) {
      console.debug("the notification could not be shown", err);
      return false;
    }
  }

  function check(view) {
    const finished = due(state(), collectSections(view), Date.now() / 1000);
    if (!finished.length) return [];
    remember(state());
    for (const timer of finished) notify(timer);
    return finished;
  }

  async function requestPermission() {
    if (typeof Notification === "undefined") return "This browser cannot show notifications.";
    if (Notification.permission === "granted") return "Alerts are on for this browser.";
    try {
      const answer = await Notification.requestPermission();
      return answer === "granted"
        ? "Alerts are on for this browser."
        : "This browser blocked notifications; the tray icon still alerts you.";
    } catch (err) {
      return "The browser refused the request: " + err.message;
    }
  }

  const exported = { newState, collect, collectSections, due, formatRemaining, progress, attach,
                     check, notify, requestPermission, GRACE_S };
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  if (typeof window !== "undefined") window.Timers = exported;
})();
