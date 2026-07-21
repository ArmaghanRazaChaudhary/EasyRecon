# Azure Speech — Pakistan (ur-PK)

EasyRecon uses **Azure Cognitive Services Speech** for mic input and bot voice — the standard choice for Urdu in Pakistan production apps.

## 1. Create Azure Speech resource

1. Go to [Azure Portal](https://portal.azure.com)
2. **Create a resource** → **AI + Machine Learning** → **Speech**
3. Region: **Southeast Asia** (Singapore) — good latency for Pakistan
4. Pricing: **Free F0** (5 audio hours/month STT + 500k chars TTS) for demo; **S0** for production
5. Copy **Key 1** and **Region**

## 2. Add to `.env`

```env
SPEECH_STT_PROVIDER=azure
SPEECH_TTS_PROVIDER=azure
AZURE_SPEECH_KEY=your_key_here
AZURE_SPEECH_REGION=southeastasia
AZURE_SPEECH_LANGUAGE=ur-PK
TTS_VOICE=ur-PK-UzmaNeural
SPEECH_FALLBACK=true
```

**Female Urdu voice:** `ur-PK-UzmaNeural` (default)  
**Male Urdu voice:** `ur-PK-AsadNeural`

## 3. Install SDK

```bash
pip install azure-cognitiveservices-speech
```

## 4. Verify

Restart API, then open:

- `GET http://127.0.0.1:8000/speech/status` — should show `"stt_provider": "azure"`, `"recommended_pakistan": true`
- `/demo` — mic → stop → send; toggle speaker for Uzma voice

## Fallback

If `AZURE_SPEECH_KEY` is missing, `SPEECH_FALLBACK=true` uses **Edge TTS** (same Uzma voice, unofficial) and **local Whisper** for STT.

## Medicine name accuracy

Azure STT gets **phrase hints** from your pharmacy database (`medicines` table) — not hardcoded rules. New medicines in POS automatically improve recognition.

## Cost (approx)

| Tier | STT | TTS |
|------|-----|-----|
| Free F0 | 5 hours/month | 0.5M chars/month |
| S0 | ~$1/hour | ~$16/1M chars |

For one pharmacy owner demo, free tier is usually enough.
