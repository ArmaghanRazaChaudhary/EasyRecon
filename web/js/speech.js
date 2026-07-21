/** EasyRecon voice — manual stop-and-send (ChatGPT style) + local Whisper STT */

const SpeechFeatures = (function () {
  const AUTO_SPEAK_KEY = "easyrecon_auto_speak";
  const SPEECH_LANG = "ur-PK";
  // Urdu only — never fall back to hi-IN (sounds Hindi)
  const SPEECH_LANG_FALLBACKS = ["ur-PK", "ur"];

  function supportsBrowserSTT() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function supportsBrowserTTS() {
    return "speechSynthesis" in window;
  }

  function plainTextForSpeech(text) {
    if (!text) return "";
    const lines = [];
    for (const line of text.split("\n")) {
      const stripped = line.trim();
      if (!stripped) continue;
      if (stripped.startsWith("|") && stripped.endsWith("|")) {
        if (lines.length) break;
        continue;
      }
      let cleaned = stripped
        .replace(/\*\*(.+?)\*\*/g, "$1")
        .replace(/\*(.+?)\*/g, "$1")
        .replace(/_(.+?)_/g, "$1");
      lines.push(cleaned);
    }
    return lines.slice(0, 6).join(". ").slice(0, 600);
  }

  function pickVoice() {
    if (!supportsBrowserTTS()) return null;
    const voices = window.speechSynthesis.getVoices();
    const preferFemale = (v) => /female|zira|hazel|samantha|uzma|gul|urdu/i.test(v.name || "");
    for (const lang of SPEECH_LANG_FALLBACKS) {
      const matches = voices.filter(
        (v) => v.lang && v.lang.toLowerCase().startsWith(lang.toLowerCase())
      );
      if (matches.length) return matches.find(preferFemale) || matches[0];
    }
    return null;
  }

  class VoiceOutput {
    constructor() {
      this._autoSpeak = localStorage.getItem(AUTO_SPEAK_KEY) === "1";
      this._audio = null;
      if (supportsBrowserTTS()) {
        window.speechSynthesis.onvoiceschanged = () => pickVoice();
      }
    }

    getAutoSpeak() {
      return this._autoSpeak;
    }

    setAutoSpeak(on) {
      this._autoSpeak = !!on;
      localStorage.setItem(AUTO_SPEAK_KEY, on ? "1" : "0");
      if (!on) this.stop();
    }

    stop() {
      if (supportsBrowserTTS()) window.speechSynthesis.cancel();
      if (this._audio) {
        this._audio.pause();
        this._audio = null;
      }
    }

    async speak(text, { preferServer = true } = {}) {
      const plain = plainTextForSpeech(text);
      if (!plain) return;
      this.stop();

      const ok = await this._speakServer(plain);
      if (ok) return;

      if (supportsBrowserTTS()) {
        this._speakBrowser(plain);
      }
    }

    _speakBrowser(text) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = SPEECH_LANG;
      u.rate = 0.95;
      const voice = pickVoice();
      if (voice) u.voice = voice;
      window.speechSynthesis.speak(u);
    }

    async _speakServer(text) {
      try {
        const res = await fetch("/speech/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!res.ok) return false;
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        this._audio = audio;
        audio.onended = () => URL.revokeObjectURL(url);
        await audio.play();
        return true;
      } catch {
        return false;
      }
    }
  }

  class VoiceInput {
    constructor({ inputEl, onStateChange, onError }) {
      this.inputEl = inputEl;
      this.onStateChange = onStateChange || (() => {});
      this.onError = onError || (() => {});
      this._recording = false;
      this._stream = null;
      this._recorder = null;
      this._chunks = [];
      this._mime = "audio/webm";
      this._stopResolve = null;
    }

    get listening() {
      return this._recording;
    }

    async start() {
      if (this._recording) return;
      if (!navigator.mediaDevices?.getUserMedia) {
        this.onError("Is browser mein mic support nahi.");
        return;
      }
      try {
        this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this._chunks = [];
        this._mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm";
        this._recorder = new MediaRecorder(this._stream, { mimeType: this._mime });
        this._recorder.ondataavailable = (e) => {
          if (e.data.size) this._chunks.push(e.data);
        };
        this._recorder.onstop = () => this._onRecorderStop();
        this._recorder.start(250);
        this._recording = true;
        this.onStateChange(true);
        if (this.inputEl) {
          this.inputEl.value = "";
          this.inputEl.placeholder = "Bol rahe hain… jab ho jaye stop ⏹ dabayein";
          this.inputEl.readOnly = true;
        }
      } catch {
        this.onError("Mic access nahi mila — browser settings check karein.");
        this._cleanupStream();
      }
    }

    async stopAndTranscribe() {
      if (!this._recording) return "";
      return new Promise((resolve, reject) => {
        this._stopResolve = { resolve, reject };
        try {
          if (this._recorder && this._recorder.state !== "inactive") {
            this._recorder.stop();
          } else {
            this._onRecorderStop().then(() => resolve("")).catch(reject);
          }
        } catch (err) {
          reject(err);
        }
      });
    }

    cancel() {
      if (!this._recording) return;
      this._stopResolve = null;
      try {
        if (this._recorder && this._recorder.state !== "inactive") {
          this._recorder.stop();
        }
      } catch {
        /* ignore */
      }
      this._chunks = [];
      this._finishRecording("");
    }

    async _onRecorderStop() {
      this._cleanupStream();
      const blob = new Blob(this._chunks, { type: this._mime });
      this._chunks = [];

      if (!this._stopResolve) {
        this._finishRecording("");
        return;
      }

      const { resolve, reject } = this._stopResolve;
      this._stopResolve = null;

      if (blob.size < 500) {
        this._finishRecording("");
        reject(new Error("Bohot choti recording — dubara boliye."));
        return;
      }

      if (this.inputEl) this.inputEl.placeholder = "Sun raha hoon…";
      try {
        const text = await this._uploadAndTranscribe(blob);
        this._finishRecording(text);
        resolve(text);
      } catch (err) {
        this._finishRecording("");
        reject(err);
      }
    }

    _finishRecording(text) {
      this._recording = false;
      this.onStateChange(false);
      if (this.inputEl) {
        this.inputEl.readOnly = false;
        this.inputEl.placeholder = "Roman Urdu mein poochhein… ya mic dabayein";
        if (text) this.inputEl.value = text;
      }
    }

    _cleanupStream() {
      if (this._stream) {
        this._stream.getTracks().forEach((t) => t.stop());
        this._stream = null;
      }
    }

    async _uploadAndTranscribe(blob) {
      const form = new FormData();
      form.append("file", blob, "voice.webm");
      const res = await fetch("/speech/transcribe", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || "Transcribe fail");
      const text = (data.text || "").trim();
      if (!text) throw new Error("Kuch sunai nahi diya — dubara try karein.");
      return text;
    }
  }

  return {
    VoiceInput,
    VoiceOutput,
    plainTextForSpeech,
    supportsBrowserSTT,
    supportsBrowserTTS,
  };
})();
