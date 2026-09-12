"use strict";

(function () {
  const caption = document.getElementById("caption");
  const confirmChip = document.getElementById("confirmChip");
  const confirmText = document.getElementById("confirmText");
  const closeBtn = document.getElementById("closeBtn");

  let ws = null;
  let astral = null;
  let idleTimer = null;
  let captionTimer = null;
  let lastState = "idle";
  let pendingConfirm = false;

  function initRenderer() {
    try {
      const canvas = document.getElementById("astral");
      astral = new window.AstralCore(canvas);
    } catch (err) {
      console.warn("[ALPHA] WebGL indisponível.", err);
    }
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/avatar/ws`);

    ws.onopen = () => {
      setState("idle");
      // Mic já ligado: a sessão de voz começa no backend assim que o WS abre.
      ws.send(JSON.stringify({ action: "start" }));
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      handle(msg);
    };
    ws.onclose = () => {
      clearTimeout(idleTimer);
      clearTimeout(captionTimer);
      pendingConfirm = false;
      confirmChip.hidden = true;
      setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
  }

  function setState(state) {
    lastState = state;
    if (astral) astral.setState(state);
  }

  function handle(msg) {
    switch (msg.type) {
      case "state":
        setState(msg.state);
        clearTimeout(idleTimer);
        if (msg.idle_after_ms) {
          idleTimer = setTimeout(() => {
            if (lastState === msg.state) setState("idle");
          }, msg.idle_after_ms);
        }
        break;

      case "caption":
        showCaption(msg.text, msg.from);
        break;

      case "ready":
        if (msg.voice === "on" && astral) astral.setAmplitude(0.1);
        break;

      case "confirmation":
        showConfirmation(msg.tool, msg.arguments || "");
        break;

      case "error":
        showCaption(msg.message || "erro", "error");
        break;
    }
  }

  function showCaption(text, from) {
    caption.textContent = text;
    caption.dataset.from = from === "user" ? "user" : "alpha";
    caption.hidden = false;
    clearTimeout(captionTimer);
    captionTimer = setTimeout(() => {
      caption.hidden = true;
    }, 3200);
  }

  function showConfirmation(tool, args) {
    confirmText.textContent = `${tool}: ${args}`;
    confirmChip.hidden = false;
    pendingConfirm = true;
  }

  function resolveConfirmation(approved) {
    if (!pendingConfirm) return;
    confirmChip.hidden = true;
    pendingConfirm = false;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "confirm", approved }));
    }
  }

  /* ── janela (pywebview) ─────────────────────────────── */

  function toggleSolid() {
    const isSolid = document.body.classList.toggle("solid");
    try {
      localStorage.setItem("alphaAvatarSolid", isSolid ? "1" : "0");
    } catch (e) {
      // noop
    }
  }

  function restoreSolid() {
    try {
      if (localStorage.getItem("alphaAvatarSolid") === "1") {
        document.body.classList.add("solid");
      }
    } catch (e) {
      // noop
    }
  }

  function closeWindow() {
    if (window.pywebview && pywebview.api) {
      pywebview.api.close();
    } else if (ws) {
      ws.send(JSON.stringify({ action: "close" }));
      window.close();
    } else {
      window.close();
    }
  }

  // Duplo clique: se a transparência real não compõe o desktop, alterna
  // para fundo sólido escuro (rede de segurança manual).
  document.addEventListener("dblclick", (e) => {
    e.preventDefault();
    toggleSolid();
  });

  closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    closeWindow();
  });
  document.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    closeWindow();
  });
  document.getElementById("btnApprove").addEventListener("click", () => resolveConfirmation(true));
  document.getElementById("btnDeny").addEventListener("click", () => resolveConfirmation(false));

  restoreSolid();
  initRenderer();
  connect();
})();