"""Format SQL results as markdown tables + detect owner output preferences."""

from __future__ import annotations

import re
from typing import Any

MONEY_KEYS = frozenset({
    "difference", "system_cash", "closing_cash", "opening_cash", "net_amount",
    "net_total", "amount", "current_balance", "credit_limit", "total_paid",
    "purchase_price", "retail_price", "unit_price", "total_revenue", "revenue",
    "unpaid_amount", "over_by",
})

QTY_KEYS = frozenset({
    "quantity", "total_qty", "total_qty_sold", "stock_strips", "quantity_strips",
    "total_units_sold", "total_units", "invoices", "invoice_count", "purchase_count",
})

COLUMN_LABELS: dict[str, str] = {
    "name": "Medicine",
    "medicine_name": "Medicine",
    "company_name": "Supplier",
    "customer_name": "Customer",
    "total_qty": "Units sold",
    "total_units_sold": "Units sold",
    "total_revenue": "Revenue (PKR)",
    "revenue": "Revenue (PKR)",
    "stock_strips": "Strips",
    "quantity_strips": "Strips",
    "strips": "Strips",
    "total_tablets": "Tablets",
    "tablets": "Tablets",
    "pack_size": "Tabs/strip",
    "invoice_count": "Invoices",
    "total_sales": "Sales count",
    "shift_date": "Date",
    "shift": "Shift",
    "difference": "Cash diff (PKR)",
    "net_amount": "Amount (PKR)",
    "payment_status": "Status",
    "batch_no": "Batch",
    "expiry_date": "Expiry",
    "phone": "Phone",
    "current_balance": "Balance (PKR)",
    "credit_limit": "Limit (PKR)",
    "over_by": "Over by (PKR)",
    "unpaid_amount": "Unpaid (PKR)",
    "purchase_count": "Purchases",
}


def human_column(key: str) -> str:
    if key in COLUMN_LABELS:
        return COLUMN_LABELS[key]
    return key.replace("_", " ").title()


def format_cell(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if key in MONEY_KEYS or "amount" in key or "revenue" in key or "total" in key and "qty" not in key:
            return f"{value:,.0f}"
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        if key in MONEY_KEYS or ("cash" in key and "count" not in key):
            return f"{value:,}"
        return f"{value:,}"
    s = str(value)
    return s[:40] + "…" if len(s) > 40 else s


def should_format_as_table(
    result: dict[str, Any],
    intent: dict[str, Any],
    preferences: dict[str, Any],
) -> bool:
    if preferences.get("format") == "prose":
        return False
    if preferences.get("format") == "table":
        return result.get("row_count", 0) >= 1

    rows = result.get("row_count", 0)
    cols = len(result.get("columns") or [])
    if rows == 0:
        return False
    if rows == 1 and cols == 1:
        return False

    qtype = intent.get("question_type", "")
    if qtype in ("rank", "list", "compare") and rows >= 2:
        return True
    if rows >= 2 and cols >= 2:
        return True
    if rows >= 1 and cols >= 3:
        return True
    return False


def rows_to_markdown_table(result: dict[str, Any], max_rows: int = 15) -> str:
    columns = result.get("columns") or []
    rows = (result.get("rows") or [])[:max_rows]
    if not columns or not rows:
        return ""

    headers = [human_column(c) for c in columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [format_cell(c, row.get(c)) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")

    if result.get("row_count", 0) > max_rows:
        lines.append(f"\n_({result['row_count'] - max_rows} aur rows...)_")
    return "\n".join(lines)


def table_intro_prompt(question: str, intent: dict[str, Any], result: dict[str, Any]) -> str:
    scope = intent.get("date_scope") or "none"
    scope_note = {
        "today": "aaj",
        "yesterday": "kal",
        "day_before_yesterday": "parso",
        "this_month": "is mahine",
        "last_month": "pichle mahine",
        "last_7_days": "pichle 7 din",
        "last_30_days": "pichle 30 din",
        "all_time": "ab tak",
    }.get(scope, "")

    return (
        f"Owner question: {question}\n"
        f"Scope: {scope_note or 'general'}\n"
        f"Rows in table: {result.get('row_count', 0)}\n"
        "Write ONLY 1-2 short Roman Urdu sentences as intro before a data table. "
        "Do NOT list medicines or numbers — the table follows. No column names. Latin script only."
    )


INTRO_SYSTEM = """You write brief Roman Urdu intros for pharmacy owners (Latin script ONLY).

FORBIDDEN — never write these:
- "Pharmacy owners ke liye..."
- "Malik sahab apne pharmacy..."
- Generic advice not from the data
- Urdu/Arabic script (اردو)

Write 1 short sentence max. Talk directly to the owner ("Aapke paas..."). Numbers only if NOT in the table below."""

SHORT_SYSTEM = """Roman Urdu (Latin script) ONLY — never Urdu/Arabic script.

Answer in 1-2 lines MAX. Direct tone — owner se baat karein, essay na likhein.
Use **bold** for key numbers from DATA only.
Strips ≠ tablets — never confuse them.
FORBIDDEN: "Pharmacy owners ke liye", generic paragraphs, invented numbers."""

PROSE_SYSTEM = """You are EasyRecon — pharmacy owner's assistant. Roman Urdu in Latin script ONLY (never اردو script).

Rules:
- Direct answer first — no "Pharmacy owners ke liye" or essay-style intros
- Never invent numbers — ONLY use values from DATA
- Strips and tablets are DIFFERENT: 3 strips × 10 tabs/strip = 30 tablets (NOT 30 strips)
- PKR only for money; stock counts are strips/tablets not rupees
- 2-3 short sentences max unless owner asked for detail
- Use **bold** for key figures from data
- If a table is attached, do NOT repeat all rows in prose"""


def build_explain_system(
    *,
    table_mode: bool,
    short_mode: bool,
    clarify: bool,
) -> str:
    if clarify:
        return (
            PROSE_SYSTEM
            + "\n\nOwner is confused about previous answer — explain strips vs tablets clearly. "
            "Use ONLY numbers from DATA. Roman Urdu, Latin script."
        )
    if short_mode:
        return SHORT_SYSTEM
    if table_mode:
        return INTRO_SYSTEM
    return PROSE_SYSTEM
