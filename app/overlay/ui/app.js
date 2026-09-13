"use strict";

(function () {
  const stateLabels = { idle: "Repouso", listening: "Ouvindo", thinking: "Pensando", planning: "Planejando", executing: "Executando", verifying: "Verificando", speaking: "Falando", error: "Erro" };
  const chatArea = document.getElementById("chatArea");
  const emptyState = document.getElementById("emptyState");
  const statePill = document.getElementById("statePill");
  const stateText = document.getElementById("stateText");
  const textInput = document.getElementById("textInput");
  const btnSend = document.getElementById("btnSend");
  const btnMic = document.getElementById("btnMic");
  const btnCancel = document.getElementById("btnCancel");
  const executionFeed = document.getElementById("executionFeed");
  const executionList = document.getElementById("executionList");
  const confirmModal = document.getElementById("confirmModal");
  const confirmTool = document.getElementById("confirmTool");
  const confirmArgs = document.getElementById("confirmArgs");
  const btnApprove = document.getElementById("btnApprove");
  const btnDeny = document.getElementById("btnDeny");

  let ws = null;
  let currentState = "idle";
  let busy = false;
  let recording = false;
  let mediaRecorder = null;
  let mediaChunks = [];
  let stream = null;
  let conversationId = null;
  let executionTimer = null;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/overlay/ws`);
    ws.onopen = () => setState("idle");
    ws.onmessage = (ev) => { try { handleMessage(JSON.parse(ev.data)); } catch {} };
    ws.onclose = () => { setState("error"); busy = false; setTimeout(connect, 1500); };
    ws.onerror = () => ws.close();
  }

  function scrollBottom() { chatArea.scrollTop = chatArea.scrollHeight; }

  function addMessage(kind, content) {
    emptyState.style.display = "none";
    const el = document.createElement("div");
    el.className = `msg ${kind}`;
    if (kind === "assistant") {
      const title = document.createElement("div");
      title.className = "msg-title";
      title.textContent = "ALPHA";
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

  function appendToken(body, token) { if (body) body.textContent += token; scrollBottom(); }

  function setState(state) {
    currentState = state;
    statePill.dataset.state = state;
    stateText.textContent = stateLabels[state] || state;
    btnCancel.hidden = !["thinking", "executing", "verifying"].includes(state);
  }

  function addExecution(msg) {
    executionFeed.hidden = false;
    const item = document.createElement("div");
    item.className = "execution-item";
    const icon = document.createElement("span");
    icon.className = "execution-icon";
    icon.textContent = msg.success === false ? "✗" : msg.success === true ? "✓" : "◉";
    const text = document.createElement("span");
    text.className = "execution-text";
    text.textContent = `${msg.label || msg.event || "ação"}${msg.target ? ` ${msg.target}` : ""}`;
    item.append(icon, text);
    executionList.appendChild(item);
    while (executionList.children.length > 8) executionList.removeChild(executionList.firstChild);
    clearTimeout(executionTimer);
    executionTimer = setTimeout(() => { executionFeed.hidden = true; executionList.innerHTML = ""; }, 12000);
  }

  function handleMessage(msg) {
    const kind = msg.type || msg.event;
    switch (kind) {
      case "state":
        setState(msg.state);
        break;
      case "assistant_message": {
        const payload = msg.payload || {};
        const content = payload.content || payload.preview || "";
        if (!content) break;
        addMessage("assistant", content);
        break;
      }
      case "token_stream": {
        const token = (msg.payload || {}).token || "";
        if (!token) break;
        let body = chatArea.querySelector(".msg.assistant:last-of-type .msg-body");
        if (!body) body = addMessage("assistant", "");
        appendToken(body, token);
        break;
      }
      case "tool_started":
        addExecution({ label: "ferramenta executando", target: (msg.payload || {}).tool, success: null });
        break;
      case "tool_finished":
      case "tool_failed":
        addExecution({ label: kind === "tool_finished" ? "ferramenta concluída" : "ferramenta falhou", target: (msg.payload || {}).tool, success: kind === "tool_finished" && !!(msg.payload || {}).success });
        break;
      case "execution":
        addExecution(msg);
        break;
      case "memory_created":
        addExecution({ label: "memória salva", success: true });
        break;
      case "transcription": {
        const text = (msg.text || "").trim();
        if (!text) { addMessage("error", "não entendi o áudio"); break; }
        addMessage("user", text);
        sendChat(text);
        break;
      }
      case "confirmation": showConfirmation(msg.tool || msg.kind || "?", msg.arguments || ""); break;
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

  function sendChat(message) {
    if (busy || !ws || ws.readyState !== WebSocket.OPEN) return;
    busy = true;
    executionList.innerHTML = "";
    executionFeed.hidden = true;
    ws.send(JSON.stringify({ action: "chat_stream", message, conversation_id: conversationId }));
  }

  function onSend() {
    const message = textInput.value.trim();
    if (!message) return;
    textInput.value = "";
    addMessage("user", message);
    sendChat(message);
  }

  function onCancel() { if (ws) ws.send(JSON.stringify({ action: "cancel" })); btnCancel.hidden = true; }

  function showConfirmation(tool, args) {
    confirmTool.textContent = tool;
    confirmArgs.textContent = typeof args === "string" ? args : JSON.stringify(args, null, 2);
    confirmModal.hidden = false;
  }

  function resolveConfirmation(approved) {
    confirmModal.hidden = true;
    if (ws) ws.send(JSON.stringify({ action: "confirm", approved }));
  }

  async function toggleMic() {
    if (recording) { stopRecording(); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickMime(MediaRecorder.isTypeSupported);
      mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      mediaChunks = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size) mediaChunks.push(e.data); };
      mediaRecorder.onstop = () => {
        if (mediaChunks.length) {
          const blob = new Blob(mediaChunks, { type: mediaRecorder.mimeType || "audio/webm" });
          blobToBase64(blob, (base64) => ws.send(JSON.stringify({ action: "voice", audio_base64: base64 })));
        }
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      };
      mediaRecorder.start();
      recording = true;
      btnMic.classList.add("recording");
      btnMic.title = "Parar gravação";
    } catch { addMessage("error", "microfone não disponível"); }
  }

  function pickMime(isSupported) {
    for (const c of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) if (isSupported(c)) return c;
    return null;
  }
  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
    recording = false;
    btnMic.classList.remove("recording");
    btnMic.title = "Ativar voz";
  }
  function blobToBase64(blob, cb) {
    const reader = new FileReader();
    reader.onloadend = () => cb((reader.result || "").split(",")[1] || "");
    reader.readAsDataURL(blob);
  }

  function minimize() { if (window.pywebview && pywebview.api) pywebview.api.minimize(); }
  function closeWindow() { if (window.pywebview && pywebview.api) pywebview.api.close(); else window.close(); }

  btnSend.addEventListener("click", onSend);
  textInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); onSend(); } });
  btnCancel.addEventListener("click", onCancel);
  btnMic.addEventListener("click", toggleMic);
  btnApprove.addEventListener("click", () => resolveConfirmation(true));
  btnDeny.addEventListener("click", () => resolveConfirmation(false));
  document.getElementById("btnMinimize").addEventListener("click", minimize);
  document.getElementById("btnClose").addEventListener("click", closeWindow);

  textInput.focus();
  connect();
})();
