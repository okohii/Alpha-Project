const messages = document.getElementById("messages");
const input = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const refreshButton = document.getElementById("refresh-button");
const micButton = document.getElementById("mic-button");
const alexaModeButton = document.getElementById("alexa-mode-button");
const assistantModeButton = document.getElementById("assistant-mode-button");
const eventsLog = document.getElementById("events-log");
const conversationList = document.getElementById("conversation-list");
const onlineLabel = document.getElementById("online-label");
const onlineDot = document.getElementById("online-dot");
const modelLabel = document.getElementById("model-label");

let currentConversationId = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let activeStream = null;
let activeVoiceMode = null;
let speechRecognition = null;
let recognitionReady = false;
let lastVoiceTrigger = "";
let lastTranscript = "";
let assistantAudio = null;
let silenceTimeout = null;

function appendMessage(role, content) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = content;
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function appendEvent(text) {
  const now = new Date();
  const ts = now.toLocaleString();
  eventsLog.textContent = `[${ts}] ${text}\n${eventsLog.textContent}`.slice(
    0,
    4000,
  );
}

function stopAssistantAudio() {
  if (assistantAudio) {
    try {
      assistantAudio.pause();
    } catch {
      // ignora falha ao pausar áudio
    }
    assistantAudio = null;
  }
}

function unlockAudioPlayback() {
  if (window.speechSynthesis) {
    try {
      window.speechSynthesis.resume();
    } catch {
      // ignora falha de desbloqueio
    }
  }
}

function playAssistantAudioWithFallback(audio, text) {
  const playPromise = audio.play();

  if (playPromise && typeof playPromise.then === "function") {
    playPromise
      .then(() => {
        appendEvent("Resposta em voz iniciada.");
      })
      .catch(() => {
        if ("speechSynthesis" in window) {
          window.speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = "pt-BR";
          utterance.rate = 1;
          utterance.pitch = 1;
          window.speechSynthesis.speak(utterance);
          appendEvent("Resposta em voz reproduzida via síntese do navegador.");
          return;
        }

        appendEvent(
          "Não foi possível reproduzir a resposta em voz. Clique em qualquer botão para liberar o áudio.",
        );
      });
    return;
  }

  appendEvent("Resposta em voz iniciada.");
}

async function loadHealth() {
  const response = await fetch("/health");
  const data = await response.json();
  const status = data.services.ollama === "ok" ? "ONLINE" : "OFFLINE";
  onlineLabel.textContent = status;
  onlineDot.className = `dot ${status.toLowerCase()}`;
}

async function loadSettings() {
  try {
    const response = await fetch("/settings");
    if (!response.ok) return;

    const data = await response.json();
    const providerName = data.provider_name || "local";
    const modelName = data.model || "local";
    const mode = data.llm_mode || "local";

    if (providerName && providerName !== "MockLLMProvider") {
      modelLabel.textContent = `Modelo ${mode === "cloud" ? "nuvem" : "local"}: ${modelName}`;
    } else {
      modelLabel.textContent = `Modelo ${mode === "cloud" ? "nuvem" : "local"}`;
    }
  } catch {
    modelLabel.textContent = "Modelo local";
  }
}

async function loadConversations() {
  const response = await fetch("/conversations");
  const items = await response.json();
  conversationList.innerHTML = "";
  items.forEach((conversation) => {
    const button = document.createElement("button");
    button.className = "conversation-item";
    button.textContent = conversation.title;
    button.onclick = () => {
      currentConversationId = conversation.id;
      appendEvent(`Conversa selecionada: ${conversation.title}`);
    };
    conversationList.appendChild(button);
  });
}

async function speakResponse(text) {
  if (!text) return;
  stopAssistantAudio();

  try {
    const response = await fetch("/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await response.json();

    if (data.status === "ok" && data.audio_base64) {
      const binary = Uint8Array.from(atob(data.audio_base64), (char) =>
        char.charCodeAt(0),
      );
      const audioBlob = new Blob([binary], {
        type: data.mime_type || "audio/wav",
      });
      const audioUrl = URL.createObjectURL(audioBlob);
      assistantAudio = new Audio(audioUrl);
      assistantAudio.volume = 1;
      assistantAudio.muted = false;
      playAssistantAudioWithFallback(assistantAudio, text);
    } else {
      appendEvent(data.detail || "TTS indisponível; resposta em texto apenas.");
    }
  } catch (error) {
    appendEvent(`Erro ao sintetizar voz: ${error.message}`);
  }
}

async function sendMessage(messageInput) {
  const message = (messageInput ?? input.value).trim();
  if (!message) return;

  stopAssistantAudio();
  appendMessage("user", message);
  if (!messageInput) {
    input.value = "";
  }

  const response = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: currentConversationId }),
  });

  if (!response.ok) {
    appendEvent("Falha ao enviar mensagem para o ALPHA." + Date.now());
    return;
  }

  const data = await response.json();
  currentConversationId = data.conversation_id;
  appendMessage("assistant", data.response);
  await speakResponse(data.response);
  if (data.memory_created) {
    appendEvent("Memória persistida.");
  }
}

function stopManualRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

async function transcribeFromMicrophone() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    appendEvent("Seu navegador não suporta captura de microfone.");
    return;
  }

  if (!isRecording) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    activeStream = stream;
    const recorder = new MediaRecorder(stream);
    mediaRecorder = recorder;
    audioChunks = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    recorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, {
        type: recorder.mimeType || "audio/webm",
      });
      const formData = new FormData();
      formData.append("file", audioBlob, "alpha-audio.webm");

      try {
        const response = await fetch("/voice/process", {
          method: "POST",
          body: formData,
        });
        const data = await response.json();
        const text = data.transcription || data.text || "";
        if (!text) {
          appendEvent("Não foi possível transcrever o áudio capturado.");
          return;
        }
        input.value = text;
        appendEvent(`Áudio capturado e transcrito: ${text}`);
        await sendMessage(text);
      } catch (error) {
        appendEvent(`Erro ao processar áudio: ${error.message}`);
      } finally {
        if (activeStream) {
          activeStream.getTracks().forEach((track) => track.stop());
          activeStream = null;
        }
        isRecording = false;
        micButton.classList.remove("recording");
        micButton.textContent = "🎙";
      }
    };

    recorder.start();
    isRecording = true;
    micButton.classList.add("recording");
    micButton.textContent = "■";
    appendEvent("Microfone ativado. Fale agora.");
    return;
  }

  stopManualRecording();
}

function setVoiceMode(mode) {
  activeVoiceMode = mode;
  alexaModeButton.classList.toggle("active", mode === "alexa");
  assistantModeButton.classList.toggle("active", mode === "assistant");
}

function clearVoiceTimers() {
  if (silenceTimeout) {
    clearTimeout(silenceTimeout);
    silenceTimeout = null;
  }
}

function sendAssistantVoiceCommand(text) {
  const rawText = text.trim();
  if (!rawText) return;

  const commandText = rawText
    .replace(/^(envia|enviar|manda|manda|ok|confirma|confirmar|envie)\b/gi, "")
    .trim();

  if (!commandText) return;

  appendEvent(`Comando assistente: ${commandText}`);
  sendMessage(commandText);
}

function handleAlexaCommand(rawText) {
  const text = rawText.replace(/\s+/g, " ").trim();
  if (!text) return;

  const normalizedText = text
    .replace(/[.,!?;:]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const wakeWordPattern = /(?:^|[\s,;.!?])(?:alpha|alfa)(?:[\s,;.!?]|$)/i;
  if (!wakeWordPattern.test(normalizedText)) {
    return;
  }

  const command = normalizedText.replace(wakeWordPattern, "").trim();
  if (!command) {
    const readyText = "ALPHA pronto. Estou ouvindo.";
    if (lastVoiceTrigger !== readyText.toLowerCase()) {
      lastVoiceTrigger = readyText.toLowerCase();
      appendMessage("assistant", readyText);
      speakResponse(readyText);
    }
    return;
  }

  const normalizedCommand = command.toLowerCase();
  if (lastVoiceTrigger !== normalizedCommand) {
    lastVoiceTrigger = normalizedCommand;
    appendEvent(`Comando Alexa: ${command}`);
    sendMessage(command);
  }
}

function configureRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    appendEvent("SpeechRecognition não suportado neste navegador.");
    return false;
  }

  if (!speechRecognition) {
    speechRecognition = new SpeechRecognition();
    speechRecognition.lang = "pt-BR";
    speechRecognition.continuous = true;
    speechRecognition.interimResults = true;

    speechRecognition.onresult = (event) => {
      stopAssistantAudio();

      let transcriptText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (!result || !result.isFinal) continue;

        const phrase = result[0]?.transcript?.trim() ?? "";
        if (!phrase) continue;
        transcriptText += ` ${phrase}`.trim();
      }

      if (!transcriptText) return;
      lastTranscript = transcriptText;

      if (activeVoiceMode === "alexa") {
        handleAlexaCommand(transcriptText);
        return;
      }

      if (activeVoiceMode === "assistant") {
        const normalized = transcriptText.toLowerCase();
        const shouldSendNow =
          /(?:\b(?:envia|enviar|manda|manda|ok|confirma|confirmar|confirmo)\b)/i.test(
            normalized,
          );

        clearVoiceTimers();
        if (shouldSendNow) {
          sendAssistantVoiceCommand(transcriptText);
          lastTranscript = "";
          return;
        }

        silenceTimeout = setTimeout(() => {
          const finalText = lastTranscript.trim();
          if (finalText) {
            sendAssistantVoiceCommand(finalText);
            lastTranscript = "";
          }
        }, 1200);
      }
    };

    speechRecognition.onerror = (event) => {
      appendEvent(`Reconhecimento de voz falhou: ${event.error}`);
    };

    speechRecognition.onend = () => {
      if (activeVoiceMode) {
        try {
          speechRecognition.start();
        } catch {
          // reabrir silenciosamente
        }
      }
    };
  }

  return true;
}

function startVoiceMode(mode) {
  if (!configureRecognition()) {
    return;
  }

  setVoiceMode(mode);
  clearVoiceTimers();
  lastVoiceTrigger = "";
  lastTranscript = "";

  const modeLabel =
    mode === "alexa" ? "Modo Alexa ativo." : "Modo assistente ativo.";
  appendEvent(`${modeLabel} Escuta contínua ligada.`);

  try {
    speechRecognition.start();
  } catch {
    appendEvent("Reconhecimento de voz foi reinicializado.");
    try {
      speechRecognition.stop();
      speechRecognition.start();
    } catch {
      // ignora
    }
  }
}

function stopVoiceMode() {
  clearVoiceTimers();
  activeVoiceMode = null;
  alexaModeButton.classList.remove("active");
  assistantModeButton.classList.remove("active");
  if (speechRecognition) {
    try {
      speechRecognition.stop();
    } catch {
      // ignora falha de parada
    }
  }
  appendEvent("Modo voz desligado.");
}

sendButton.addEventListener("click", () => {
  unlockAudioPlayback();
  sendMessage();
});
refreshButton.addEventListener("click", async () => {
  unlockAudioPlayback();
  await loadHealth();
  await loadSettings();
  await loadConversations();
});
micButton.addEventListener("click", () => {
  unlockAudioPlayback();
  transcribeFromMicrophone();
});
alexaModeButton.addEventListener("click", () => {
  unlockAudioPlayback();
  if (activeVoiceMode === "alexa") {
    stopVoiceMode();
  } else {
    startVoiceMode("alexa");
  }
});
assistantModeButton.addEventListener("click", () => {
  unlockAudioPlayback();
  if (activeVoiceMode === "assistant") {
    stopVoiceMode();
  } else {
    startVoiceMode("assistant");
  }
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    unlockAudioPlayback();
    sendMessage();
  }
});

appendMessage(
  "assistant",
  "ALPHA pronto. Envie uma mensagem ou ative um modo de voz.",
);
loadHealth();
loadSettings();
loadConversations();
