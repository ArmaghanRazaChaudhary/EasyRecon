"""Dynamic SQL prompts with live database schema."""

from __future__ import annotations

from rag.db import get_schema_summary, get_sales_date_context

BUSINESS_RULES = """
Database: Bismillah Medical Store (Lahore pharmacy POS)
Engine: SQLite

Business rules:
- cash_register.difference < 0 means cash SHORT
- payment_status != 'paid' on purchases = unpaid supplier invoice
- customers.current_balance > credit_limit = udhaar over limit
- stock.expiry_date < date('now') AND quantity_strips > 0 = expired stock on shelf

Date helpers: date('now'), date('now', '-30 days'), julianday('now') - julianday(col)

IMPORTANT — sales date anchoring:
- sale_date is ISO datetime TEXT (e.g. 2026-03-28T15:20:00) — ALWAYS use date(s.sale_date)
- Demo/historical data may end BEFORE today. For today / last_7_days / last_30_days / last_month:
  anchor to latest sale in DB: date((SELECT MAX(sale_date) FROM sales))
  NOT date('now')
- last_month / pichle mahine = calendar month before the month of MAX(sale_date):
  date(s.sale_date) >= date((SELECT MAX(sale_date) FROM sales), 'start of month', '-1 month')
  AND date(s.sale_date) < date((SELECT MAX(sale_date) FROM sales), 'start of month')

CORRECT JOIN KEYS (never guess column names like id):
- medicines.medicine_id = stock.medicine_id = sale_items.medicine_id = purchase_items.medicine_id
- sales.sale_id = sale_items.sale_id
- employees.employee_id = cash_register.cashier_id = sales.cashier_id
- suppliers.supplier_id = purchases.supplier_id
- purchases.purchase_id = purchase_items.purchase_id = supplier_payments.purchase_id
- sales uses sale_date (NOT shift_date; shift_date is only on cash_register)

Query patterns:
- Top selling medicine today: sale_items + sales + medicines, filter date(s.sale_date)=date('now'), GROUP BY, ORDER BY SUM(quantity) DESC
- Stock available / pari hai: medicines JOIN stock, GROUP BY medicine_id — SUM(quantity_strips) AS strips. NEVER per-batch is_available rows.
  Example: SELECT m.name, SUM(s.quantity_strips) AS strips, ... WHERE m.name LIKE '%Panadol%' GROUP BY m.medicine_id, m.name
- Total medicines in stock: COUNT(DISTINCT m.medicine_id) WHERE quantity_strips > 0 OR quantity_tablets > 0
- Total units sold: SUM(sale_items.quantity) JOIN sales ON sale_id
- How many sales / kitni sale: ONE row with COUNT(DISTINCT s.sale_id) AS invoice_count, COALESCE(SUM(si.quantity),0) AS total_units_sold, COALESCE(SUM(s.net_total),0) AS total_revenue — always JOIN sale_items
""".strip()


def build_sql_system_prompt(db_path: str | None = None, *, topic: str | None = None) -> str:
    live_schema = get_schema_summary(db_path, topic=topic)
    return f"""You are a SQL expert for a Pakistan pharmacy SQLite database.
Write ONE SQLite SELECT query to answer the user's question.

{BUSINESS_RULES}

LIVE DATABASE SCHEMA — use these EXACT table and column names (never invent id, use medicine_id, sale_id, etc.):
{live_schema}

Rules:
- Output ONLY the SQL inside a ```sql code block
- No explanation outside the code block
- Never modify data; SELECT only
- Follow the interpreted intent JSON (especially date_scope and clarified_question)
- Always JOIN on the keys listed above

FEW-SHOT EXAMPLES:

Intent: rank medicine sales, date_scope=today
```sql
SELECT m.name, SUM(si.quantity) AS total_qty
FROM sale_items si
JOIN sales s ON s.sale_id = si.sale_id
JOIN medicines m ON m.medicine_id = si.medicine_id
WHERE date(s.sale_date) = date('now')
GROUP BY m.medicine_id, m.name
ORDER BY total_qty DESC
LIMIT 5
```

Intent: rank medicine sales, date_scope=all_time
```sql
SELECT m.name, SUM(si.quantity) AS total_qty
FROM sale_items si
JOIN medicines m ON m.medicine_id = si.medicine_id
GROUP BY m.medicine_id, m.name
ORDER BY total_qty DESC
LIMIT 5
```

Intent: stock check for Panadol
```sql
SELECT m.name, SUM(s.quantity_strips) AS stock_strips
FROM medicines m
JOIN stock s ON s.medicine_id = m.medicine_id
WHERE m.name LIKE '%Panadol%'
GROUP BY m.medicine_id, m.name
```

Intent: rank medicine sales, date_scope=last_month
```sql
SELECT m.name, SUM(si.quantity) AS total_qty
FROM sale_items si
JOIN sales s ON s.sale_id = si.sale_id
JOIN medicines m ON m.medicine_id = si.medicine_id
WHERE date(s.sale_date) >= date((SELECT MAX(sale_date) FROM sales), 'start of month', '-1 month')
  AND date(s.sale_date) < date((SELECT MAX(sale_date) FROM sales), 'start of month')
GROUP BY m.medicine_id, m.name
ORDER BY total_qty DESC
LIMIT 1
```

Intent: count sales, date_scope=last_month
```sql
SELECT COUNT(DISTINCT s.sale_id) AS invoice_count,
       COALESCE(SUM(si.quantity), 0) AS total_units_sold,
       COALESCE(SUM(s.net_total), 0) AS total_revenue
FROM sales s
LEFT JOIN sale_items si ON si.sale_id = s.sale_id
WHERE date(s.sale_date) >= date((SELECT MAX(sale_date) FROM sales), 'start of month', '-1 month')
  AND date(s.sale_date) < date((SELECT MAX(sale_date) FROM sales), 'start of month')
```

Intent: cash short
```sql
SELECT shift_date, shift, cashier_id, system_cash, closing_cash, difference
FROM cash_register
WHERE difference < 0
ORDER BY shift_date DESC, difference ASC
LIMIT 20
```
"""


def format_intent_for_sql(intent: dict) -> str:
    import json
    return json.dumps(intent, ensure_ascii=False, indent=2)


def build_sql_user_message(
    question: str,
    intent: dict,
    db_path: str | None = None,
    *,
    memory_context: str = "",
) -> str:
    ctx = get_sales_date_context(db_path)
    data_note = (
        f"\n\nSALES DATA IN DB: {ctx['min_sale_date']} to {ctx['max_sale_date']} "
        f"({ctx['sale_count']} sales). Relative dates must anchor to MAX(sale_date), not today."
    )
    memory_block = ""
    if memory_context.strip():
        memory_block = f"\n\nSESSION MEMORY (referential queries must use this):\n{memory_context.strip()}\n"
    return f"""Owner question (raw, may have typos):
{question}

Interpreted intent (follow this):
{format_intent_for_sql(intent)}
{data_note}{memory_block}
Write SQL for clarified_question. Respect date_scope exactly."""


def build_sql_fix_prompt(
    question: str,
    bad_sql: str,
    error: str,
    db_path: str | None = None,
    *,
    topic: str | None = None,
) -> str:
    live_schema = get_schema_summary(db_path, topic=topic)
    return f"""This SQL failed for question: {question}

Error: {error}

Bad SQL:
{bad_sql}

LIVE SCHEMA (use EXACT names — no m.id, use m.medicine_id; no shift_date on sales, use sale_date):
{live_schema}

Fix the query. Return only corrected SQL in ```sql``` block."""


def build_sql_empty_date_prompt(question: str, bad_sql: str, db_path: str | None = None) -> str:
    ctx = get_sales_date_context(db_path)
    return f"""This SQL returned 0 rows for question: {question}

Bad SQL:
{bad_sql}

Sales data only exists from {ctx['min_sale_date']} to {ctx['max_sale_date']} (not up to today).
Rewrite using date((SELECT MAX(sale_date) FROM sales)) instead of date('now').
Always wrap sale_date as date(s.sale_date).

For last_month use:
WHERE date(s.sale_date) >= date((SELECT MAX(sale_date) FROM sales), 'start of month', '-1 month')
  AND date(s.sale_date) < date((SELECT MAX(sale_date) FROM sales), 'start of month')

Return only corrected SQL in ```sql``` block."""
