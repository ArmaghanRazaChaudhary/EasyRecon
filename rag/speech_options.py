"""Speech provider catalog — swap via .env, no code changes per pharmacy."""

from __future__ import annotations

import os
from typing import Any

SPEECH_CATALOG: dict[str, Any] = {
    "stt": {
        "azure_ur_pk": {
            "label": "Azure Speech — Urdu Pakistan (recommended)",
            "env": "SPEECH_STT_PROVIDER=azure\nAZURE_SPEECH_KEY=your_key\nAZURE_SPEECH_REGION=southeastasia\nAZURE_SPEECH_LANGUAGE=ur-PK",
            "accuracy_urdu": "excellent",
            "offline": False,
            "cost": "free tier 5 audio hours/month, then pay-as-you-go",
            "recommended_pakistan": True,
            "notes": "Most used in Pakistan enterprise apps. Phrase hints from your medicine DB.",
        },
        "local_whisper": {
            "label": "Local Whisper (offline fallback)",
            "env": "SPEECH_STT_PROVIDER=local\nLOCAL_WHISPER_MODEL=small",
            "accuracy_urdu": "medium",
            "offline": True,
            "cost": "free",
        },
        "groq_whisper": {
            "label": "Groq Whisper API",
            "env": "SPEECH_STT_PROVIDER=groq",
            "accuracy_urdu": "high",
            "offline": False,
            "cost": "Groq free tier",
        },
    },
    "tts": {
        "azure_urdu_female": {
            "label": "Azure Neural — Urdu female Uzma (Pakistan)",
            "env": "SPEECH_TTS_PROVIDER=azure\nTTS_VOICE=ur-PK-UzmaNeural",
            "language": "ur-PK Urdu (not Hindi)",
            "gender": "female",
            "recommended_pakistan": True,
        },
        "azure_urdu_male": {
            "label": "Azure Neural — Urdu male Asad (Pakistan)",
            "env": "SPEECH_TTS_PROVIDER=azure\nTTS_VOICE=ur-PK-AsadNeural",
            "language": "ur-PK",
            "gender": "male",
        },
        "edge_urdu_female": {
            "label": "Edge TTS — Urdu female (free fallback, same voice)",
            "env": "SPEECH_TTS_PROVIDER=edge\nTTS_VOICE=ur-PK-UzmaNeural",
            "language": "ur-PK",
            "gender": "female",
            "cost": "free (unofficial API)",
        },
    },
}


def speech_recommendations() -> dict[str, str]:
    return {
        "pakistan_production": "SPEECH_STT_PROVIDER=azure + SPEECH_TTS_PROVIDER=azure + ur-PK-UzmaNeural",
        "setup_guide": "docs/AZURE_SPEECH_SETUP.md",
        "region_pakistan": "AZURE_SPEECH_REGION=southeastasia (Singapore, low latency)",
        "free_fallback": "SPEECH_FALLBACK=true uses Edge TTS if Azure key missing",
        "avoid": "pyttsx3 and hi-IN browser voices",
    }


def list_speech_options() -> dict[str, Any]:
    from rag.speech import speech_status

    return {
        "active": speech_status(),
        "catalog": SPEECH_CATALOG,
        "recommendations": speech_recommendations(),
        "current_env": {
            "SPEECH_STT_PROVIDER": os.getenv("SPEECH_STT_PROVIDER", "azure"),
            "SPEECH_TTS_PROVIDER": os.getenv("SPEECH_TTS_PROVIDER", "azure"),
            "AZURE_SPEECH_REGION": os.getenv("AZURE_SPEECH_REGION", "southeastasia"),
            "AZURE_SPEECH_LANGUAGE": os.getenv("AZURE_SPEECH_LANGUAGE", "ur-PK"),
            "TTS_VOICE": os.getenv("TTS_VOICE", "ur-PK-UzmaNeural"),
            "SPEECH_FALLBACK": os.getenv("SPEECH_FALLBACK", "true"),
        },
    }
