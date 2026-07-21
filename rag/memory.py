"""Per-pharmacy / per-owner session memory."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "data" / "sessions"
PHARMACIES_DIR = PROJECT_ROOT / "data" / "pharmacies"
PHARMACIES_INDEX = PHARMACIES_DIR / "index.json"
CORRECTIONS_PATH = PROJECT_ROOT / "data" / "learned_corrections.jsonl"
DEFAULT_SESSION_ID = "demo-pharmacy"
MAX_HISTORY = 40


def _ensure_dirs() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    PHARMACIES_DIR.mkdir(parents=True, exist_ok=True)
    CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)


def pharmacy_slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s\-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s[:56] or "pharmacy")


def load_pharmacy_index() -> dict[str, Any]:
    _ensure_dirs()
    if not PHARMACIES_INDEX.exists():
        return {}
    try:
        return json.loads(PHARMACIES_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_pharmacy_index(index: dict[str, Any]) -> None:
    _ensure_dirs()
    PHARMACIES_INDEX.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def bind_pharmacy_session(pharmacy_name: str, session_id: str) -> dict[str, Any]:
    """Map pharmacy -> active session (one ongoing chat per store)."""
    slug = pharmacy_slug(pharmacy_name)
    index = load_pharmacy_index()
    index[slug] = {
        "pharmacy_name": pharmacy_name,
        "pharmacy_slug": slug,
        "session_id": session_id,
        "updated_at": _now(),
    }
    save_pharmacy_index(index)
    return index[slug]


def get_pharmacy_binding(pharmacy_name: str) -> dict[str, Any] | None:
    slug = pharmacy_slug(pharmacy_name)
    return load_pharmacy_index().get(slug)


def get_or_create_pharmacy_session(pharmacy_name: str) -> dict[str, Any]:
    binding = get_pharmacy_binding(pharmacy_name)
    if binding:
        session = load_session(binding["session_id"])
        if session.get("messages") is not None:
            session["pharmacy_name"] = pharmacy_name
            session["pharmacy_slug"] = pharmacy_slug(pharmacy_name)
            return session

    sid = new_session_id()
    session = _empty_session(sid, pharmacy_name)
    _session_path(sid).write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    bind_pharmacy_session(pharmacy_name, sid)
    return session


def reset_pharmacy_session(pharmacy_name: str) -> dict[str, Any]:
    sid = new_session_id()
    session = _empty_session(sid, pharmacy_name)
    _session_path(sid).write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    bind_pharmacy_session(pharmacy_name, sid)
    return session


def _empty_session(session_id: str, pharmacy_name: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "pharmacy_name": pharmacy_name,
        "pharmacy_slug": pharmacy_slug(pharmacy_name),
        "messages": [],
        "last_question": None,
        "last_intent": None,
        "last_sql": None,
        "last_answer": None,
        "last_rows": None,
        "last_columns": None,
        "context_memory": None,
        "conversation_summary": None,
        "summary_at_message_count": 0,
        "preferences": {"format": "auto", "brevity": "short", "language": "roman_urdu"},
        "updated_at": _now(),
    }


def session_for_api(session: dict[str, Any]) -> dict[str, Any]:
    """Public session payload for UI restore."""
    return {
        "session_id": session.get("session_id"),
        "pharmacy_name": session.get("pharmacy_name"),
        "pharmacy_slug": session.get("pharmacy_slug"),
        "messages": session.get("messages") or [],
        "preferences": session.get("preferences") or {},
        "updated_at": session.get("updated_at"),
        "message_count": len(session.get("messages") or []),
    }


def _session_path(session_id: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", session_id)[:64]
    return SESSIONS_DIR / f"{safe}.json"


def normalize_session_id(session_id: str | None) -> str:
    if session_id and session_id.strip():
        return session_id.strip()
    return DEFAULT_SESSION_ID


def load_session(session_id: str | None = None) -> dict[str, Any]:
    _ensure_dirs()
    sid = normalize_session_id(session_id)
    path = _session_path(sid)
    if not path.exists():
        return _empty_session(sid, "Bismillah Medical Store")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("session_id", sid)
        data.setdefault("messages", [])
        data.setdefault("preferences", {"format": "auto", "brevity": "normal"})
        data.setdefault("context_memory", None)
        data.setdefault("conversation_summary", None)
        data.setdefault("summary_at_message_count", 0)
        return data
    except (json.JSONDecodeError, OSError):
        return {"session_id": sid, "messages": []}


def save_session_turn(
    session_id: str | None,
    *,
    question: str,
    answer: str,
    intent: dict | None = None,
    sql: str | None = None,
    pharmacy_name: str | None = None,
    rows: list | None = None,
    columns: list | None = None,
) -> dict[str, Any]:
    _ensure_dirs()
    sid = normalize_session_id(session_id)
    session = load_session(sid)
    if pharmacy_name:
        session["pharmacy_name"] = pharmacy_name
        session["pharmacy_slug"] = pharmacy_slug(pharmacy_name)
        bind_pharmacy_session(pharmacy_name, sid)

    session["messages"].append({"role": "user", "content": question, "at": _now()})
    session["messages"].append({"role": "assistant", "content": answer, "at": _now()})
    session["messages"] = session["messages"][-MAX_HISTORY:]

    session["last_question"] = question
    session["last_answer"] = answer
    session["last_intent"] = intent
    session["last_sql"] = sql
    if rows is not None:
        session["last_rows"] = rows[:8]
    if columns is not None:
        session["last_columns"] = columns

    from rag.context_memory import build_context_memory, maybe_refresh_conversation_summary

    session["context_memory"] = build_context_memory(intent, rows, columns)
    session = maybe_refresh_conversation_summary(sid, session)
    session["updated_at"] = _now()

    _session_path(sid).write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return session


def get_session_preferences(session_id: str | None = None) -> dict[str, Any]:
    session = load_session(session_id)
    prefs = session.get("preferences") or {}
    return {
        "format": prefs.get("format", "auto"),  # auto | table | prose
        "brevity": prefs.get("brevity", "normal"),  # normal | short
    }


def _persist_pharmacy_learned_prefs(pharmacy_name: str, prefs: dict[str, Any]) -> None:
    slug = pharmacy_slug(pharmacy_name)
    index = load_pharmacy_index()
    entry = dict(index.get(slug) or {})
    entry.setdefault("pharmacy_name", pharmacy_name)
    entry.setdefault("pharmacy_slug", slug)
    entry["learned_preferences"] = prefs
    entry["updated_at"] = _now()
    index[slug] = entry
    save_pharmacy_index(index)


def get_pharmacy_learned_preferences(session_id: str | None = None) -> dict[str, Any]:
    session = load_session(session_id)
    name = session.get("pharmacy_name")
    if not name:
        return {}
    binding = get_pharmacy_binding(name)
    return (binding or {}).get("learned_preferences") or {}


def get_merged_preferences(session_id: str | None = None) -> dict[str, Any]:
    """Session prefs + pharmacy-level learned prefs (survives new chat)."""
    session_prefs = get_session_preferences(session_id)
    pharmacy_prefs = get_pharmacy_learned_preferences(session_id)
    merged = dict(session_prefs)
    for key in ("format", "brevity", "language"):
        if pharmacy_prefs.get(key):
            merged[key] = pharmacy_prefs[key]
    return merged


def apply_preference_updates(
    session_id: str | None,
    updates: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply owner prefs from intent JSON — no phrase regex."""
    if not updates:
        return get_merged_preferences(session_id)
    session = load_session(session_id)
    prefs = dict(get_merged_preferences(session_id))
    for key in ("format", "brevity", "language"):
        val = updates.get(key)
        if val:
            prefs[key] = val
    session["preferences"] = prefs
    sid = normalize_session_id(session_id)
    _session_path(sid).write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if session.get("pharmacy_name"):
        _persist_pharmacy_learned_prefs(session["pharmacy_name"], prefs)
    return prefs


def preference_ack_message(updates: dict[str, Any] | None) -> str:
    """Short Roman Urdu ack when owner only changed preferences."""
    if not updates:
        return "Theek hai."
    parts = []
    if updates.get("language") == "roman_urdu":
        parts.append("ab se Roman Urdu mein jawab dunga")
    if updates.get("format") == "table":
        parts.append("lists table mein dunga")
    elif updates.get("format") == "prose":
        parts.append("paragraph style mein dunga")
    if updates.get("brevity") == "short":
        parts.append("seedha jawab dunga — koi extra intro nahi")
    elif updates.get("brevity") == "normal":
        parts.append("detail ke sath jawab dunga")
    if not parts:
        return "Theek hai — preference save ho gayi."
    return "Theek hai, " + ", ".join(parts) + "."


def format_preferences_for_prompt(session_id: str | None = None) -> str:
    prefs = get_merged_preferences(session_id)
    lines = []
    if prefs.get("format") == "table":
        lines.append("Owner prefers TABLE format for lists.")
    elif prefs.get("format") == "prose":
        lines.append("Owner prefers prose paragraphs, not tables.")
    if prefs.get("brevity") == "short":
        lines.append("Owner prefers SHORT answers — minimal words, key numbers only.")
    if prefs.get("language") == "roman_urdu":
        lines.append("ALWAYS answer in Roman Urdu (Latin script). Never use Urdu/Arabic script.")
    return "\n".join(lines)


def format_session_context(
    session_id: str | None = None,
    question: str = "",
    max_turns: int | None = None,
) -> str:
    from rag.context_memory import format_tiered_context

    session = load_session(session_id)
    return format_tiered_context(session, session_id, question, max_turns=max_turns)


def handle_correction(
    message: str,
    session_id: str | None = None,
) -> tuple[str, str]:
    """Returns (effective_question, correction_context). Saves lesson to corrections file."""
    session = load_session(session_id)
    correction_context = message
    if session.get("last_question"):
        correction_context = (
            f"Previous question: {session.get('last_question')}\n"
            f"Previous understanding: {(session.get('last_intent') or {}).get('clarified_question', 'n/a')}\n"
            f"Previous SQL: {session.get('last_sql', 'n/a')}\n"
            f"Owner correction: {message}"
        )
        add_correction(
            session_id=normalize_session_id(session_id),
            original_question=session.get("last_question", ""),
            wrong_clarified=(session.get("last_intent") or {}).get("clarified_question"),
            wrong_sql=session.get("last_sql"),
            user_correction=message,
        )
    return message, correction_context


def add_correction(
    *,
    session_id: str,
    original_question: str,
    wrong_clarified: str | None,
    wrong_sql: str | None,
    user_correction: str,
    corrected_question: str | None = None,
) -> dict[str, Any]:
    _ensure_dirs()
    entry = {
        "session_id": session_id,
        "original_question": original_question,
        "wrong_clarified": wrong_clarified,
        "wrong_sql": wrong_sql,
        "user_correction": user_correction,
        "corrected_question": corrected_question or user_correction,
        "at": _now(),
    }
    with CORRECTIONS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_corrections(limit: int = 50) -> list[dict[str, Any]]:
    if not CORRECTIONS_PATH.exists():
        return []
    lines = CORRECTIONS_PATH.read_text(encoding="utf-8").strip().splitlines()
    items = []
    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def relevant_corrections(question: str, limit: int = 5) -> list[dict[str, Any]]:
    q_words = set(re.findall(r"\w+", question.lower()))
    scored: list[tuple[int, dict]] = []
    for entry in load_corrections(limit=100):
        blob = " ".join(
            str(entry.get(k, ""))
            for k in ("original_question", "user_correction", "corrected_question")
        ).lower()
        overlap = len(q_words & set(re.findall(r"\w+", blob)))
        if overlap > 0:
            scored.append((overlap, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [e for _, e in scored[:limit]]
    return load_corrections(limit=limit)[-3:]


def format_corrections_for_prompt(corrections: list[dict[str, Any]]) -> str:
    if not corrections:
        return ""
    lines = ["\nLEARNED FROM OWNER CORRECTIONS (do not repeat these mistakes):"]
    for i, c in enumerate(corrections, 1):
        lines.append(
            f"{i}. Owner asked: {c.get('original_question')}\n"
            f"   Wrong: {c.get('wrong_clarified', 'n/a')}\n"
            f"   Corrected: {c.get('corrected_question')}"
        )
    return "\n".join(lines)


def new_session_id() -> str:
    return f"pharm-{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
