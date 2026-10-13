// The chat page: ask the companion persona, stream the reply, draw the recipes it sent.
//
// The stream reader buffers across chunk boundaries - a `data:` line can be split between two chunks,
// and splitting each chunk on its own loses tokens (the app's hard-won SSE rule).
"use strict";

(function () {
  const state = { api: null, status: null, showError: null, icons: {}, history: [], busy: false };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function iconFor(name) {
    const file = state.icons[name];
    return file ? "/api/assets/" + file : null;
  }

  // --- recipe diagrams ----------------------------------------------------

  function itemBox(item) {
    const wrap = el("div", "recipe-item");
    const box = el("div", "box");
    const url = iconFor(item.name);
    if (url) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = "";
      box.appendChild(img);
    }
    wrap.appendChild(box);
    wrap.appendChild(el("small", null, (item.amount || 1) + " x " + (item.name || "")));
    return wrap;
  }

  function recipeRow(recipe) {
    const row = el("div", "recipe");
    (recipe.ingredients || []).forEach((item, index) => {
      if (index) row.appendChild(el("span", null, "+"));
      row.appendChild(itemBox(item));
    });
    row.appendChild(el("span", null, "→"));
    if (recipe.result) row.appendChild(itemBox(recipe.result));
    if (recipe.station) row.appendChild(el("small", "recipe-station", recipe.station));
    return row;
  }

  // --- the turn -----------------------------------------------------------

  function drawTurn(role, text) {
    const turn = el("div", "chat-turn " + role, text);
    document.getElementById("chat-log").appendChild(turn);
    turn.scrollIntoView({ block: "nearest" });
    return turn;
  }

  async function send(message) {
    if (state.busy || !message.trim()) return;
    state.busy = true;
    drawTurn("user", message);
    const turn = drawTurn("assistant", "…");
    let answer = "";
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message, history: state.history }),
      });
      if (!res.ok) {
        let detail = res.status + " " + res.statusText;
        try {
          const body = await res.json();
          if (body && body.detail) detail = body.detail;
        } catch (err) {
          console.debug("no JSON body on the chat failure", err);
        }
        throw new Error(detail);
      }
      answer = await read(res, turn);
      state.history.push({ role: "user", content: message });
      state.history.push({ role: "assistant", content: answer });
    } catch (err) {
      turn.textContent = answer || "";
      turn.appendChild(el("div", "chat-failed", "The reply failed: " + err.message));
      if (state.showError) state.showError("The chat failed: " + err.message);
    } finally {
      state.busy = false;
    }
    return answer;
  }

  async function read(res, turn) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = "";
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();                        // keep the unfinished line for the next chunk
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const event = JSON.parse(line.slice(6));
        if (event.token) {
          answer += event.token;
          turn.textContent = answer;
        }
        if (event.error) throw new Error(event.error);
        if (event.done) {
          for (const recipe of event.recipes || []) turn.appendChild(recipeRow(recipe));
        }
      }
    }
    return answer;
  }

  // --- page ---------------------------------------------------------------

  function draw() {
    const page = document.getElementById("page-chat");
    if (page.dataset.ready) return;
    page.dataset.ready = "1";
    const log = el("div", "chat-log");
    log.id = "chat-log";
    page.appendChild(log);
    const form = el("form", "chat-form");
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "How much Copper do I have?";
    input.title = "Ask the companion persona about your game";
    const button = el("button", null, "Ask");
    button.type = "submit";
    button.title = "Send the question to the companion";
    form.appendChild(input);
    form.appendChild(button);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const message = input.value;
      input.value = "";
      send(message);
    });
    page.appendChild(form);
    page.appendChild(el("small", "chat-hint",
      "Answers come from your own save and the running game, through the plugin's persona."));
  }

  function init(options) {
    state.api = options.api;
    state.status = options.status;
    state.showError = options.showError;
    draw();
  }

  window.Chat = {
    init: init,
    draw: draw,
    send: send,
    setIcons: (icons) => { state.icons = icons || {}; },
    recipeRow: recipeRow,
    state: state,
  };
})();
