"""Deterministic Roman Urdu answers from SQL rows — schema-driven, not phrase rules."""

from __future__ import annotations

import os
import re
from typing import Any

from rag.answer_format import rows_to_markdown_table

FAST_ANSWERS = os.getenv("FAST_ANSWERS", "true").lower() in ("1", "true", "yes")

SCOPE_LABELS = {
    "today": "Aaj",
    "yesterday": "Kal",
    "day_before_yesterday": "Parso",
    "this_week": "Is week",
    "last_week": "Pichle week",
    "this_month": "Is mahine",
    "last_month": "Pichle mahine",
    "last_30_days": "Pichle 30 din",
    "last_7_days": "Pichle 7 din",
    "all_time": "Ab tak",
}

STRIP_KEYS = ("strips", "stock_strips", "quantity_strips", "total_strips")
TABLET_KEYS = ("total_tablets", "tablets", "quantity_tablets", "loose_tablets")
PACK_KEYS = ("pack_size",)


def _fmt_qty(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _first_val(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    for key in keys:
        for col, val in row.items():
            if col.lower() == key and val is not None:
                return val
    return None


def _parse_stock_row(row: dict[str, Any]) -> tuple[str, int, int, int]:
    name = str(_first_val(row, ("name", "medicine_name")) or "Medicine")
    strips = int(_first_val(row, STRIP_KEYS) or 0)
    pack = int(_first_val(row, PACK_KEYS) or 10)
    tablets_raw = _first_val(row, TABLET_KEYS)
    if tablets_raw is not None:
        tablets = int(tablets_raw)
    else:
        loose = int(_first_val(row, ("quantity_tablets",)) or 0)
        tablets = strips * pack + loose
    return name, strips, pack, tablets


def _is_stock_result(result: dict[str, Any], intent: dict[str, Any]) -> bool:
    if intent.get("topic") == "stock":
        return True
    cols = {c.lower() for c in (result.get("columns") or [])}
    if cols & {k.lower() for k in STRIP_KEYS} or "quantity_strips" in cols:
        return True
    if cols & {"is_available", "available"} and ("name" in cols or "medicine_name" in cols):
        return True
    return False


def _is_medicine_count_result(result: dict[str, Any]) -> bool:
    cols = result.get("columns") or []
    if result.get("row_count") != 1 or len(cols) != 1:
        return False
    col = cols[0].lower()
    return (
        "medicines_in_stock" in col
        or col.startswith("total_medicines")
        or ("count" in col and "medicine" in col)
        or col in ("medicine_count", "total_medicine_count")
    )


def _is_availability_check(intent: dict[str, Any]) -> bool:
    qtype = intent.get("question_type")
    metric = (intent.get("metric") or "").lower()
    clarified = (intent.get("clarified_question") or "").lower()
    return qtype == "check" or "availab" in metric or "available" in clarified


def _normalize_stock_result(result: dict[str, Any]) -> dict[str, Any]:
    """Collapse per-batch rows into one row per medicine."""
    rows = result.get("rows") or []
    if not rows:
        return result
    cols = {c.lower() for c in (result.get("columns") or [])}
    if cols & {"is_available", "available"} and not cols & {k.lower() for k in STRIP_KEYS}:
        grouped: dict[str, int] = {}
        for row in rows:
            name = str(row.get("name") or row.get("medicine_name") or "Medicine")
            avail = row.get("is_available") or row.get("available")
            strips = int(row.get("quantity_strips") or row.get("strips") or 0)
            if strips == 0 and avail:
                strips = 1 if int(avail) else 0
            grouped[name] = grouped.get(name, 0) + strips
        new_rows = [{"name": n, "strips": s, "total_tablets": s * 10} for n, s in grouped.items()]
        return {**result, "columns": ["name", "strips", "total_tablets"], "rows": new_rows, "row_count": len(new_rows)}

    names = [str(r.get("name") or r.get("medicine_name") or "") for r in rows]
    if len(names) == len(set(names)):
        return result

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name, strips, pack, tablets = _parse_stock_row(row)
        if name not in merged:
            merged[name] = {"name": name, "strips": 0, "pack_size": pack, "total_tablets": 0}
        merged[name]["strips"] += strips
        merged[name]["total_tablets"] += tablets
    new_rows = list(merged.values())
    return {**result, "columns": ["name", "strips", "pack_size", "total_tablets"], "rows": new_rows, "row_count": len(new_rows)}


def _availability_answer(
    intent: dict[str, Any],
    result: dict[str, Any],
) -> str | None:
    result = _normalize_stock_result(result)
    rows = result.get("rows") or []
    if not rows:
        entity = intent.get("entity") or "Yeh medicine"
        return f"**Nahi** — **{entity}** abhi stock mein **nahi** hai."

    parsed = [_parse_stock_row(r) for r in rows]
    in_stock = [(n, s, p, t) for n, s, p, t in parsed if s > 0]
    entity = intent.get("entity") or parsed[0][0]

    if not in_stock:
        names = ", ".join(n for n, _, _, _ in parsed)
        return f"**Nahi** — **{entity}** ({names}) abhi stock mein **nahi** hai."

    if len(in_stock) == 1:
        name, strips, _, tablets = in_stock[0]
        return f"**Haan**, **{name}** available hai — **{strips} strips** ({tablets} tablets)."

    parts = [f"**Haan**, **{entity}** ke kuch variants available hain:"]
    for name, strips, _, tablets in in_stock:
        parts.append(f"- **{name}**: **{strips} strips** ({tablets} tablets)")
    return "\n".join(parts)


def _stock_answer(
    question: str,
    intent: dict[str, Any],
    result: dict[str, Any],
    *,
    short: bool = False,
) -> str | None:
    result = _normalize_stock_result(result)
    rows = result.get("rows") or []
    if not rows:
        entity = intent.get("entity")
        if entity and str(entity).lower() not in {"kia", "kya", "what"}:
            return f"**{entity}** ka stock abhi **0 strips** hai — record nahi mila."
        if intent.get("topic") == "stock":
            return "Stock list khali hai — koi medicine quantity > 0 nahi mili."
        return f"**{entity or 'Yeh medicine'}** ka stock abhi **0 strips** hai — record nahi mila."

    parsed = [_parse_stock_row(r) for r in rows]

    if len(parsed) == 1:
        name, strips, pack, tablets = parsed[0]
        if strips == 0:
            return f"**{name}** abhi stock mein **nahi** hai (0 strips)."
        if short:
            return f"**{name}**: **{strips} strips** ({tablets} tablets)."
        return (
            f"**{name}** ke paas **{strips} strips** hain - "
            f"har strip mein **{pack} tablets**, total **{tablets} tablets**."
        )

    total_strips = sum(p[1] for p in parsed)
    total_tablets = sum(p[3] for p in parsed)

    display = {
        "columns": ["name", "strips", "total_tablets"],
        "rows": [{"name": p[0], "strips": p[1], "total_tablets": p[3]} for p in parsed],
        "row_count": len(parsed),
    }
    table = rows_to_markdown_table(display)
    if short and table:
        return table
    if table:
        return f"Total **{total_strips} strips** / **{total_tablets} tablets**.\n\n{table}"
    return f"Total **{total_strips} strips**, **{total_tablets} tablets**."


def _clarify_units_answer(question: str, result: dict[str, Any]) -> str | None:
    rows = result.get("rows") or []
    if not rows:
        return None
    q = question.lower()
    if not re.search(r"strip|tablet|tab|matlab|mtlb|teen|mean", q):
        return None

    if len(rows) == 1:
        name, strips, pack, tablets = _parse_stock_row(rows[0])
        return (
            f"**{name}**: number **strips** mein hai - **{strips} strips**. "
            f"Har strip **{pack} tablets** ki hoti hai, is liye total **{tablets} tablets** hain. "
            f"30 tablets != 30 strips."
        )

    lines = ["Strips aur tablets ka farq:"]
    for row in rows[:8]:
        name, strips, pack, tablets = _parse_stock_row(row)
        lines.append(f"- **{name}**: **{strips} strips** = **{tablets} tablets** (×{pack})")
    return "\n".join(lines)


def _medicine_count_answer(result: dict[str, Any]) -> str | None:
    rows = result.get("rows") or []
    if not rows:
        return None
    row = rows[0]
    val = next(iter(row.values()))
    count = int(val) if val is not None else 0
    return (
        f"Abhi stock mein **{count} alag medicines** available hain "
        f"(distinct medicines - total strips/tablets alag cheez hai)."
    )


def _sales_summary_answer(intent: dict[str, Any], result: dict[str, Any]) -> str | None:
    rows = result.get("rows") or []
    if len(rows) != 1:
        return None
    row = rows[0]
    inv = row.get("invoice_count")
    if inv is None:
        return None
    inv = int(inv or 0)
    units = int(row.get("total_units_sold") or 0)
    revenue = row.get("total_revenue") or 0
    scope = SCOPE_LABELS.get(intent.get("date_scope") or "", "Is din")
    if inv == 0:
        return f"**{scope}** koi sale record nahi mila (0 invoices)."
    if isinstance(revenue, float):
        revenue = f"{revenue:,.0f}"
    return f"**{scope}**: **{inv}** invoices, **{units}** units, **PKR {revenue}** revenue."


def _rank_answer(intent: dict[str, Any], result: dict[str, Any]) -> str | None:
    rows = result.get("rows") or []
    if not rows:
        return None
    row = rows[0]
    name = row.get("name") or row.get("medicine_name")
    qty = row.get("units_sold") or row.get("total_qty")
    if not name:
        return None
    scope = SCOPE_LABELS.get(intent.get("date_scope") or "", "Is period mein")
    if qty is not None:
        return f"{scope} sab se zyada **{name}** biki — **{_fmt_qty(qty)}** units."
    return f"{scope} top medicine: **{name}**."


def try_deterministic_answer(
    question: str,
    intent: dict[str, Any],
    result: dict[str, Any],
    preferences: dict[str, Any] | None = None,
    *,
    clarify: bool = False,
) -> str | None:
    """Build answer purely from SQL rows — Roman Urdu, correct units."""
    if not FAST_ANSWERS:
        return None

    prefs = preferences or {}
    short = prefs.get("brevity") == "short" or prefs.get("brevity") is None

    if clarify:
        clarified = _clarify_units_answer(question, result)
        if clarified:
            return clarified

    if intent.get("question_type") in ("clarify", "explain") and not clarify:
        return None

    sales_ans = _sales_summary_answer(intent, result)
    if sales_ans:
        return sales_ans

    if intent.get("question_type") == "rank" or "units_sold" in (result.get("columns") or []):
        rank_ans = _rank_answer(intent, result)
        if rank_ans:
            return rank_ans

    if _is_medicine_count_result(result):
        return _medicine_count_answer(result)

    if _is_stock_result(result, intent):
        result = _normalize_stock_result(result)
        if _is_availability_check(intent):
            avail = _availability_answer(intent, result)
            if avail:
                return avail
        return _stock_answer(question, intent, result, short=short)

    return _legacy_fast_answer(intent, result)


def _legacy_fast_answer(intent: dict[str, Any], result: dict[str, Any]) -> str | None:
    rows = result.get("rows") or []
    topic = intent.get("topic", "general")

    if not rows:
        if topic == "stock" and intent.get("entity"):
            return (
                f"{intent['entity']} ka stock record nahi mila. "
                "Naam check karein."
            )
        if intent.get("date_scope") == "today":
            return "Aaj ke liye abhi koi sale record nahi mila."
        return None

    if len(rows) == 1 and intent.get("question_type") == "rank":
        row = rows[0]
        name = row.get("name") or row.get("medicine_name")
        qty = None
        for k, v in row.items():
            if "qty" in k.lower() or "quantity" in k.lower() or "sold" in k.lower():
                qty = v
                break
        if name and qty is not None:
            scope = SCOPE_LABELS.get(intent.get("date_scope", ""), "Is period mein")
            return f"{scope} sab se zyada **{name}** biki — total **{_fmt_qty(qty)}** units."

    return None


def try_fast_answer(intent: dict[str, Any], result: dict[str, Any]) -> str | None:
    return try_deterministic_answer("", intent, result)
