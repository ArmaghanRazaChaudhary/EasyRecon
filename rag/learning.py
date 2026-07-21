"""True learning layer — persisted owner data, not phrase hardcoding.

Learning stores (all grow from real usage):
  1. learned_corrections.jsonl  — owner said answer/SQL was wrong
  2. pharmacy index learned_preferences — format, brevity, language (survives new chat)
  3. session context_memory — last entities, rows, date_scope for referential queries
  4. conversation_summary — rolling Groq summary every N turns
  5. intent preference_update — Groq detects style change from natural language (no regex)

NOT learning (do not grow with phrases):
  - analyze.py phrase lists
  - canned_sql / fast_answer only for SQL→text truth (numbers from DB)
"""

from __future__ import annotations

from typing import Any

from rag.memory import (
    apply_preference_updates,
    format_corrections_for_prompt,
    format_preferences_for_prompt,
    get_merged_preferences,
    handle_correction,
    load_corrections,
    relevant_corrections,
)


def record_turn_learning(
    session_id: str | None,
    question: str,
    intent: dict[str, Any],
) -> dict[str, Any]:
    """Persist learnable signals from one Groq intent JSON — single entry point."""
    prefs = apply_preference_updates(session_id, intent.get("preference_update"))
    if intent.get("message_type") == "correction":
        handle_correction(question, session_id)
    return prefs


def learning_stats() -> dict[str, Any]:
    corrections = load_corrections()
    return {
        "corrections_count": len(corrections),
        "learning_sources": [
            "learned_corrections.jsonl",
            "pharmacy learned_preferences",
            "session context_memory",
            "conversation_summary",
            "intent preference_update",
        ],
        "recent_corrections": corrections[-3:],
    }


def format_learning_block(session_id: str | None, question: str) -> str:
    """Text block injected into analyze — corrections + prefs only."""
    parts: list[str] = []
    prefs = format_preferences_for_prompt(session_id)
    if prefs:
        parts.append(prefs)
    corrections = format_corrections_for_prompt(relevant_corrections(question))
    if corrections:
        parts.append(corrections)
    return "\n".join(parts)


def get_owner_prefs(session_id: str | None = None) -> dict[str, Any]:
    return get_merged_preferences(session_id)
