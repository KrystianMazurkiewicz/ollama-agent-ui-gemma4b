(() => {
  const state = {
    config: null,
    conversations: [],
    currentId: null,
    privateMode: false,
    privateMessages: [],
    busy: false,
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    list: $("conversationList"),
    messages: $("messages"),
    title: $("chatTitle"),
    subtitle: $("chatSubtitle"),
    input: $("messageInput"),
    composer: $("composer"),
    send: $("sendButton"),
    newChat: $("newChat"),
    privateChat: $("privateChat"),
    rename: $("renameChat"),
    clear: $("clearChat"),
    del: $("deleteChat"),
    export: $("exportChat"),
    settingsToggle: $("settingsToggle"),
    settings: $("settingsPanel"),
    modelSelect: $("modelSelect"),
    modelAdd: $("modelAdd"),
    addModel: $("addModel"),
    system: $("systemPrompt"),
    warning: $("modelWarning"),
  };

  const esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );

  function mdish(text) {
    // Safe, small renderer: escape all HTML, preserve code fences, simple paragraphs only.
    const src = String(text ?? "");
    const parts = src.split(/(```[\s\S]*?```)/g);
    return parts
      .map((part) => {
        if (part.startsWith("```") && part.endsWith("```")) {
          let inner = part.slice(3, -3);
          inner = inner.replace(/^\w+\n/, "");
          return `<pre><code>${esc(inner)}</code></pre>`;
        }
        return esc(part)
          .split(/\n{2,}/)
          .map((p) => (p ? `<p>${p.replace(/\n/g, "<br>")}</p>` : ""))
          .join("");
      })
      .join("");
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let msg = `${res.status} ${res.statusText}`;
      try {
        msg = (await res.json()).error || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  }

  function localExtraModels() {
    try {
      return JSON.parse(localStorage.getItem("extra_models") || "[]");
    } catch {
      return [];
    }
  }

  function saveExtraModels(models) {
    localStorage.setItem(
      "extra_models",
      JSON.stringify([...new Set(models)].sort()),
    );
  }

  async function loadConfigAndModels() {
    state.config = await api("/api/config");
    let models = [state.config.default_model];
    try {
      const data = await api("/api/models");
      models = [
        ...new Set([
          ...(data.models || []),
          ...localExtraModels(),
          state.config.default_model,
        ]),
      ];
      if (data.warning) showWarning(data.warning);
    } catch (e) {
      showWarning(`Could not load model list: ${e.message}`);
    }
    els.modelSelect.innerHTML = "";
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = opt.textContent = m;
      els.modelSelect.appendChild(opt);
    }
    els.modelSelect.value = state.config.default_model;
  }

  function showWarning(text) {
    els.warning.textContent = text;
    els.warning.classList.remove("hidden");
  }

  function scrollBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function formatTs(ts) {
    if (!ts) return "";
    return new Date(ts).toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function setBusy(b) {
    state.busy = b;
    els.send.disabled = b;
    els.input.disabled = b;
    els.send.textContent = b ? "Wait" : "Send";
  }

  function messageEl(role, content = "", meta = "", thinking = "") {
    const wrap = document.createElement("article");
    wrap.className = `message ${role}`;
    if (meta) {
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      wrap.appendChild(m);
    }
    if (role === "assistant") {
      const think = document.createElement("details");
      think.className = "thinking-box hidden";
      think.open = true;
      think.innerHTML = `<summary>Gemma is thinking</summary><div class="thinking-text"></div>`;
      wrap.appendChild(think);
      if (thinking) {
        think.classList.remove("hidden");
        think.open = false;
        think.querySelector(".thinking-text").textContent = thinking;
      }
    }
    const body = document.createElement("div");
    body.className = "content";
    body.innerHTML = mdish(content);
    wrap.appendChild(body);
    return wrap;
  }

  function renderMessages(messages) {
    els.messages.innerHTML = "";
    for (const m of messages) {
      els.messages.appendChild(
        messageEl(
          m.role,
          m.content,
          `${m.role} · ${m.model || ""} · ${formatTs(m.timestamp)}`,
          m.thinking || "",
        ),
      );
    }
    scrollBottom();
  }

  async function loadConversations() {
    if (state.privateMode) return;
    const data = await api("/api/conversations");
    state.conversations = data.conversations || [];
    renderConversationList();
  }

  function renderConversationList() {
    els.list.innerHTML = "";
    for (const c of state.conversations) {
      const b = document.createElement("button");
      b.className =
        "conversation-item" + (c.id === state.currentId ? " active" : "");
      b.textContent = c.title;
      b.title = c.title;
      b.onclick = () => openConversation(c.id);
      els.list.appendChild(b);
    }
  }

  async function openConversation(id) {
    state.privateMode = false;
    state.currentId = id;
    const data = await api(`/api/conversations/${encodeURIComponent(id)}`);
    els.title.textContent = data.conversation.title;
    els.subtitle.textContent = "Saved locally";
    renderMessages(data.messages || []);
    await loadConversations();
  }

  async function newChat() {
    state.privateMode = false;
    state.currentId = null;
    els.title.textContent = "New chat";
    els.subtitle.textContent = "Saved locally";
    renderMessages([]);
    await loadConversations();
  }

  function privateChat() {
    state.privateMode = true;
    state.currentId = null;
    state.privateMessages = [];
    els.title.textContent = "Private chat";
    els.subtitle.textContent = "Not saved to SQLite";
    els.list
      .querySelectorAll(".active")
      .forEach((x) => x.classList.remove("active"));
    renderMessages([]);
  }

  async function sendMessage(text) {
    const model = els.modelSelect.value || state.config.default_model;
    const ts = new Date().toISOString();
    const displayTs = formatTs(ts);

    const userMsg = { role: "user", content: text, timestamp: ts, model };
    if (state.privateMode) state.privateMessages.push(userMsg);
    els.messages.appendChild(messageEl("user", text, ""));

    const assistant = messageEl(
      "assistant",
      "",
      `assistant · ${model} · ${displayTs}`,
    );
    const content = assistant.querySelector(".content");
    const thinkingBox = assistant.querySelector(".thinking-box");
    const thinkingText = assistant.querySelector(".thinking-text");
    content.innerHTML = `<span class="typing">Gemma is thinking</span>`;
    els.messages.appendChild(assistant);
    scrollBottom();

    setBusy(true);
    let answer = "";
    let thinking = "";
    let gotContent = false;
    let convId = state.currentId;
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: state.currentId,
          private: state.privateMode,
          private_history: state.privateMode
            ? state.privateMessages.map((m) => ({
                role: m.role,
                content: m.content,
              }))
            : [],
          model,
          system: els.system.value || "",
          message: text,
        }),
      });
      if (!res.ok || !res.body)
        throw new Error(`Local server error: ${res.status} ${res.statusText}`);

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += dec.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop();
        for (const ev of events) handleSSE(ev);
      }
      if (buffer.trim()) handleSSE(buffer);
    } catch (e) {
      content.innerHTML = mdish(`[Error] ${e.message}`);
    } finally {
      setBusy(false);
      els.input.focus();
      if (state.privateMode) {
        state.privateMessages.push({
          role: "assistant",
          content: answer,
          thinking,
          timestamp: new Date().toISOString(),
          model,
        });
      } else {
        await loadConversations();
        if (convId && !state.currentId) state.currentId = convId;
        renderConversationList();
      }
      scrollBottom();
    }

    function handleSSE(rawEvent) {
      let name = "message";
      const dataLines = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:"))
          dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) return;
      let data;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        data = { text: dataLines.join("\n") };
      }

      if (name === "meta") {
        convId = data.conversation_id || convId;
        if (!state.privateMode && convId) state.currentId = convId;
        return;
      }
      if (name === "thinking") {
        const t = data.text || "";
        if (!t) return;
        thinking += t;
        thinkingBox.classList.remove("hidden");
        thinkingBox.open = true;
        thinkingText.textContent = thinking;
        scrollBottom();
        return;
      }
      if (name === "content") {
        const t = data.text || "";
        if (!gotContent) {
          gotContent = true;
          thinkingBox.open = false;
          answer = "";
        }
        answer += t;
        content.innerHTML = mdish(answer);
        scrollBottom();
        return;
      }
      if (name === "error") {
        content.innerHTML = mdish(
          `[Error] ${data.error || data.text || "unknown error"}`,
        );
        return;
      }
      if (name === "done") {
        content.innerHTML = mdish(answer || "[No answer returned]");
      }
    }
  }

  els.composer.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = els.input.value.trim();
    if (!text || state.busy) return;
    els.input.value = "";
    els.input.style.height = "auto";
    await sendMessage(text);
  });

  els.input.addEventListener("input", () => {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(180, els.input.scrollHeight) + "px";
  });

  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      els.composer.requestSubmit();
    }
  });

  els.newChat.onclick = newChat;
  els.privateChat.onclick = privateChat;
  els.settingsToggle.onclick = () => els.settings.classList.toggle("hidden");

  els.addModel.onclick = () => {
    const name = els.modelAdd.value.trim();
    if (!name) return;
    const extras = localExtraModels();
    extras.push(name);
    saveExtraModels(extras);
    const opt = document.createElement("option");
    opt.value = opt.textContent = name;
    els.modelSelect.appendChild(opt);
    els.modelSelect.value = name;
    els.modelAdd.value = "";
  };

  els.rename.onclick = async () => {
    if (state.privateMode)
      return alert(
        "Private chats are not saved, so there is nothing to rename.",
      );
    if (!state.currentId)
      return alert("Send a message first, then rename the saved chat.");
    const title = prompt("New chat name:", els.title.textContent);
    if (!title) return;
    await api(
      `/api/conversations/${encodeURIComponent(state.currentId)}/rename`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      },
    );
    els.title.textContent = title;
    await loadConversations();
  };

  els.clear.onclick = async () => {
    if (state.privateMode) {
      state.privateMessages = [];
      renderMessages([]);
      return;
    }
    if (!state.currentId) return renderMessages([]);
    if (!confirm("Clear only the messages in this chat? The chat title stays."))
      return;
    await api(
      `/api/conversations/${encodeURIComponent(state.currentId)}/clear`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    renderMessages([]);
    await loadConversations();
  };

  els.del.onclick = async () => {
    if (state.privateMode) {
      privateChat();
      return;
    }
    if (!state.currentId) return;
    if (!confirm("Delete this saved chat from local history?")) return;
    await fetch(`/api/conversations/${encodeURIComponent(state.currentId)}`, {
      method: "DELETE",
    });
    await newChat();
  };

  els.export.onclick = () => {
    if (state.privateMode)
      return alert("Private chats are not saved, so export is disabled.");
    if (!state.currentId)
      return alert("Send a message first, then you can download the chat.");
    window.location.href = `/api/conversations/${encodeURIComponent(state.currentId)}/export`;
  };

  (async function init() {
    try {
      await loadConfigAndModels();
      await newChat();
      els.input.focus();
    } catch (e) {
      els.messages.innerHTML = `<article class="message assistant"><div class="content">${mdish("[Error] " + e.message)}</div></article>`;
    }
  })();
})();
