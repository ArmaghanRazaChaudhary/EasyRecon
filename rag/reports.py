"""Predefined daily reconciliation checks (no LLM required)."""

from __future__ import annotations

from typing import Any

from rag.db import execute_query

CASH_SHORTS_SQL = """
SELECT shift_date, shift, difference, system_cash, closing_cash, notes
FROM cash_register
WHERE difference < -500
  AND shift_date >= date('now', '-7 days')
ORDER BY difference ASC
LIMIT 10
"""

UNPAID_SUPPLIERS_SQL = """
SELECT s.company_name, p.invoice_no, p.purchase_date, p.net_amount, p.payment_status
FROM purchases p
JOIN suppliers s ON s.supplier_id = p.supplier_id
WHERE p.payment_status != 'paid'
  AND julianday('now') - julianday(p.purchase_date) > 30
ORDER BY p.purchase_date
LIMIT 15
"""

EXPIRED_STOCK_SQL = """
SELECT m.name, st.batch_no, st.quantity_strips, st.expiry_date
FROM stock st
JOIN medicines m ON m.medicine_id = st.medicine_id
WHERE st.expiry_date < date('now') AND st.quantity_strips > 0
ORDER BY st.expiry_date
LIMIT 15
"""

CREDIT_OVERDUE_SQL = """
SELECT name, phone, current_balance, credit_limit,
       ROUND(current_balance - credit_limit, 2) AS over_by
FROM customers
WHERE credit_limit > 0 AND current_balance > credit_limit
ORDER BY over_by DESC
LIMIT 10
"""

DUPLICATE_PAYMENTS_SQL = """
SELECT sp.purchase_id, s.company_name, COUNT(*) AS payment_count, SUM(sp.amount) AS total_paid
FROM supplier_payments sp
JOIN purchases p ON p.purchase_id = sp.purchase_id
JOIN suppliers s ON s.supplier_id = sp.supplier_id
GROUP BY sp.purchase_id
HAVING COUNT(*) > 1
LIMIT 10
"""


def daily_report(db_path: str | None = None) -> dict[str, Any]:
    sections = {
        "cash_shorts": execute_query(CASH_SHORTS_SQL, db_path=db_path, limit=10),
        "unpaid_suppliers": execute_query(UNPAID_SUPPLIERS_SQL, db_path=db_path, limit=15),
        "expired_stock": execute_query(EXPIRED_STOCK_SQL, db_path=db_path, limit=15),
        "credit_overdue": execute_query(CREDIT_OVERDUE_SQL, db_path=db_path, limit=10),
        "duplicate_payments": execute_query(DUPLICATE_PAYMENTS_SQL, db_path=db_path, limit=10),
    }

    summary = {
        "cash_shorts": sections["cash_shorts"]["row_count"],
        "unpaid_suppliers": sections["unpaid_suppliers"]["row_count"],
        "expired_stock": sections["expired_stock"]["row_count"],
        "credit_overdue": sections["credit_overdue"]["row_count"],
        "duplicate_payments": sections["duplicate_payments"]["row_count"],
    }
    summary["total_issues"] = sum(summary.values())

    return {"summary": summary, "sections": sections}


def format_whatsapp_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "Assalam o Alaikum - Bismillah Medical Store",
        "Aaj ki reconciliation report:",
        "",
    ]

    if s["cash_shorts"]:
        worst = report["sections"]["cash_shorts"]["rows"][0]
        lines.append(f"[X] Cash short: PKR {abs(worst['difference']):,.0f} ({worst['shift_date']} {worst['shift']})")
    else:
        lines.append("[OK] Cash register: no major shorts (last 7 days)")

    lines.append(f"{'[!]' if s['unpaid_suppliers'] else '[OK]'} Unpaid supplier invoices (30+ days): {s['unpaid_suppliers']}")
    lines.append(f"{'[!]' if s['expired_stock'] else '[OK]'} Expired stock batches: {s['expired_stock']}")
    lines.append(f"{'[!]' if s['credit_overdue'] else '[OK]'} Udhaar over credit limit: {s['credit_overdue']}")
    lines.append(f"{'[!]' if s['duplicate_payments'] else '[OK]'} Duplicate supplier payments: {s['duplicate_payments']}")
    lines.append("")
    lines.append("Koi sawal ho to poochhein.")

    return "\n".join(lines)
