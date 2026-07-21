# EasyRecon

### Ask your pharmacy books questions in Roman Urdu — get SQL-backed answers, not hallucinations.

EasyRecon is a **local-first pharmacy reconciliation assistant** for Pakistan retail pharmacies. Owners ask things like *“Aaj cash short kyun hai?”* and the system routes intent → generates safe SQL → runs it on a SQLite ledger → answers in natural Roman Urdu (with optional voice + WhatsApp).

Built for real shop workflows: cash drawer vs POS, stock vs ledger, supplier payables, udhaar, expiry, FBR gaps — with a synthetic “Bismillah Medical Store” dataset so you can demo without client data.

---

## What it does

| Capability | How it works |
|------------|----------------|
| **Natural language → SQL** | Local **Ollama** (default `qwen3.5:27b`) writes SQL; Python executes it (LLM never holds a DB connection) |
| **Fast intent / answers** | **Groq** for intent, scope, and Roman Urdu explanations |
| **Reconciliation-ready schema** | Cash register diffs, stock ledger, purchases, sales, returns, expenses, DRAP / FBR fields |
| **Planted discrepancies** | Generator injects realistic flags (`cash_short`, `stock_mismatch`, overdue suppliers, …) for RAG eval |
| **Web chat UI** | FastAPI + static `web/` — ask, see SQL, browse tabular results |
| **Speech** | Azure Speech (ur-PK) or local Whisper / edge-tts fallbacks |
| **WhatsApp reports** | Twilio sandbox/production hooks for daily recon digests |

```text
Question (Roman Urdu / English)
        │
        ▼
   Groq intent + scope
        │
        ▼
   Ollama → SQL  ──►  Python executes on SQLite
        │
        ▼
   Deterministic table / Groq Roman Urdu answer
        │
        ▼
   Web UI · CLI · WhatsApp · TTS
```

---

## Tech stack

| Layer | Technology |
|-------|------------|
| API | **FastAPI**, Uvicorn, Pydantic |
| LLMs | **Ollama** (local SQL), **Groq** (intent + explanations) |
| Data | **SQLite** runtime · **PostgreSQL-shaped** schema in `schema/schema.sql` |
| Synthetic data | **Faker** + custom Pakistan pharmacy generator |
| Speech | Azure Cognitive Speech · faster-whisper · edge-tts · pyttsx3 |
| Messaging | Twilio WhatsApp API |
| Frontend | Vanilla JS chat UI (`web/`) |

---

## Privacy & what is (not) in this repo

| Path | Status |
|------|--------|
| `.env` | **Local only** — API keys never committed |
| `*.db` | **Generated locally** — not in git |
| `data/sessions/` | **Local chat memory** — gitignored |
| `.env.example` | Safe placeholders |
| `scripts/generate_pharmacy_db.py` | Rebuilds the demo DB anytime |

> If you ever pasted a real Groq/Azure/Twilio key into `.env`, rotate it after publishing — this push does **not** include `.env`.

---

## Quick start

### 1. Python deps

```bash
cd EasyRecon
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# add GROQ_API_KEY from https://console.groq.com
```

### 2. Generate synthetic pharmacy DB

```bash
python scripts/generate_pharmacy_db.py
# → data/bismillah_pharmacy.db
```

| Scale | Months | ~Sales | Use |
|-------|--------|--------|-----|
| `small` | 6 | ~12k | Fast iteration |
| `medium` | 9 | ~25k | Dev |
| `large` | 12 | ~40k+ | **Default demo** |
| `xlarge` | 18 | ~90k+ | Stress |

```bash
python scripts/generate_pharmacy_db.py --scale xlarge --months 18
```

### 3. Pull local SQL model (one-time, large download)

```bash
ollama pull qwen3.5:27b
```

### 4. Ask from CLI

```bash
# No AI — daily WhatsApp-style report
python scripts/ask.py --whatsapp

# Needs Ollama + Groq
python scripts/ask.py "Aaj cash short kyun hai?"
python scripts/ask.py "Expired medicines abhi bhi stock mein hain?"
```

### 5. Run the API + UI

```bash
python -m api.main
```

- UI: http://127.0.0.1:8000/  
- Health: http://127.0.0.1:8000/health  
- Ask: `POST /ask` with `{"question":"…"}`  

Optional: Azure speech (`docs/AZURE_SPEECH_SETUP.md`) · WhatsApp (`docs/WHATSAPP_SETUP.md`).

---

## Domain model (Pakistan retail)

**Core tables:** `medicines`, `stock`, `stock_ledger`, `suppliers`, `purchases`, `purchase_items`, `sales`, `sale_items`, `customers`, `cash_register`, `supplier_payments`, `returns`, `expenses`

**Local specifics:** `drap_reg_no`, batch/`expiry_date` (FEFO), `fbr_qr_code`, payment methods (`cash`, `card`, `udhaar`, JazzCash, Easypaisa), `cash_register.difference` as the #1 recon signal.

**Built-in flag types** (see `reconciliation_flags`): cash short, stock mismatch, unpaid supplier invoices, duplicate payments, credit overdue, expired stock, return not in register, missing FBR QR, payment amount mismatch, DRAP price anomalies.

---

## Sample questions

```
Aaj cash short kyun hai?
Kon se supplier ke unpaid invoices 30 din se zyada purane hain?
Panadol ka stock ledger se match kyun nahi kar raha?
Duplicate supplier payment dikhao
Allied Traders ko kitna paisa dena baqi hai?
FBR QR missing wali invoices kaun si hain?
```

---

## Repo map

```text
EasyRecon/
├── api/                 # FastAPI app + WhatsApp webhook routes
├── rag/                 # SQL agent, prompts, memory, speech, reports
├── web/                 # Chat UI (HTML/CSS/JS)
├── schema/schema.sql    # Canonical SQL schema
├── scripts/
│   ├── generate_pharmacy_db.py
│   ├── ask.py
│   └── sample_queries.sql
├── docs/                # Azure Speech + WhatsApp setup
├── data/                # Local DB + sessions (gitignored content)
├── .env.example
└── requirements.txt
```

---

## Design notes (for engineers / hiring managers)

- **Tool use, not chat-with-DB:** the model proposes SQL; a Python sandbox executes read-only-style queries and returns rows.
- **Hybrid latency:** canned SQL + deterministic formatters skip a second LLM round-trip when results are simple tables/scalars (`FAST_ANSWERS`).
- **Session memory** per pharmacy slug for follow-ups (“unhe phone karo”) without leaking across shops.
- **Synthetic-first:** ship a generator with ground-truth flags so eval isn’t blocked on real pharmacy exports.
- **Honest scope:** this is an assistant for ledger Q&A and recon surfacing — not a full ERP replacement.

---

## License

MIT — see [LICENSE](LICENSE). Third-party model/API terms (Ollama models, Groq, Azure, Twilio) apply separately.
