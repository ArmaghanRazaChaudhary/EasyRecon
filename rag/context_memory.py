"""Tiered session context — bounded tokens, structured memory, always-on learning."""

from __future__ import annotations

import json
import os
import re
from typing import Any

# Bounded context (not full history — linear token cost)
CONTEXT_MAX_TURNS = int(os.getenv("CONTEXT_MAX_TURNS", "8"))
MSG_SNIPPET_LEN = int(os.getenv("MSG_SNIPPET_LEN", "400"))
SUMMARY_INTERVAL = int(os.getenv("SUMMARY_INTERVAL", "10"))

REFERENTIAL_RE = re.compile(
    r"\b(un|in|wo|wahi|wohi|yeh|ye|in ka|un ka|us ka|is ka|in ki|un ki|"
    r"above|those|these|same|pehle wale|us list|is list|in medicines|un medicines|"
    r"in sab|un sab|total of these|in ka total|un ka total)\b",
    re.IGNORECASE,
)

ENTITY_KEYS = ("name", "medicine_name", "company_name", "customer_name", "Medicine_Name")


def build_context_memory(
    intent: dict[str, Any] | None,
    rows: list | None,
    columns: list | None,
) -> dict[str, Any]:
    """Compact structured memory — small token footprint for SQL + intent."""
    intent = intent or {}
    memory: dict[str, Any] = {
        "topic": intent.get("topic"),
        "date_scope": intent.get("date_scope"),
        "entity": intent.get("entity"),
        "question_type": intent.get("question_type"),
        "clarified_question": intent.get("clarified_question"),
    }
    if rows:
        memory["row_count"] = len(rows)
        entities: list[str] = []
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            for key in ENTITY_KEYS:
                val = row.get(key)
                if val and str(val) not in entities:
                    entities.append(str(val)[:80])
                    break
        if entities:
            memory["entities"] = entities[:8]
        memory["sample_rows"] = rows[:5]
    if columns:
        memory["columns"] = columns[:12]
    return memory


def is_referential_query(text: str) -> bool:
    return bool(REFERENTIAL_RE.search(text))


def format_structured_memory_block(session: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = (session.get("conversation_summary") or "").strip()
    if summary:
        lines.append(f"CONVERSATION SUMMARY (older context):\n{summary}")

    cm = session.get("context_memory") or {}
    if cm:
        meta = {k: v for k, v in cm.items() if k not in ("sample_rows", "columns")}
        lines.append("LAST QUERY CONTEXT (owner may refer with un/wo/in):")
        lines.append(json.dumps(meta, ensure_ascii=False, default=str))
        sample = cm.get("sample_rows")
        if sample:
            lines.append("LAST RESULT ROWS:")
            lines.append(json.dumps(sample, ensure_ascii=False, default=str))

    if session.get("last_sql"):
        lines.append(f"LAST SQL (reuse or extend if referential):\n{session['last_sql'][:600]}")
    return "\n".join(lines)


def format_owner_learning_block(session_id: str | None, question: str) -> str:
    """Always injected — preferences + global corrections (auto-learning)."""
    from rag.memory import format_corrections_for_prompt, format_preferences_for_prompt
    from rag.memory import get_merged_preferences, get_pharmacy_learned_preferences
    from rag.memory import relevant_corrections

    prefs = get_merged_preferences(session_id)
    pharmacy_prefs = get_pharmacy_learned_preferences(session_id)

    lines = [
        "OWNER LEARNING (always apply — learned from this owner):",
        f"- answer format: {prefs.get('format', 'auto')}",
        f"- brevity: {prefs.get('brevity', 'normal')}",
    ]
    if pharmacy_prefs.get("notes"):
        lines.append(f"- owner notes: {pharmacy_prefs['notes']}")

    hint = format_preferences_for_prompt(session_id)
    if hint:
        lines.append(hint)

    corrections = format_corrections_for_prompt(relevant_corrections(question))
    if corrections:
        lines.append(corrections)

    return "\n".join(lines)


def format_tiered_context(
    session: dict[str, Any],
    session_id: str | None,
    question: str,
    *,
    max_turns: int | None = None,
) -> str:
    """Sliding window + summary + structured memory + learning (bounded)."""
    max_turns = max_turns or CONTEXT_MAX_TURNS
    lines: list[str] = []

    if session.get("pharmacy_name"):
        lines.append(f"Pharmacy: {session['pharmacy_name']}")

    lines.append(format_owner_learning_block(session_id, question))

    structured = format_structured_memory_block(session)
    if structured:
        lines.append(structured)

    for msg in (session.get("messages") or [])[-max_turns * 2 :]:
        role = "Owner" if msg["role"] == "user" else "Assistant"
        content = (msg.get("content") or "")[:MSG_SNIPPET_LEN]
        lines.append(f"{role}: {content}")

    return "\n".join(lines)


def format_sql_memory_context(session: dict[str, Any], question: str) -> str:
    """Minimal context for SQL step — structured only, no full chat."""
    parts = [format_owner_learning_block(session.get("session_id"), question)]
    structured = format_structured_memory_block(session)
    if structured:
        parts.append(structured)
    if is_referential_query(question):
        parts.append(
            "REFERENTIAL QUERY: owner refers to previous result. "
            "Filter SQL using LAST RESULT ROWS / entities / last date_scope. "
            "Do not ignore prior context."
        )
    return "\n\n".join(parts)


def maybe_refresh_conversation_summary(session_id: str | None, session: dict[str, Any]) -> dict[str, Any]:
    """Rolling summary every N turns — fixed ~200-400 tokens, not unbounded."""
    messages = session.get("messages") or []
    n = len(messages)
    last_at = session.get("summary_at_message_count") or 0

    if n < 6:
        return session
    if n - last_at < SUMMARY_INTERVAL and session.get("conversation_summary"):
        return session

    try:
        from rag.llm import chat_intent

        chunk = messages[-(SUMMARY_INTERVAL * 2) :]
        transcript = "\n".join(
            f"{'Owner' if m['role'] == 'user' else 'Bot'}: {(m.get('content') or '')[:180]}"
            for m in chunk
        )
        prefs = session.get("preferences") or {}
        response = chat_intent(
            [
                {
                    "role": "system",
                    "content": (
                        "Write 3-4 short Roman Urdu lines (Latin script) summarizing this pharmacy chat. "
                        "Include: topics discussed, date filters used, medicine/supplier names, "
                        f"owner preferences (format={prefs.get('format')}, brevity={prefs.get('brevity')}). "
                        "No bullet lists."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            temperature=0.1,
            timeout=45.0,
        )
        session["conversation_summary"] = response.strip()[:800]
        session["summary_at_message_count"] = n
    except Exception:
        pass
    return session
