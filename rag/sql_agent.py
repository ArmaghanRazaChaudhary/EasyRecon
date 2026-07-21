"""SQL agent: Groq intent + local Qwen SQL + fast/Groq answers + per-pharmacy sessions."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from rag.analyze import analyze_question, build_off_topic_reply
from rag.answer_format import (
    build_explain_system,
    rows_to_markdown_table,
    should_format_as_table,
    table_intro_prompt,
)
from rag.canned_sql import patch_intent_from_question, try_canned_sql
from rag.pharmacy_vocab import normalize_pharmacy_speech
from rag.fast_answer import try_deterministic_answer
from rag.db import DatabaseError, execute_query
from rag.llm import LLMError, chat_explain, chat_local
from rag.learning import record_turn_learning
from rag.memory import (
    format_session_context,
    get_merged_preferences,
    load_session,
    preference_ack_message,
    save_session_turn,
)
from rag.context_memory import format_sql_memory_context
from rag.prompts import (
    build_sql_empty_date_prompt,
    build_sql_fix_prompt,
    build_sql_system_prompt,
    build_sql_user_message,
)

SQL_BLOCK_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
SQL_NUM_PREDICT = 400
RELATIVE_DATE_SCOPES = frozenset({
    "today", "yesterday", "day_before_yesterday",
    "this_week", "last_week", "last_7_days", "last_30_days", "last_month", "this_month",
})
BOILERPLATE_RE = re.compile(
    r"(?:Pharmacy owners? ke liye|Malik sahab|Pharmacy ke malik|"
    r"Hamare pharmacy mein|Apni pharmacy mein|jaankari nimn mein|madad karegi|"
    r"dard nivaarak|dawaen uplabdh|sar dard|Ji sir|milenge|claim apply|Owner Activity).*$",
    re.IGNORECASE | re.MULTILINE,
)
URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")


def _clean_answer(text: str, *, roman_urdu: bool = True) -> str:
    text = text.replace("\u2014", "-").replace("\u2013", "-").strip()
    text = BOILERPLATE_RE.sub("", text).strip()
    if roman_urdu and URDU_SCRIPT_RE.search(text):
        text = URDU_SCRIPT_RE.sub("", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def extract_sql(text: str) -> str:
    match = SQL_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()
    stripped = text.strip()
    if stripped.upper().startswith(("SELECT", "WITH")):
        return stripped.split(";")[0].strip()
    raise DatabaseError("Model did not return valid SQL.")


def format_rows_for_llm(result: dict[str, Any], max_rows: int = 25) -> str:
    rows = result["rows"][:max_rows]
    return json.dumps(
        {
            "row_count": result["row_count"],
            "columns": result["columns"],
            "rows": rows,
            "truncated": result["row_count"] > max_rows,
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _generate_sql_with_retries(
    question: str,
    intent: dict[str, Any],
    *,
    model: str | None,
    db_path: str | None,
    session: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    intent = patch_intent_from_question(question, intent)
    topic = intent.get("topic")
    canned = try_canned_sql(intent, question)
    if canned:
        try:
            return execute_query(canned, db_path=db_path), errors
        except DatabaseError as exc:
            errors.append(str(exc))

    system_prompt = build_sql_system_prompt(db_path, topic=topic)
    memory_context = format_sql_memory_context(session, question) if session else ""
    user_message = build_sql_user_message(
        question, intent, db_path, memory_context=memory_context
    )

    sql_response = chat_local(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        model=model,
        temperature=0.0,
        sql=True,
        num_predict=SQL_NUM_PREDICT,
    )
    sql = extract_sql(sql_response)
    last_response = sql_response
    date_anchor_retried = False

    for attempt in range(3):
        try:
            result = execute_query(sql, db_path=db_path)
            if (
                result["row_count"] == 0
                and intent.get("date_scope") in RELATIVE_DATE_SCOPES
                and not date_anchor_retried
            ):
                date_anchor_retried = True
                fix_prompt = build_sql_empty_date_prompt(question, sql, db_path)
                last_response = chat_local(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": last_response},
                        {"role": "user", "content": fix_prompt},
                    ],
                    model=model,
                    temperature=0.0,
                    sql=True,
                    num_predict=SQL_NUM_PREDICT,
                )
                sql = extract_sql(last_response)
                continue
            return result, errors
        except DatabaseError as err:
            errors.append(str(err))
            if attempt == 2:
                raise
            fix_prompt = build_sql_fix_prompt(question, sql, str(err), db_path, topic=topic)
            last_response = chat_local(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": last_response},
                    {"role": "user", "content": fix_prompt},
                ],
                model=model,
                temperature=0.0,
                sql=True,
                num_predict=SQL_NUM_PREDICT,
            )
            sql = extract_sql(last_response)

    raise DatabaseError("SQL generation failed after retries.")


def _merge_output_prefs(intent: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    prefs = get_merged_preferences(session_id)
    style = intent.get("output_style") or "auto"
    if style == "table":
        prefs = {**prefs, "format": "table"}
    elif style == "short":
        prefs = {**prefs, "brevity": "short"}
    elif style == "prose":
        prefs = {**prefs, "format": "prose"}
    return prefs


def _build_explain_prompt(
    question: str,
    result: dict[str, Any],
    intent: dict[str, Any],
    session_context: str,
    *,
    clarify: bool = False,
    table_mode: bool = False,
    short_mode: bool = False,
    previous_question: str | None = None,
    previous_answer: str | None = None,
) -> str:
    if table_mode and not clarify:
        return table_intro_prompt(question, intent, result)

    parts = [
        f"RECENT CHAT:\n{session_context}\n",
        f"OWNER ASKED: {question}",
        f"Understood as: {intent.get('clarified_question', '')}",
        f"\nDATA ({result['row_count']} rows):\n{format_rows_for_llm(result, max_rows=15)}",
    ]
    if clarify and previous_question:
        parts.append(f"PREVIOUS Q: {previous_question}")
    if clarify and previous_answer:
        parts.append(f"PREVIOUS A: {previous_answer}")
    if short_mode:
        parts.append("\nAnswer in 1-2 lines ONLY. Bold key numbers with **.")
    elif not table_mode:
        parts.append("\nNatural Roman Urdu. Explain numbers clearly. Bold key figures with **.")
    return "\n".join(parts)


SYSTEM_REPLY = (
    "Haan — **Groq** intent aur Roman Urdu jawab ke liye use hota hai (fast). "
    "**SQL** local **Qwen 3.5** (Ollama) likhta hai. Aap sales, stock, cash poochhein."
)


def _explain_result(
    question: str,
    result: dict[str, Any],
    intent: dict[str, Any],
    session_context: str,
    *,
    model: str | None,
    session_id: str | None = None,
    clarify: bool = False,
    previous_question: str | None = None,
    previous_answer: str | None = None,
) -> tuple[str, str]:
    prefs = _merge_output_prefs(intent, session_id)
    roman = prefs.get("language") != "english"

    det = try_deterministic_answer(
        question, intent, result, prefs, clarify=clarify
    )
    if det:
        return _clean_answer(det, roman_urdu=roman), "deterministic"

    short_mode = prefs.get("brevity") == "short" and not clarify
    table_mode = should_format_as_table(result, intent, prefs) and not clarify

    if table_mode:
        table = rows_to_markdown_table(result)
        if table:
            return _clean_answer(table, roman_urdu=roman), "table"

    system = build_explain_system(
        table_mode=table_mode,
        short_mode=short_mode,
        clarify=clarify,
    )

    raw = chat_explain(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": _build_explain_prompt(
                    question,
                    result,
                    intent,
                    session_context,
                    clarify=clarify,
                    table_mode=table_mode,
                    short_mode=short_mode,
                    previous_question=previous_question,
                    previous_answer=previous_answer,
                ),
            },
        ],
        temperature=0.2 if clarify else 0.15,
    )
    answer = _clean_answer(raw, roman_urdu=roman)

    if table_mode:
        table = rows_to_markdown_table(result)
        if table:
            answer = f"{answer}\n\n{table}" if answer else table
            return answer, "table"

    if answer.strip():
        return answer, "llm"

    fallback = rows_to_markdown_table(result)
    if fallback:
        return _clean_answer(fallback, roman_urdu=roman), "table"
    if result.get("row_count", 0) == 0:
        return "Is query ke liye koi record nahi mila.", "fallback"
    return "Jawab tayyar nahi ho saka — dobara try karein.", "fallback"


def ask(
    question: str,
    *,
    model: str | None = None,
    db_path: str | None = None,
    session_id: str | None = None,
    pharmacy_name: str | None = None,
    skip_scope_check: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    question = normalize_pharmacy_speech(question)
    session = load_session(session_id)
    session_context = format_session_context(session_id, question)

    analysis = analyze_question(
        question,
        model=None,
        session_context=session_context,
        session_id=session_id,
    )
    record_turn_learning(session_id, question, analysis)
    analysis = patch_intent_from_question(question, analysis)

    if re.search(r"\b(groq|grok|easyrecon|integrated)\b", question, re.I):
        if analysis.get("category") == "system" or not analysis.get("topic"):
            save_session_turn(session_id, question=question, answer=SYSTEM_REPLY, intent=analysis, pharmacy_name=pharmacy_name)
            return {
                "question": question,
                "session_id": session_id,
                "answer": SYSTEM_REPLY,
                "sql": None,
                "row_count": 0,
                "rows": [],
                "errors": [],
                "intent": analysis,
                "off_topic": False,
                "corrected": False,
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                "answer_source": "system",
            }

    msg_type = analysis.get("message_type") or "query"
    corrected = msg_type == "correction"
    effective_question = (
        analysis.get("resolved_question")
        or analysis.get("clarified_question")
        or question
    )

    if msg_type == "preference_only":
        ack = preference_ack_message(analysis.get("preference_update"))
        save_session_turn(session_id, question=question, answer=ack, intent=analysis, pharmacy_name=pharmacy_name)
        return {
            "question": question,
            "session_id": session_id,
            "answer": ack,
            "sql": None,
            "row_count": 0,
            "rows": [],
            "errors": [],
            "intent": analysis,
            "off_topic": False,
            "corrected": False,
            "preference_only": True,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "answer_source": "preference",
        }

    if (
        msg_type == "clarify"
        and not analysis.get("refers_to_previous")
        and session.get("last_sql")
    ):
        result = execute_query(session["last_sql"], db_path=db_path)
        analysis["question_type"] = "clarify"
        answer, answer_source = _explain_result(
            question,
            result,
            analysis,
            session_context,
            model=model,
            session_id=session_id,
            clarify=True,
            previous_question=session.get("last_question"),
            previous_answer=session.get("last_answer"),
        )
        save_session_turn(
            session_id,
            question=question,
            answer=answer,
            intent=analysis,
            sql=session["last_sql"],
            pharmacy_name=pharmacy_name,
            rows=result.get("rows"),
            columns=result.get("columns"),
        )
        return {
            "question": question,
            "session_id": session_id,
            "intent": analysis,
            "sql": session["last_sql"],
            "row_count": result["row_count"],
            "columns": result["columns"],
            "rows": result["rows"],
            "answer": answer,
            "errors": [],
            "off_topic": False,
            "corrected": corrected,
            "follow_up": True,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "answer_source": answer_source,
        }

    if not skip_scope_check and not analysis.get("in_scope"):
        if (analysis.get("category") == "system") or re.search(
            r"\b(groq|grok|easyrecon|integrated|integration)\b", question, re.I
        ):
            answer = SYSTEM_REPLY
            save_session_turn(session_id, question=question, answer=answer, intent=analysis, pharmacy_name=pharmacy_name)
            return {
                "question": question,
                "session_id": session_id,
                "answer": answer,
                "sql": None,
                "row_count": 0,
                "rows": [],
                "errors": [],
                "intent": analysis,
                "off_topic": False,
                "corrected": corrected,
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                "answer_source": "system",
            }
        answer = build_off_topic_reply(analysis)
        answer = _clean_answer(answer)
        save_session_turn(session_id, question=question, answer=answer, intent=analysis, pharmacy_name=pharmacy_name)
        return {
            "question": question,
            "session_id": session_id,
            "answer": answer,
            "sql": None,
            "row_count": 0,
            "rows": [],
            "errors": [],
            "intent": analysis,
            "off_topic": True,
            "corrected": corrected,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "answer_source": "scope",
        }

    result, errors = _generate_sql_with_retries(
        effective_question,
        analysis,
        model=model,
        db_path=db_path,
        session=session,
    )
    answer, answer_source = _explain_result(
        effective_question, result, analysis, session_context, model=model, session_id=session_id
    )

    save_session_turn(
        session_id,
        question=effective_question,
        answer=answer,
        intent=analysis,
        sql=result["sql"],
        pharmacy_name=pharmacy_name,
        rows=result.get("rows"),
        columns=result.get("columns"),
    )

    return {
        "question": question,
        "effective_question": effective_question,
        "session_id": session_id,
        "intent": analysis,
        "sql": result["sql"],
        "row_count": result["row_count"],
        "columns": result["columns"],
        "rows": result["rows"],
        "answer": answer,
        "errors": errors,
        "off_topic": False,
        "corrected": corrected,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "answer_source": answer_source,
    }


def ask_safe(question: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return ask(question, **kwargs)
    except LLMError as exc:
        msg = str(exc)
        friendly = "SQL nahi ban saki — thori der baad dobara try karein." if "SQL" in msg or "valid SQL" in msg else msg
        return {"question": question, "error": msg, "answer": friendly, "sql": None}
    except (DatabaseError, json.JSONDecodeError, KeyError) as exc:
        return {"question": question, "error": str(exc), "answer": f"Error: {exc}", "sql": None}
