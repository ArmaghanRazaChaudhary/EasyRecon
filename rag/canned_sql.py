"""Deterministic SQL for common pharmacy questions — avoids slow LLM SQL on frequent patterns."""

from __future__ import annotations

import re
from typing import Any

SALES_SUMMARY = """
SELECT COUNT(DISTINCT s.sale_id) AS invoice_count,
       COALESCE(SUM(si.quantity), 0) AS total_units_sold,
       COALESCE(ROUND(SUM(s.net_total), 2), 0) AS total_revenue
FROM sales s
LEFT JOIN sale_items si ON si.sale_id = s.sale_id
{where}
""".strip()

TOP_MEDICINE = """
SELECT m.name,
       SUM(si.quantity) AS units_sold,
       ROUND(SUM(si.amount), 2) AS revenue
FROM sale_items si
JOIN sales s ON s.sale_id = si.sale_id
JOIN medicines m ON m.medicine_id = si.medicine_id
{where}
GROUP BY m.medicine_id, m.name
ORDER BY units_sold DESC
LIMIT 10
""".strip()

MEDICINES_IN_STOCK_COUNT = """
SELECT COUNT(DISTINCT m.medicine_id) AS medicines_in_stock
FROM medicines m
JOIN stock s ON s.medicine_id = m.medicine_id
WHERE s.quantity_strips > 0 OR COALESCE(s.quantity_tablets, 0) > 0
""".strip()

STOCK_LIST = """
SELECT m.name,
       SUM(s.quantity_strips) AS strips,
       m.pack_size,
       (SUM(s.quantity_strips) * m.pack_size) + SUM(COALESCE(s.quantity_tablets, 0)) AS total_tablets
FROM medicines m
JOIN stock s ON s.medicine_id = m.medicine_id
WHERE s.quantity_strips > 0 OR COALESCE(s.quantity_tablets, 0) > 0
GROUP BY m.medicine_id, m.name, m.pack_size
ORDER BY strips DESC
LIMIT 25
""".strip()

STOCK_BY_NAME = """
SELECT m.name,
       SUM(s.quantity_strips) AS strips,
       m.pack_size,
       (SUM(s.quantity_strips) * m.pack_size) + SUM(COALESCE(s.quantity_tablets, 0)) AS total_tablets
FROM medicines m
JOIN stock s ON s.medicine_id = m.medicine_id
WHERE m.name LIKE '{like_pattern}'
GROUP BY m.medicine_id, m.name, m.pack_size
ORDER BY strips DESC
LIMIT 100
""".strip()

ANCHOR = "(SELECT MAX(sale_date) FROM sales)"

DATE_WHERE: dict[str, str] = {
    "today": f"WHERE date(s.sale_date) = date({ANCHOR})",
    "yesterday": f"WHERE date(s.sale_date) = date({ANCHOR}, '-1 day')",
    "day_before_yesterday": f"WHERE date(s.sale_date) = date({ANCHOR}, '-2 days')",
    "last_7_days": f"WHERE date(s.sale_date) >= date({ANCHOR}, '-7 days')",
    "this_week": (
        f"WHERE strftime('%Y-%W', date(s.sale_date)) = strftime('%Y-%W', date({ANCHOR}))"
    ),
    "last_week": (
        f"WHERE strftime('%Y-%W', date(s.sale_date)) = strftime('%Y-%W', date({ANCHOR}, '-7 days'))"
    ),
    "last_30_days": f"WHERE date(s.sale_date) >= date({ANCHOR}, '-30 days')",
    "this_month": (
        f"WHERE date(s.sale_date) >= date({ANCHOR}, 'start of month')\n"
        f"  AND date(s.sale_date) <= date({ANCHOR})"
    ),
    "last_month": (
        f"WHERE date(s.sale_date) >= date({ANCHOR}, 'start of month', '-1 month')\n"
        f"  AND date(s.sale_date) < date({ANCHOR}, 'start of month')"
    ),
    "all_time": "",
}

# Roman Urdu question hints → date_scope (only when Groq intent is incomplete)
_QUESTION_DATE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\baaj\b", re.I), "today"),
    (re.compile(r"\bkal\b", re.I), "yesterday"),
    (re.compile(r"\bparso\b", re.I), "day_before_yesterday"),
    (re.compile(r"\biss?\s+week\b|\bis\s+week\b|this\s+week", re.I), "this_week"),
    (re.compile(r"\bpichl[ae]?\s+week\b|last\s+week", re.I), "last_week"),
    (re.compile(r"\biss?\s+month\b|\bis\s+month\b|\bmahin[ae]\b", re.I), "this_month"),
    (re.compile(r"\bpichl[ae]?\s+month\b", re.I), "last_month"),
)

_DAYS_AGO_RE = re.compile(r"(\d+)\s*din\s*pehle", re.I)

_NOT_MEDICINE = frozenset({
    "kia", "kya", "ky", "what", "kaun", "kitni", "kitna", "kitne", "konsi", "kon",
    "sb", "sab", "all", "remaining", "reh", "gaya", "gya", "hai", "mein", "stock",
})


def _days_ago_where(intent: dict[str, Any]) -> str | None:
    days = intent.get("days_ago")
    if days is not None:
        try:
            n = int(days)
            if n >= 0:
                return f"WHERE date(s.sale_date) = date({ANCHOR}, '-{n} days')"
        except (TypeError, ValueError):
            pass
    clarified = intent.get("clarified_question") or intent.get("original_question") or ""
    m = _DAYS_AGO_RE.search(clarified)
    if m:
        n = int(m.group(1))
        return f"WHERE date(s.sale_date) = date({ANCHOR}, '-{n} days')"
    return None


def _resolve_date_scope(intent: dict[str, Any], question: str = "") -> str | None:
    scope = intent.get("date_scope")
    if scope and scope not in ("none", "specific_date"):
        return scope if scope in DATE_WHERE or scope == "days_ago" else None
    if scope == "specific_date":
        custom = _days_ago_where(intent)
        if custom:
            return f"__custom__:{custom}"
    q = question or intent.get("original_question") or ""
    m = _DAYS_AGO_RE.search(q)
    if m:
        n = int(m.group(1))
        return f"__custom__:WHERE date(s.sale_date) = date({ANCHOR}, '-{n} days')"
    for pattern, label in _QUESTION_DATE_HINTS:
        if pattern.search(q):
            return label
    return None


def _sales_where(intent: dict[str, Any], question: str = "") -> str | None:
    scope = _resolve_date_scope(intent, question)
    if not scope:
        return None
    if scope.startswith("__custom__:"):
        return scope.split(":", 1)[1]
    return DATE_WHERE.get(scope)


def _stock_like_pattern(intent: dict[str, Any]) -> str | None:
    entity = (intent.get("entity") or "").strip()
    if entity and entity.lower() not in _NOT_MEDICINE:
        return f"%{entity.replace(chr(39), chr(39)+chr(39))}%"
    clarified = intent.get("clarified_question") or ""
    for token in clarified.replace("?", " ").split():
        t = token.strip(",.")
        if len(t) >= 4 and t[0].isupper() and t.lower() not in _NOT_MEDICINE:
            return f"%{t.replace(chr(39), chr(39)+chr(39))}%"
    return None


def _is_stock_inventory_question(intent: dict[str, Any], question: str) -> bool:
    if intent.get("topic") != "stock":
        return False
    if intent.get("entity") and intent["entity"].lower() not in _NOT_MEDICINE:
        return False
    q = (question or intent.get("original_question") or "").lower()
    return bool(
        re.search(r"\b(kia|kya|konsi|kon|sab|sb|remaining|reh\s*g)", q)
        or intent.get("question_type") in ("list", "count", "total")
    )


def patch_intent_from_question(question: str, intent: dict[str, Any]) -> dict[str, Any]:
    """Fill missing intent fields when Groq returns incomplete JSON."""
    q = question.lower()
    scope = _resolve_date_scope(intent, q)
    if scope and not scope.startswith("__custom__"):
        intent.setdefault("date_scope", scope)

    if intent.get("topic"):
        if intent.get("entity") and str(intent["entity"]).lower() in _NOT_MEDICINE:
            intent["entity"] = None
        return intent
    if re.search(r"\b(groq|grok|easyrecon|integrated)\b", q):
        intent.update({
            "in_scope": True,
            "category": "system",
            "topic": "general",
            "question_type": "explain",
        })
        return intent

    scope = _resolve_date_scope(intent, q)
    if re.search(r"\bsale", q):
        intent.setdefault("topic", "sales")
        intent.setdefault("question_type", "total")
        if scope and not scope.startswith("__custom__"):
            intent.setdefault("date_scope", scope)
        elif scope and scope.startswith("__custom__"):
            intent.setdefault("date_scope", "specific_date")
        intent.setdefault("in_scope", True)
        return intent

    if re.search(r"\b(sbse|sab se|top|zyada)\b", q) and re.search(r"\b(medicine|dawa|dawai)", q):
        intent.update({
            "in_scope": True,
            "topic": "sales",
            "question_type": "rank",
            "date_scope": scope if scope and not scope.startswith("__custom__") else "this_month",
            "category": "sales",
        })
        return intent

    if re.search(r"\bstock\b", q) and re.search(r"\b(kia|kya|konsi|reh|list)\b", q):
        intent.update({
            "in_scope": True,
            "topic": "stock",
            "question_type": "list",
            "entity": None,
            "category": "stock",
        })
    return intent


def try_canned_sql(intent: dict[str, Any], question: str = "") -> str | None:
    """Return fixed SQL for well-known intents, else None (use LLM)."""
    topic = intent.get("topic")
    qtype = intent.get("question_type")
    metric = (intent.get("metric") or "").lower()
    clarified = (intent.get("clarified_question") or "").lower()
    q = question or intent.get("original_question") or ""

    if topic == "stock":
        if _is_stock_inventory_question(intent, q):
            if qtype in ("count", "total") or re.search(r"\bkitn[ie]", q):
                return MEDICINES_IN_STOCK_COUNT
            return STOCK_LIST
        like = _stock_like_pattern(intent)
        if like and qtype in ("check", "total", "list", "count"):
            return STOCK_BY_NAME.format(like_pattern=like)

    if topic != "sales":
        return None

    where = _sales_where(intent, q)

    if qtype == "rank" or re.search(r"\b(sbse|sab se|top|zyada)\b", q, re.I):
        if where is None:
            scope = _resolve_date_scope(intent, q)
            if scope and not scope.startswith("__custom__"):
                where = DATE_WHERE.get(scope, DATE_WHERE["this_month"])
            elif scope and scope.startswith("__custom__"):
                where = scope.split(":", 1)[1]
            else:
                where = DATE_WHERE["this_month"]
        return TOP_MEDICINE.format(where=where)

    if qtype not in ("count", "total", "list") and not re.search(r"\bsale", q, re.I):
        return None

    sales_words = ("sale", "invoice", "bill", "transaction", "revenue", "units")
    if not any(w in metric or w in clarified or w in q.lower() for w in sales_words):
        return None

    if where is None:
        return None

    return SALES_SUMMARY.format(where=where)
