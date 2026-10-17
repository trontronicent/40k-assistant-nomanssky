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

  // --- recipe diagrams ----------------------------------------------------
  // Drawn by sections.js (Sections.recipeRow), the same builder the page's `recipes` sections use - so a
  // recipe under a reply, in the Recipes tab and in the overlay all look the same.

  function recipeRow(recipe) {
    const doc = window.Sections.nodeFactory(document);
    return window.Sections.recipeRow(doc, recipe, state.icons);
  }

  // --- the turn -----------------------------------------------------------

  function speakButton(turn) {
    const button = el("button", "chat-speak", "Speak");
    button.type = "button";
    button.title = "Read this answer aloud";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const res = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: turn.textContent }),
        });
        if (!res.ok) throw new Error("the voice failed (" + res.status + ")");
        const audio = new Audio(URL.createObjectURL(await res.blob()));
        await audio.play();
      } catch (err) {
        if (state.showError) state.showError("Speaking failed: " + err.message);
      } finally {
        button.disabled = false;
      }
    });
    return button;
  }

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
          if (state.status && state.status.tts_enabled) turn.appendChild(speakButton(turn));
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
