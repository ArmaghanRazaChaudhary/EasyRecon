"""Speech — Azure ur-PK (Pakistan default) with edge/groq/local fallbacks."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SPEECH_STT_PROVIDER = os.getenv("SPEECH_STT_PROVIDER", "azure").lower()
SPEECH_TTS_PROVIDER = os.getenv("SPEECH_TTS_PROVIDER", "azure").lower()
SPEECH_FALLBACK = os.getenv("SPEECH_FALLBACK", "true").lower() in ("1", "true", "yes")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

TTS_VOICE = os.getenv("TTS_VOICE", "ur-PK-UzmaNeural")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))
TTS_RATE = int(os.getenv("TTS_RATE", "165"))

MAX_AUDIO_BYTES = int(os.getenv("SPEECH_MAX_AUDIO_BYTES", str(5 * 1024 * 1024)))
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "ur")
AZURE_SPEECH_LANGUAGE = os.getenv("AZURE_SPEECH_LANGUAGE", "ur-PK")

_whisper_model: Any = None
_ffmpeg_path: str | None = None


from rag.pharmacy_vocab import normalize_pharmacy_speech, whisper_initial_prompt


class SpeechError(RuntimeError):
    pass


def _resolve_ffmpeg() -> str | None:
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path
    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg_path = found
        return found
    try:
        import imageio_ffmpeg

        _ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        return _ffmpeg_path
    except ImportError:
        pass
    for pattern in (
        Path.home() / "AppData/Local/Microsoft/WinGet/Packages",
        Path("C:/ffmpeg/bin"),
    ):
        if not pattern.exists():
            continue
        for exe in pattern.rglob("ffmpeg.exe"):
            _ffmpeg_path = str(exe)
            return _ffmpeg_path
    return None


def _ensure_ffmpeg() -> None:
    ff = _resolve_ffmpeg()
    if not ff:
        raise SpeechError(
            "ffmpeg not found — needed for mic/webm audio. "
            "Install: winget install Gyan.FFmpeg — then restart terminal."
        )
    ff_dir = str(Path(ff).parent)
    if ff_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")


def _convert_to_wav(audio_path: Path) -> Path:
    """Normalize browser webm/ogg to wav for reliable Whisper decoding."""
    if audio_path.suffix.lower() == ".wav":
        return audio_path
    _ensure_ffmpeg()
    ff = _resolve_ffmpeg() or "ffmpeg"
    out_path = audio_path.with_suffix(".wav")
    cmd = [
        ff,
        "-y",
        "-i",
        str(audio_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode(errors="replace")[-400:]
        raise SpeechError(f"Audio conversion failed: {err or exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SpeechError("Audio conversion timed out.") from exc
    return out_path


def plain_text_for_speech(text: str) -> str:
    """Strip markdown/tables for TTS — keep intro lines only."""
    if not text:
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            if lines:
                break
            continue
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
        cleaned = re.sub(r"_(.+?)_", r"\1", cleaned)
        lines.append(cleaned)
    out = " ".join(lines[:6])
    return out[:TTS_MAX_CHARS].strip()


def _local_whisper_ready() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False


def _local_tts_ready() -> bool:
    try:
        import pyttsx3  # noqa: F401

        return True
    except ImportError:
        return False


def _edge_tts_ready() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except ImportError:
        return False


def _azure_ready() -> bool:
    from rag.speech_azure import azure_configured

    return azure_configured()


def _resolve_stt_provider() -> str:
    pref = SPEECH_STT_PROVIDER
    if pref == "azure" and _azure_ready():
        return "azure"
    if pref == "groq" and GROQ_API_KEY:
        return "groq"
    if pref == "local" and _local_whisper_ready():
        return "local"
    if SPEECH_FALLBACK:
        if _azure_ready():
            return "azure"
        if _local_whisper_ready():
            return "local"
        if GROQ_API_KEY:
            return "groq"
    return pref


def _resolve_tts_provider() -> str:
    pref = SPEECH_TTS_PROVIDER
    if pref == "azure" and _azure_ready():
        return "azure"
    if pref == "edge" and _edge_tts_ready():
        return "edge"
    if pref == "local" and _local_tts_ready():
        return "local"
    if SPEECH_FALLBACK:
        if _azure_ready():
            return "azure"
        if _edge_tts_ready():
            return "edge"
        if _local_tts_ready():
            return "local"
    return pref


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechError(
            "Local Whisper not installed. Run: pip install faster-whisper "
            "(ffmpeg recommended for webm audio)."
        ) from exc
    _whisper_model = WhisperModel(
        LOCAL_WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )
    return _whisper_model


def _write_temp_audio(audio_bytes: bytes, filename: str) -> Path:
    suffix = Path(filename).suffix or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.flush()
        return Path(tmp.name)
    finally:
        tmp.close()


def _transcribe_local(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    language: str | None = None,
) -> str:
    path = _write_temp_audio(audio_bytes, filename)
    wav_path: Path | None = None
    try:
        wav_path = _convert_to_wav(path)
        model = _get_whisper_model()
        lang = language or STT_LANGUAGE or None
        segments, _info = model.transcribe(
            str(wav_path),
            language=lang,
            beam_size=5,
            vad_filter=True,
            initial_prompt=whisper_initial_prompt(),
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
    finally:
        path.unlink(missing_ok=True)
        if wav_path and wav_path != path:
            wav_path.unlink(missing_ok=True)
    if not text:
        raise SpeechError("Could not understand audio — try again clearly.")
    return text


def _transcribe_groq(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
    language: str | None = None,
) -> str:
    if not GROQ_API_KEY:
        raise SpeechError("GROQ_API_KEY not set — set SPEECH_STT_PROVIDER=local for offline STT.")
    lang = language or STT_LANGUAGE
    data: dict[str, str] = {
        "model": GROQ_WHISPER_MODEL,
        "response_format": "json",
        "temperature": "0",
    }
    if lang:
        data["language"] = lang
    try:
        response = httpx.post(
            f"{GROQ_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (filename, audio_bytes, content_type)},
            data=data,
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SpeechError(f"Whisper error: {exc.response.text}") from exc
    except httpx.ConnectError as exc:
        raise SpeechError("Cannot reach Groq API for transcription.") from exc
    text = (response.json().get("text") or "").strip()
    if not text:
        raise SpeechError("Could not understand audio — try again clearly.")
    return text


def _transcribe_azure(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
) -> str:
    from rag.speech_azure import AzureSpeechError, transcribe_wav

    path = _write_temp_audio(audio_bytes, filename)
    wav_path: Path | None = None
    try:
        wav_path = _convert_to_wav(path)
        return transcribe_wav(wav_path, language=AZURE_SPEECH_LANGUAGE)
    except AzureSpeechError as exc:
        raise SpeechError(str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)
        if wav_path and wav_path != path:
            wav_path.unlink(missing_ok=True)


def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
    language: str | None = None,
) -> str:
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise SpeechError(f"Audio too large (max {MAX_AUDIO_BYTES // (1024 * 1024)} MB).")
    if not audio_bytes:
        raise SpeechError("Empty audio file.")

    provider = _resolve_stt_provider()
    if provider == "azure":
        raw = _transcribe_azure(audio_bytes, filename=filename)
    elif provider == "groq":
        raw = _transcribe_groq(
            audio_bytes, filename=filename, content_type=content_type, language=language
        )
    else:
        raw = _transcribe_local(audio_bytes, filename=filename, language=language)
    return normalize_pharmacy_speech(raw)


def _synthesize_local(text: str) -> tuple[bytes, str]:
    try:
        import pyttsx3
    except ImportError as exc:
        raise SpeechError(
            "Local TTS not installed. Run: pip install pyttsx3 — or use browser speaker in demo."
        ) from exc

    spoken = plain_text_for_speech(text)
    if not spoken:
        raise SpeechError("Nothing to speak.")

    engine = pyttsx3.init()
    engine.setProperty("rate", TTS_RATE)
    voices = engine.getProperty("voices")
    for voice in voices:
        name = (voice.name or "").lower()
        vid = (voice.id or "").lower()
        if "urdu" in name or "urdu" in vid or "hindi" in name or "english" in name:
            engine.setProperty("voice", voice.id)
            break

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        engine.save_to_file(spoken, str(out_path))
        engine.runAndWait()
        return out_path.read_bytes(), "audio/wav"
    finally:
        out_path.unlink(missing_ok=True)


async def _synthesize_edge_async(text: str, *, voice: str | None = None) -> tuple[bytes, str]:
    try:
        import edge_tts
    except ImportError as exc:
        raise SpeechError(
            "edge-tts not installed. Run: pip install edge-tts — or set SPEECH_TTS_PROVIDER=local."
        ) from exc

    spoken = plain_text_for_speech(text)
    if not spoken:
        raise SpeechError("Nothing to speak.")

    voice_id = voice or TTS_VOICE
    communicate = edge_tts.Communicate(spoken, voice_id)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    if not chunks:
        raise SpeechError("TTS produced no audio.")
    return b"".join(chunks), "audio/mpeg"


def _synthesize_azure(text: str, *, voice: str | None = None) -> tuple[bytes, str]:
    from rag.speech_azure import AzureSpeechError, synthesize as azure_synth

    spoken = plain_text_for_speech(text)
    if not spoken:
        raise SpeechError("Nothing to speak.")
    try:
        return azure_synth(spoken, voice=voice or TTS_VOICE)
    except AzureSpeechError as exc:
        raise SpeechError(str(exc)) from exc


def synthesize_speech(text: str, *, voice: str | None = None) -> tuple[bytes, str]:
    provider = _resolve_tts_provider()
    if provider == "azure":
        return _synthesize_azure(text, voice=voice)
    if provider == "edge":
        return asyncio.run(_synthesize_edge_async(text, voice=voice))
    return _synthesize_local(text)


def speech_status() -> dict[str, Any]:
    stt = _resolve_stt_provider()
    tts = _resolve_tts_provider()

    if stt == "azure":
        stt_ready = _azure_ready()
        stt_model = f"azure-{AZURE_SPEECH_LANGUAGE}"
    elif stt == "groq":
        stt_ready = bool(GROQ_API_KEY)
        stt_model = GROQ_WHISPER_MODEL
    else:
        stt_ready = _local_whisper_ready() and bool(_resolve_ffmpeg())
        stt_model = LOCAL_WHISPER_MODEL

    if tts == "azure":
        tts_ready = _azure_ready()
        tts_voice = TTS_VOICE
    elif tts == "edge":
        tts_ready = _edge_tts_ready()
        tts_voice = TTS_VOICE
    else:
        tts_ready = _local_tts_ready()
        tts_voice = "pyttsx3 (system voices)"

    return {
        "stt_provider": stt,
        "stt_ready": stt_ready,
        "stt_model": stt_model,
        "stt_language": AZURE_SPEECH_LANGUAGE if stt == "azure" else STT_LANGUAGE,
        "stt_device": WHISPER_DEVICE if stt == "local" else None,
        "tts_provider": tts,
        "tts_ready": tts_ready,
        "tts_voice": tts_voice,
        "azure_region": os.getenv("AZURE_SPEECH_REGION", "southeastasia"),
        "azure_configured": _azure_ready(),
        "fallback_enabled": SPEECH_FALLBACK,
        "ffmpeg": _resolve_ffmpeg(),
        "offline": stt == "local" and tts == "local",
        "recommended_pakistan": stt == "azure" and tts == "azure",
    }
