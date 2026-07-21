"""Intent + scope via LLM — minimal rules; preferences & corrections from memory."""

from __future__ import annotations

import json
import re
from typing import Any

from rag.llm import LLMError, chat_intent
from rag.memory import (
    format_corrections_for_prompt,
    format_preferences_for_prompt,
    format_session_context,
    relevant_corrections,
)

_OFF_TOPIC_FALLBACKS: dict[str, list[str]] = {
    "greeting": [
        "Wa Alaikum Assalam! Main EasyRecon hoon — cash, stock, sales ke bare mein poochhein?",
    ],
    "weather": [
        "Mausam ka data mere paas nahi — aaj ki sale ya stock check kar sakta hoon.",
    ],
    "personal": [
        "Yeh personal baat hai — main sirf aap ki pharmacy ka data bata sakta hoon.",
    ],
    "general_knowledge": [
        "General knowledge mere scope se bahar — apni dukaan ka data poochhein.",
    ],
    "off_topic": [
        "Yeh store se related nahi — cash, stock, supplier, udhaar try karein.",
    ],
}

ANALYZE_SYSTEM_BASE = """You analyze pharmacy owner messages (Pakistan: Roman Urdu, English, typos, voice errors).

Output ONLY JSON in ```json``` block.

Use RECENT CONVERSATION and OWNER LEARNING blocks in context — infer meaning from full dialogue, never from fixed phrase lists.

SCOPE: pharmacy business (sales, stock, cash, suppliers, udhaar, expiry, invoices).
Also IN SCOPE: questions about EasyRecon itself (Groq, AI, integration, how it works) — category "system".
OUT OF SCOPE: weather, personal/leave chat, insurance claims, jokes, politics, unrelated general knowledge, medical advice.

Roman Urdu date words (map to date_scope, NOT entity):
- aaj → today, kal → yesterday, parso → day_before_yesterday
- iss week / is week → this_week, pichle week → last_week
- "4 din pehle" → specific_date + days_ago: 4
- iss month / is mahine → this_month

Roman Urdu "kia/kya" means WHAT — never set entity to "kia". For "stock mein kia hai" → topic stock, list/count, entity null.

If in_scope, return:{
  "in_scope": true,
  "reason": "...",
  "message_type": "query|correction|clarify|referential|preference_only",
  "refers_to_previous": false,
  "resolved_question": "exact business question for SQL (especially after correction/referential)",
  "preference_update": { "format": null, "brevity": null, "language": null },
  "category": "sales|stock|cash|supplier|customer|system|...",
  "topic": "sales|stock|cash|supplier|customer|employee|returns|general",
  "question_type": "count|rank|list|total|check|compare|explain|clarify",
  "date_scope": "today|yesterday|day_before_yesterday|this_week|last_week|this_month|last_month|last_7_days|last_30_days|all_time|specific_date|none",
  "days_ago": null,
  "entity": null,
  "metric": "plain English",
  "output_style": "auto|table|short|prose",
  "clarified_question": "one clear English sentence for SQL",
  "sql_hints": ["1-3 hints"]
}

MESSAGE TYPE (from conversation context):
- query | correction | clarify | referential | preference_only
- correction: owner rejected prior answer — set resolved_question for fresh SQL
- preference_only: owner only changed style/language — fill preference_update, no SQL

preference_update fields: format (table|prose), brevity (short|normal), language (roman_urdu).

Infer date_scope, output_style, question_type, entity from conversation — not keyword rules.
If out of scope:
{
  "in_scope": false,
  "reason": "...",
  "category": "off_topic|greeting|personal|weather|general_knowledge",
  "friendly_reply": "1-2 SHORT Roman Urdu sentences redirecting to pharmacy data — NEVER agree with or continue casual/off-topic chat (leave, claims, small talk)"
}
"""

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _parse_json(text: str) -> dict[str, Any]:
    match = JSON_BLOCK_RE.search(text)
    raw = match.group(1) if match else text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace:
            return json.loads(brace.group(0))
        raise


def build_analyze_system(question: str, session_context: str | None = None, session_id: str | None = None) -> str:
    prompt = ANALYZE_SYSTEM_BASE
    if session_context:
        # Tiered context always includes OWNER LEARNING (prefs + corrections)
        prompt += f"\n\nRECENT CONVERSATION:\n{session_context}"
    else:
        prompt += format_corrections_for_prompt(relevant_corrections(question))
        pref = format_preferences_for_prompt(session_id)
        if pref:
            prompt += f"\n\nOWNER PREFERENCES:\n{pref}"
    return prompt


def build_off_topic_reply(analysis: dict[str, Any]) -> str:
    category = analysis.get("category") or "off_topic"
    # Never trust LLM to improvise on personal/off-topic — it hallucinates agreeable chat
    if category in ("personal", "off_topic", "weather", "general_knowledge"):
        options = _OFF_TOPIC_FALLBACKS.get(category) or _OFF_TOPIC_FALLBACKS["off_topic"]
        question = analysis.get("original_question") or ""
        idx = sum(ord(c) for c in question) % len(options)
        return options[idx]
    reply = (analysis.get("friendly_reply") or "").strip()
    if reply and len(reply) > 20 and len(reply) < 200:
        return reply
    options = _OFF_TOPIC_FALLBACKS.get(category) or _OFF_TOPIC_FALLBACKS["off_topic"]
    question = analysis.get("original_question") or ""
    idx = sum(ord(c) for c in question) % len(options)
    return options[idx]


OFF_TOPIC_REPLY = _OFF_TOPIC_FALLBACKS["off_topic"][0]


def analyze_question(
    question: str,
    *,
    model: str | None = None,
    session_context: str | None = None,
    session_id: str | None = None,
    correction_context: str | None = None,
) -> dict[str, Any]:
    system = build_analyze_system(question, session_context=session_context, session_id=session_id)
    user_content = question
    if correction_context:
        user_content = f"{question}\n\nCORRECTION CONTEXT:\n{correction_context}"

    response = chat_intent(
        [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        model=model,
        temperature=0.0,
        timeout=90.0,
    )
    try:
        result = _parse_json(response)
    except json.JSONDecodeError:
        response = chat_intent(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"{user_content}\n\n"
                        "IMPORTANT: Return complete valid JSON only. Never leave fields null."
                    ),
                },
            ],
            model=model,
            temperature=0.0,
            timeout=90.0,
        )
        result = _parse_json(response)

    result["in_scope"] = bool(result.get("in_scope", False))
    result["original_question"] = question
    result.setdefault("message_type", "query")
    result.setdefault("refers_to_previous", False)
    if result.get("resolved_question"):
        result["clarified_question"] = result["resolved_question"]
    return result
