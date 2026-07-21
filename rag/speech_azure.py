"""Azure Cognitive Services Speech — ur-PK STT/TTS (standard in Pakistan production)."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") or os.getenv("AZURE_SPEECH_SUBSCRIPTION_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "southeastasia")
AZURE_SPEECH_LANGUAGE = os.getenv("AZURE_SPEECH_LANGUAGE", "ur-PK")
AZURE_TTS_VOICE = os.getenv("TTS_VOICE", "ur-PK-UzmaNeural")


class AzureSpeechError(RuntimeError):
    pass


def azure_sdk_ready() -> bool:
    try:
        import azure.cognitiveservices.speech as speechsdk  # noqa: F401

        return True
    except ImportError:
        return False


def azure_configured() -> bool:
    return bool(AZURE_SPEECH_KEY.strip()) and azure_sdk_ready()


def _speech_config() -> Any:
    if not AZURE_SPEECH_KEY:
        raise AzureSpeechError(
            "AZURE_SPEECH_KEY not set. Create free tier at "
            "https://portal.azure.com → Speech Services (region: southeastasia)."
        )
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise AzureSpeechError(
            "Install: pip install azure-cognitiveservices-speech"
        ) from exc
    return speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)


def _attach_phrase_hints(recognizer: Any) -> None:
    """Boost pharmacy medicine names from DB — data-driven, not hardcoded rules."""
    try:
        import azure.cognitiveservices.speech as speechsdk
        from rag.pharmacy_vocab import medicine_phrase_list

        grammar = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
        for phrase in medicine_phrase_list():
            grammar.addPhrase(phrase)
        grammar.addPhrase("Panadol")
        grammar.addPhrase("stock")
        grammar.addPhrase("sales")
    except Exception:
        pass


def transcribe_wav(wav_path: Path, *, language: str | None = None) -> str:
    import azure.cognitiveservices.speech as speechsdk

    lang = language or AZURE_SPEECH_LANGUAGE
    speech_config = _speech_config()
    speech_config.speech_recognition_language = lang
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
        "15000",
    )
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
        "3000",
    )

    audio_config = speechsdk.audio.AudioConfig(filename=str(wav_path))
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config, audio_config=audio_config
    )
    _attach_phrase_hints(recognizer)

    result = recognizer.recognize_once_async().get()
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        text = (result.text or "").strip()
        if text:
            return text

    if result.reason == speechsdk.ResultReason.NoMatch:
        return _transcribe_continuous(wav_path, language=lang)

    if result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        raise AzureSpeechError(
            f"Azure STT canceled: {details.reason} — {details.error_details or ''}"
        )
    raise AzureSpeechError("Azure STT could not understand audio.")


def _transcribe_continuous(wav_path: Path, *, language: str) -> str:
    import azure.cognitiveservices.speech as speechsdk

    speech_config = _speech_config()
    speech_config.speech_recognition_language = language
    audio_config = speechsdk.audio.AudioConfig(filename=str(wav_path))
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config, audio_config=audio_config
    )
    _attach_phrase_hints(recognizer)

    parts: list[str] = []
    done = threading.Event()

    def on_recognized(evt: Any) -> None:
        import azure.cognitiveservices.speech as speechsdk

        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            t = (evt.result.text or "").strip()
            if t:
                parts.append(t)

    def on_stopped(_evt: Any) -> None:
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_stopped)
    recognizer.canceled.connect(on_stopped)

    recognizer.start_continuous_recognition_async().get()
    done.wait(timeout=120)
    recognizer.stop_continuous_recognition_async().get()

    text = " ".join(parts).strip()
    if not text:
        raise AzureSpeechError("Azure STT: kuch sunai nahi diya — dubara boliye.")
    return text


def synthesize(text: str, *, voice: str | None = None) -> tuple[bytes, str]:
    import azure.cognitiveservices.speech as speechsdk

    spoken = text.strip()
    if not spoken:
        raise AzureSpeechError("Nothing to speak.")

    speech_config = _speech_config()
    speech_config.speech_synthesis_voice_name = voice or AZURE_TTS_VOICE
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=None
    )
    result = synthesizer.speak_text_async(spoken).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return bytes(result.audio_data), "audio/mpeg"

    if result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        raise AzureSpeechError(
            f"Azure TTS canceled: {details.reason} — {details.error_details or ''}"
        )
    raise AzureSpeechError("Azure TTS failed.")
