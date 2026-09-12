"use strict";

(function () {
  const stateLabels = {
    idle: "Repouso",
    listening: "Ouvindo",
    thinking: "Pensando",
    planning: "Planejando",
    executing: "Executando",
    verifying: "Verificando",
    speaking: "Falando",
    error: "Erro",
  };

  const chatArea = document.getElementById("chatArea");
  const emptyState = document.getElementById("emptyState");
  const statePill = document.getElementById("statePill");
  const stateText = document.getElementById("stateText");
  const textInput = document.getElementById("textInput");
  const btnSend = document.getElementById("btnSend");
  const btnMic = document.getElementById("btnMic");
  const btnCancel = document.getElementById("btnCancel");
  const toolBar = document.getElementById("toolBar");
  const toolName = document.getElementById("toolName");
  const toolStatus = document.getElementById("toolStatus");
  const confirmModal = document.getElementById("confirmModal");
  const confirmTool = document.getElementById("confirmTool");
  const confirmArgs = document.getElementById("confirmArgs");
  const btnApprove = document.getElementById("btnApprove");
  const btnDeny = document.getElementById("btnDeny");

  let ws = null;
  let currentState = "idle";
  let busy = false;
  let activeTool = null;
  let recording = false;
  let mediaRecorder = null;
  let mediaChunks = [];
  let stream = null;
  let conversationId = null;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/overlay/ws`);

    ws.onopen = () => {
      setState("idle");
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleMessage(msg);
    };
    ws.onclose = () => {
      setState("error");
      busy = false;
      setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
  }

  /* ── render ─────────────────────────────────────────────────── */

  function scrollBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
  }

  function addMessage(kind, content) {
    emptyState.style.display = "none";
    const el = document.createElement("div");
    el.className = `msg ${kind}`;

    if (kind === "assistant") {
      const title = document.createElement("div");
      title.className = "msg-title";
      title.innerHTML = "ALPHA";
      el.appendChild(title);
    }

    const body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = content;
    el.appendChild(body);
    chatArea.appendChild(el);
    scrollBottom();
    return body;
  }

  function appendToken(body, token) {
    if (body) body.textContent += token;
    scrollBottom();
  }

  function setState(state) {
    currentState = state;
    statePill.dataset.state = state;
    stateText.textContent = stateLabels[state] || state;
    btnCancel.hidden = !["thinking", "executing", "verifying"].includes(state);
  }

  function setCollapsedTool() {
    if (!activeTool) {
      toolBar.hidden = true;
      return;
    }
    toolBar.hidden = false;
    toolName.textContent = activeTool.name;
    toolStatus.className = "tool-status";
    if (activeTool.running) {
      toolStatus.classList.add("run");
      toolStatus.innerHTML = `<span class="spin"></span>executando`;
    } else if (activeTool.success === true) {
      toolStatus.classList.add("ok");
      toolStatus.textContent = "ok";
    } else if (activeTool.success === false) {
      toolStatus.classList.add("fail");
      toolStatus.textContent = "falhou";
    } else {
      toolStatus.textContent = "";
    }
  }

  /* ── protocolo WS ───────────────────────────────────────────── */

  function handleMessage(msg) {
    const kind = msg.type || msg.event;
    switch (kind) {
      case "state":
        setState(msg.state);
        if (msg.state === "idle" || msg.state === "error") {
          activeTool = null;
          setCollapsedTool();
        }
        break;

      case "assistant_message": {
        const payload = msg.payload || {};
        const content = payload.content || payload.preview || "";
        if (!content) break;
        const last = lastAssistantBody();
        if (last && last.textContent === "") {
          last.textContent = content; // conclui a mensagem que veio por stream
        } else if (!last || last.textContent !== content) {
          addMessage("assistant", content);
        }
        break;
      }

      case "token_stream": {
        const token = (msg.payload || {}).token || "";
        if (!token) break;
        let body = lastAssistantBody();
        if (!body) body = addMessage("assistant", "");
        appendToken(body, token);
        break;
      }

      case "user_message":
        // a fala já foi renderizada localmente ao enviar
        break;

      case "tool_started": {
        const p = msg.payload || {};
        activeTool = { name: p.tool, running: true, success: null };
        setCollapsedTool();
        break;
      }
      case "tool_finished":
      case "tool_failed": {
        const p = msg.payload || {};
        if (activeTool && activeTool.name === p.tool) {
          activeTool.running = false;
          activeTool.success = kind === "tool_finished" && !!p.success;
        }
        setCollapsedTool();
        if (kind === "tool_failed" && p.error) {
          addToolNote(`ferramenta ${p.tool} falhou: ${p.error}`);
        }
        break;
      }

      case "memory_created":
        addToolNote("memória salva");
        break;

      case "transcription": {
        const text = (msg.text || "").trim();
        if (!text) {
          addToolNote("não entendi o áudio");
          break;
        }
        addMessage("user", text);
        sendChat(text);
        break;
      }

      case "confirmation":
        showConfirmation(msg.tool || msg.kind || "?", msg.arguments || "");
        break;

      case "error":
        addMessage("error", msg.message || "ocorreu um erro");
        setState("error");
        busy = false;
        break;

      case "done":
        if (msg.conversation_id) conversationId = msg.conversation_id;
        busy = false;
        break;
    }
  }

  function lastAssistantBody() {
    const el = chatArea.querySelector(".msg.assistant:last-of-type .msg-body");
    return el || null;
  }

  function addToolNote(text) {
    const title = document.createElement("div");
    title.className = "msg-title";
    title.innerHTML = `ALPHA <span class="tick">·</span> ${escapeHtml(text)}`;
    chatArea.appendChild(title);
    scrollBottom();
  }

  function escapeHtml(s) {
    const d = document.createElement("span");
    d.textContent = s;
    return d.innerHTML;
  }

  /* ── envio ──────────────────────────────────────────────────── */

  function sendChat(message) {
    if (busy) return;
    busy = true;
    activeTool = null;
    setCollapsedTool();
    ws.send(JSON.stringify({ action: "chat_stream", message, conversation_id: conversationId }));
  }

  function onSend() {
    const message = textInput.value.trim();
    if (!message) return;
    textInput.value = "";
    addMessage("user", message);
    sendChat(message);
  }

  function onCancel() {
    ws.send(JSON.stringify({ action: "cancel" }));
    btnCancel.hidden = true;
  }

  /* ── confirmação ────────────────────────────────────────────── */

  function showConfirmation(tool, args) {
    confirmTool.textContent = tool;
    confirmArgs.textContent =
      typeof args === "string" ? args : JSON.stringify(args, null, 2);
    confirmModal.hidden = false;
  }

  function resolveConfirmation(approved) {
    confirmModal.hidden = true;
    ws.send(JSON.stringify({ action: "confirm", approved }));
  }

  /* ── voz ────────────────────────────────────────────────────── */

  async function toggleMic() {
    if (recording) {
      stopRecording();
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickMime(MediaRecorder.isTypeSupported);
      mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      mediaChunks = [];
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size) mediaChunks.push(e.data);
      };
      mediaRecorder.onstop = () => {
        if (mediaChunks.length) {
          const blob = new Blob(mediaChunks, { type: mediaRecorder.mimeType || "audio/webm" });
          blobToBase64(blob, (base64) => {
            ws.send(JSON.stringify({ action: "voice", audio_base64: base64 }));
          });
        }
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      };
      mediaRecorder.start();
      recording = true;
      btnMic.classList.add("recording");
      btnMic.title = "Parar gravação";
    } catch {
      addMessage("error", "microfone não disponível");
    }
  }

  function pickMime(isSupported) {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ];
    for (const c of candidates) if (isSupported(c)) return c;
    return null;
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    recording = false;
    btnMic.classList.remove("recording");
    btnMic.title = "Ativar voz";
  }

  function blobToBase64(blob, cb) {
    const reader = new FileReader();
    reader.onloadend = () => {
      const data = reader.result;
      const base64 = data.split(",")[1] || "";
      cb(base64);
    };
    reader.readAsDataURL(blob);
  }

  /* ── janela (pywebview) ─────────────────────────────────────── */

  window.addEventListener("alpha:overlay", (ev) => {
    // Push backend→UI opcional (ex.: overlay_ready) via fila do controller.
    if (ev.detail && ev.detail.name) {
      console.info("[ALPHA overlay]", ev.detail.name);
    }
  });

  function minimize() {
    if (window.pywebview && pywebview.api) {
      pywebview.api.minimize();
    }
  }

  function closeWindow() {
    if (window.pywebview && pywebview.api) {
      pywebview.api.close();
    } else {
      window.close();
    }
  }

  /* ── bindings ───────────────────────────────────────────────── */

  btnSend.addEventListener("click", onSend);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onSend();
    }
  });
  btnCancel.addEventListener("click", onCancel);
  btnMic.addEventListener("click", toggleMic);
  btnApprove.addEventListener("click", () => resolveConfirmation(true));
  btnDeny.addEventListener("click", () => resolveConfirmation(false));
  document.getElementById("btnMinimize").addEventListener("click", minimize);
  document.getElementById("btnClose").addEventListener("click", closeWindow);

  textInput.focus();
  connect();
})();