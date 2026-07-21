/** EasyRecon live chat — per-pharmacy session restore */

const DEFAULT_PHARMACY = "Bismillah Medical Store";
const PHARMACY_KEY = "easyrecon_pharmacy";

function getPharmacyName() {
  return localStorage.getItem(PHARMACY_KEY) || DEFAULT_PHARMACY;
}

function setPharmacyName(name) {
  localStorage.setItem(PHARMACY_KEY, name);
}

function formatMessageHtml(text) {
  const parts = [];
  const lines = text.split("\n");
  let i = 0;
  let textBuf = [];

  function flushText() {
    if (!textBuf.length) return;
    let chunk = textBuf.join("\n");
    textBuf = [];
    chunk = chunk
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<strong>$1</strong>")
      .replace(/_(.+?)_/g, "<em>$1</em>");
    parts.push(`<div class="msg-text">${chunk.replace(/\n/g, "<br>")}</div>`);
  }

  while (i < lines.length) {
    const line = lines[i];
    if (/^\|.+\|$/.test(line.trim())) {
      flushText();
      const tableLines = [];
      while (i < lines.length && /^\|.+\|$/.test(lines[i].trim())) {
        tableLines.push(lines[i].trim());
        i++;
      }
      const parsed = tableLines
        .filter((row) => !/^\|[\s\-:|]+\|$/.test(row))
        .map((row) => row.slice(1, -1).split("|").map((c) => c.trim()));
      if (parsed.length >= 1) {
        const header = parsed[0];
        const body = parsed.slice(1);
        let html = '<table class="msg-table"><thead><tr>';
        header.forEach((h) => { html += `<th>${h}</th>`; });
        html += "</tr></thead><tbody>";
        body.forEach((row) => {
          html += "<tr>";
          row.forEach((c) => { html += `<td>${c}</td>`; });
          html += "</tr>";
        });
        html += "</tbody></table>";
        parts.push(html);
      }
      continue;
    }
    textBuf.push(line);
    i++;
  }
  flushText();
  return parts.join("");
}

function formatMsgTime(iso) {
  if (!iso) return new Date().toLocaleTimeString("en-PK", { hour: "2-digit", minute: "2-digit" });
  try {
    return new Date(iso).toLocaleTimeString("en-PK", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function initChat(options = {}) {
  const chat = document.getElementById("chat");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const micBtn = document.getElementById("mic-btn");
  const ttsToggle = document.getElementById("tts-toggle");
  const sidEl = document.getElementById("sid");
  const titleEl = document.getElementById("pharmacy-title");
  const resetBtn = document.getElementById("new-chat");

  let pharmacyName = getPharmacyName();
  let sessionId = null;

  const voiceOut = typeof SpeechFeatures !== "undefined" ? new SpeechFeatures.VoiceOutput() : null;
  let voiceIn = null;

  function setVoiceUI(recording) {
    if (micBtn) {
      micBtn.classList.toggle("recording", recording);
      micBtn.disabled = recording;
      micBtn.title = recording ? "Recording…" : "Mic se boliye";
    }
    if (sendBtn) {
      sendBtn.classList.toggle("voice-send", recording);
      sendBtn.textContent = recording ? "\u23F9" : "\u27A4";
      sendBtn.title = recording ? "Stop aur send" : "Send";
      sendBtn.setAttribute("aria-label", recording ? "Stop and send voice" : "Send");
    }
  }

  if (typeof SpeechFeatures !== "undefined" && micBtn) {
    voiceIn = new SpeechFeatures.VoiceInput({
      inputEl: input,
      onStateChange: setVoiceUI,
      onError: (msg) => addBubble(msg, "system"),
    });
    if (!SpeechFeatures.supportsBrowserSTT()) {
      micBtn.style.display = "none";
    }
  } else if (micBtn) {
    micBtn.style.display = "none";
  }

  if (voiceOut && ttsToggle) {
    ttsToggle.classList.toggle("active", voiceOut.getAutoSpeak());
    ttsToggle.onclick = () => {
      const next = !voiceOut.getAutoSpeak();
      voiceOut.setAutoSpeak(next);
      ttsToggle.classList.toggle("active", next);
      ttsToggle.title = next ? "Auto-read ON — click to mute" : "Auto-read OFF — click to enable";
    };
    ttsToggle.title = voiceOut.getAutoSpeak()
      ? "Auto-read ON — click to mute"
      : "Auto-read OFF — click to enable";
  } else if (ttsToggle) {
    ttsToggle.style.display = "none";
  }

  if (titleEl) titleEl.textContent = pharmacyName;

  function addBubble(text, cls, html = false, at = null) {
    const wrap = document.createElement("div");
    wrap.className = `bubble-wrap ${cls.split(" ")[0]}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble " + cls;
    if (html) bubble.innerHTML = text;
    else bubble.textContent = text;

    wrap.appendChild(bubble);
    if (!cls.includes("system")) {
      const time = document.createElement("div");
      time.className = "bubble-time";
      time.textContent = formatMsgTime(at);
      wrap.appendChild(time);
    }
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return bubble;
  }

  function renderMessages(messages) {
    chat.innerHTML = "";
    if (!messages || !messages.length) {
      if (options.welcome) addBubble(options.welcome, "bot");
      return;
    }
    for (const msg of messages) {
      const cls = msg.role === "user" ? "user" : "bot";
      const html = cls === "bot";
      const content = html ? formatMessageHtml(msg.content) : msg.content;
      addBubble(content, cls, html, msg.at);
    }
  }

  async function loadPharmacySession() {
    try {
      const r = await fetch(
        `/session/pharmacy?pharmacy_name=${encodeURIComponent(pharmacyName)}`
      );
      const d = await r.json();
      sessionId = d.session_id;
      if (sidEl) sidEl.textContent = sessionId.slice(0, 10) + "…";
      renderMessages(d.messages);
      return d;
    } catch {
      if (sidEl) sidEl.textContent = "offline";
      if (options.welcome) addBubble(options.welcome, "bot");
    }
  }

  loadPharmacySession();

  function startThinking() {
    const el = addBubble("Thinking.", "system thinking");
    let step = 0;
    const timer = setInterval(() => {
      step = (step + 1) % 3;
      el.textContent = "Thinking" + ".".repeat(step + 1);
    }, 450);
    return () => {
      clearInterval(timer);
      el.closest(".bubble-wrap")?.remove();
    };
  }

  async function ask(q, opts = {}) {
    if (!q.trim()) return;
    if (voiceOut) voiceOut.stop();
    addBubble(q.trim(), "user");
    input.value = "";
    sendBtn.disabled = true;
    if (micBtn) micBtn.disabled = true;
    const stopThinking = startThinking();

    try {
      const res = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q.trim(),
          session_id: sessionId,
          pharmacy_name: pharmacyName,
        }),
      });
      const data = await res.json();
      stopThinking();
      if (data.session_id) {
        sessionId = data.session_id;
        if (sidEl) sidEl.textContent = sessionId.slice(0, 10) + "…";
      }
      const detail = typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg;
      const answer = data.answer || data.error || detail || "Koi jawab nahi.";
      addBubble(formatMessageHtml(answer), "bot", true);
      if (voiceOut && voiceOut.getAutoSpeak() && answer) {
        voiceOut.speak(answer, { preferServer: !!opts.fromVoice });
      }
    } catch {
      stopThinking();
      addBubble("Server se connect nahi ho saka. API chal rahi hai?", "bot");
    }
    sendBtn.disabled = false;
    if (micBtn && !voiceIn?.listening) micBtn.disabled = false;
    input.focus();
  }

  async function handleSend() {
    if (voiceIn?.listening) {
      sendBtn.disabled = true;
      try {
        const text = await voiceIn.stopAndTranscribe();
        if (text.trim()) await ask(text.trim(), { fromVoice: true });
      } catch (err) {
        addBubble(err.message || "Voice fail.", "system");
      }
      sendBtn.disabled = false;
      if (micBtn) micBtn.disabled = false;
      return;
    }
    await ask(input.value);
  }

  async function resetChat() {
    if (voiceIn?.listening) voiceIn.cancel();
    if (!confirm("Nayi chat shuru karein? Purani history is pharmacy ke liye clear ho jayegi.")) return;
    sendBtn.disabled = true;
    try {
      const r = await fetch(
        `/session/pharmacy/reset?pharmacy_name=${encodeURIComponent(pharmacyName)}`,
        { method: "POST" }
      );
      const d = await r.json();
      sessionId = d.session_id;
      if (sidEl) sidEl.textContent = sessionId.slice(0, 10) + "…";
      renderMessages([]);
      if (options.welcome) addBubble(options.welcome, "bot");
    } catch {
      addBubble("Reset fail — server check karein.", "system");
    }
    sendBtn.disabled = false;
  }

  sendBtn.onclick = () => handleSend();
  if (micBtn && voiceIn) {
    micBtn.onclick = () => {
      if (!voiceIn.listening) voiceIn.start();
    };
  }
  input.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !voiceIn?.listening) {
      e.preventDefault();
      handleSend();
    }
  };
  document.querySelectorAll(".chip").forEach((c) => {
    c.onclick = () => ask(c.dataset.q);
  });
  if (resetBtn) resetBtn.onclick = resetChat;
}
