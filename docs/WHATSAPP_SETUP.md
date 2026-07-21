# EasyRecon WhatsApp Bot (Twilio)

Real WhatsApp chat for pharmacy demos — pharmacist messages your bot from their phone.

## Why Twilio sandbox first?

- Free for testing (no Meta Business verification wait)
- Works in Pakistan with `+92` numbers
- Webhook to your laptop via ngrok
- Production later: Twilio paid number or Meta Cloud API

## Setup (30 minutes)

### 1. Twilio account

1. Sign up at https://www.twilio.com/try-twilio
2. Console → **Messaging** → **Try it out** → **Send a WhatsApp message**
3. Note **Sandbox number** (usually `+1 415 523 8886`)
4. Note **join code** (e.g. `join word-word`)

### 2. Environment

Add to `.env`:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_PHARMACY_NAME=Bismillah Medical Store
```

Find SID and token on Twilio Console home page.

### 3. Install + run server

```powershell
cd c:\Users\GNG\Desktop\EasyRecon
pip install twilio
python -m api.main
```

Check: http://127.0.0.1:8000/whatsapp/status → `"configured": true`

### 4. Expose webhook (ngrok)

```powershell
ngrok http 8000
```

Copy the `https://xxxx.ngrok-free.app` URL.

Twilio Console → WhatsApp Sandbox → **Sandbox settings**:

- **When a message comes in:** `https://xxxx.ngrok-free.app/whatsapp/webhook`
- Method: **POST**

Save.

### 5. Join sandbox (your phone + pharmacist)

On WhatsApp, send to Twilio sandbox number:

```
join <your-sandbox-code>
```

Pharmacist does the same from their phone (each tester must join once).

### 6. Test

Message the sandbox number:

- `help` — menu
- `report` — instant daily reconciliation (no AI)
- `Panadol pari hai?` — full AI answer (10–30 sec, you'll get "Soch raha hoon..." first)

## Demo day tips

| Do | Don't |
|----|--------|
| Keep laptop + Ollama + ngrok running | Close laptop lid (sleep kills tunnel) |
| Test one question before meeting | Assume sandbox works without join |
| Say "sample store data" | Pretend it's their real POS yet |
| Use `report` for instant wow | Only show slow AI questions first |

## Commands

| Message | Action |
|---------|--------|
| `report` / `hisaab` / `daily` | Daily reconciliation text |
| `help` / `start` | Help menu |
| Anything else | EasyRecon AI Q&A |

## Production path (later)

1. **Twilio WhatsApp Sender** — apply for business profile (~PKR usage per message)
2. **Meta WhatsApp Cloud API** — direct, often cheaper at scale
3. Map `From` phone → pharmacy tenant in database
4. Schedule **Subah 7** report via cron + outbound message

## Troubleshooting

- **No reply:** check ngrok still running, webhook URL in Twilio, server logs
- **503 on webhook:** Twilio keys missing in `.env`
- **"Thinking" then nothing:** Ollama down or Groq key invalid — check `/health`
- **Pharmacist can't message:** they must send `join ...` to sandbox first
