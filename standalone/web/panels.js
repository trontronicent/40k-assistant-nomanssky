// The Settings, Updates and Codex panels of the standalone page.
//
// Each one draws from the host's own routes and shows every failure; nothing is cached across draws, so
// a panel always reflects what the host actually has.
"use strict";

(function () {
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function api(path, options) {
    return window.App.api(path, options);
  }

  function field(label, control, hint) {
    const wrap = el("label", "stc-field");
    wrap.appendChild(el("span", "stc-field-label", label));
    wrap.appendChild(control);
    if (hint) wrap.appendChild(el("small", "stc-field-hint", hint));
    return wrap;
  }

  async function save(changes) {
    try {
      const result = await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changes),
      });
      window.App.showNotice(result.restart_needed
        ? "Saved. Restart the companion for this to take effect."
        : "Saved.");
      return result.settings;
    } catch (err) {
      window.App.showError("The setting could not be saved: " + err.message);
      return null;
    }
  }

  // --- settings -----------------------------------------------------------

  const Settings = {
    async draw() {
      const page = document.getElementById("page-settings");
      page.textContent = "";
      page.appendChild(el("h3", null, "Settings"));
      let settings = null;
      let models = { models: [], available: false };
      try {
        settings = (await api("/api/settings")).settings;
        models = await api("/api/models");
      } catch (err) {
        window.App.showError("The settings could not be read: " + err.message);
        return;
      }
      const form = el("div", "stc-form");
      form.appendChild(field("AI assistant", toggle("ai_enabled", settings.ai_enabled),
        models.available ? "Ollama is running." : "Ollama did not answer."));
      form.appendChild(field("Chat model", modelPicker(settings, models),
        "The installer sets up 40k-12b-companion."));
      form.appendChild(field("Spoken replies", toggle("tts_enabled", settings.tts_enabled),
        "Needs the Piper voice from the installer."));
      form.appendChild(field("Game overlay", toggle("overlay_enabled", settings.overlay_enabled),
        "A small always-on-top window over the game."));
      form.appendChild(field("Tray icon", toggle("tray_enabled", settings.tray_enabled),
        "Alerts you when a timer ends, even with no page open."));
      form.appendChild(field("Codex", toggle("codex_enabled", settings.codex_enabled),
        "Keeps the generated item and world documents."));
      form.appendChild(field("Updates", channelPicker(settings),
        "Pre-release includes the beta versions."));
      form.appendChild(field("Port", portBox(settings), "Needs a restart."));
      page.appendChild(form);
    },
  };

  function toggle(key, value) {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(value);
    input.title = "Turn this on or off";
    input.addEventListener("change", async () => {
      const saved = await save({ [key]: input.checked });
      if (!saved) input.checked = !input.checked;        // the refusal stands; show the real state
    });
    return input;
  }

  function modelPicker(settings, models) {
    const select = document.createElement("select");
    select.title = "Which model answers in the chat";
    const names = models.models.slice();
    if (settings.chat_model && names.indexOf(settings.chat_model) < 0) names.unshift(settings.chat_model);
    for (const name of names) {
      const option = el("option", null, name);
      option.value = name;
      if (name === settings.chat_model) option.selected = true;
      select.appendChild(option);
    }
    if (!names.length) {
      const option = el("option", null, "no models installed");
      option.value = "";
      select.appendChild(option);
    }
    select.addEventListener("change", () => save({ chat_model: select.value }));
    return select;
  }

  function channelPicker(settings) {
    const select = document.createElement("select");
    select.title = "Which versions the Updates page offers";
    for (const channel of ["stable", "pre-release"]) {
      const option = el("option", null, channel);
      option.value = channel;
      if (channel === settings.update_channel) option.selected = true;
      select.appendChild(option);
    }
    select.addEventListener("change", () => save({ update_channel: select.value }));
    return select;
  }

  function portBox(settings) {
    const input = document.createElement("input");
    input.type = "number";
    input.value = String(settings.port);
    input.min = "1024";
    input.max = "65535";
    input.title = "The port the page is served on";
    input.addEventListener("change", () => save({ port: Number(input.value) }));
    return input;
  }

  // --- updates ------------------------------------------------------------

  const Updates = {
    async draw() {
      const page = document.getElementById("page-updates");
      page.textContent = "";
      page.appendChild(el("h3", null, "Versions"));
      page.appendChild(el("p", null, "Loading the versions…"));
      let answer = null;
      try {
        answer = await api("/api/updates", { timeoutMs: 40000 });
      } catch (err) {
        page.textContent = "";
        page.appendChild(el("h3", null, "Versions"));
        page.appendChild(el("p", null, "The versions could not be read: " + err.message));
        return;
      }
      page.textContent = "";
      page.appendChild(el("h3", null, "Versions (" + answer.channel + ")"));
      page.appendChild(el("p", null, "Installed: " + answer.installed));
      const list = el("div", "update-list");
      for (const row of answer.versions) list.appendChild(versionRow(row));
      page.appendChild(list);
    },
  };

  const ACTION_LABELS = { update: "Update", downgrade: "Downgrade", installed: "Installed",
                          blocked: "Not available" };

  function versionRow(row) {
    const line = el("div", "update-row");
    line.appendChild(el("strong", null, row.version + (row.prerelease ? " (pre-release)" : "")));
    if (row.reason) line.appendChild(el("small", null, row.reason));
    const button = el("button", null, ACTION_LABELS[row.action] || row.action);
    button.type = "button";
    button.title = row.reason || ("Install version " + row.version);
    button.disabled = row.action === "installed" || row.action === "blocked";
    button.addEventListener("click", () => installVersion(row, button));
    line.appendChild(button);
    return line;
  }

  async function installVersion(row, button) {
    const warn = row.action === "downgrade"
      ? "Going back to " + row.version + " keeps your data. Continue?"
      : "Install version " + row.version + "?";
    if (!window.confirm(warn)) return;
    button.disabled = true;
    try {
      const result = await api("/api/updates/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: row.version, confirm_data: row.action === "downgrade" }),
        timeoutMs: 300000,
      });
      window.App.showNotice(result.message || "The companion restarts now.");
      waitForRestart(row.version);
    } catch (err) {
      button.disabled = false;
      window.App.showError("The version could not be installed: " + err.message);
    }
  }

  function waitForRestart(version) {
    const page = document.getElementById("page-updates");
    page.textContent = "";
    page.appendChild(el("h3", null, "Restarting…"));
    page.appendChild(el("p", null, "Waiting for version " + version + " to come up."));
    let tries = 0;
    const poll = setInterval(async () => {
      tries += 1;
      try {
        const status = await api("/api/status", { timeoutMs: 3000 });
        if (status.version === version) {
          clearInterval(poll);
          window.location.reload();
        }
      } catch (err) {
        console.debug("the host is still restarting", err);
      }
      if (tries > 60) {
        clearInterval(poll);
        page.appendChild(el("p", null,
          "It is taking long. Start the companion from its shortcut and check apply_update.log."));
      }
    }, 2000);
  }

  // --- codex --------------------------------------------------------------

  const HIT_CHARS = 900;          // how much of a hit is shown (cut after a whole line)

  const CodexPage = {
    async draw() {
      const page = document.getElementById("page-codex");
      page.textContent = "";
      page.appendChild(el("h3", null, "Codex"));
      let info = null;
      try {
        info = await api("/api/codex");
      } catch (err) {
        page.appendChild(el("p", null, "The Codex could not be read: " + err.message));
        return;
      }
      page.appendChild(el("p", null,
        info.documents + " documents in the library “" + info.library + "”."));
      const form = el("form", "stc-form");
      const input = document.createElement("input");
      input.type = "search";
      input.placeholder = "Chromatic Metal";
      input.title = "Search the generated documents";
      const button = el("button", null, "Search");
      button.type = "submit";
      button.title = "Search the Codex";
      form.appendChild(input);
      form.appendChild(button);
      const results = el("div", "codex-results");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        results.textContent = "";
        try {
          const answer = await api("/api/codex/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: input.value }),
          });
          if (!answer.hits.length) results.appendChild(el("p", null, "Nothing matched."));
          const words = input.value.split(/\s+/).filter(Boolean);
          for (const hit of answer.hits) {
            const box = el("div", "codex-hit");
            box.appendChild(el("strong", null, hit.title));
            box.appendChild(el("small", null, hit.path));
            // Markdown, drawn styled (markdown.js) with the searched words marked - not raw text
            box.appendChild(window.Markdown.renderMarkdown(document, window.Markdown.leadingLines(hit.text, HIT_CHARS),
              words));
            results.appendChild(box);
          }
        } catch (err) {
          window.App.showError("The Codex search failed: " + err.message);
        }
      });
      page.appendChild(form);
      page.appendChild(results);
      if (info.hidden.length) page.appendChild(restoreBox(info.hidden.length));
    },
  };

  function restoreBox(count) {
    const box = el("div", "stc-notice");
    box.appendChild(el("p", null, count + " documents you deleted are left out."));
    const button = el("button", null, "Write them again");
    button.type = "button";
    button.title = "Forget that these documents were deleted";
    button.addEventListener("click", async () => {
      if (!window.confirm("Write the " + count + " deleted documents again?")) return;
      try {
        const result = await api("/api/codex/restore", { method: "POST" });
        window.App.showNotice(result.message || "Done.");
        CodexPage.draw();
      } catch (err) {
        window.App.showError("The documents could not be restored: " + err.message);
      }
    });
    box.appendChild(button);
    return box;
  }

  window.Settings = Settings;
  window.Updates = Updates;
  window.CodexPage = CodexPage;
})();
