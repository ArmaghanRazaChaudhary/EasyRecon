"""Database connection and safe SQL execution."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "bismillah_pharmacy.db"

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


class DatabaseError(RuntimeError):
    pass


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists():
        raise DatabaseError(
            f"Database not found: {path}\n"
            "Run: python scripts/generate_pharmacy_db.py"
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def validate_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise DatabaseError("Empty SQL query.")

    if FORBIDDEN_SQL.search(cleaned):
        raise DatabaseError("Only SELECT queries are allowed.")

    if ";" in cleaned:
        raise DatabaseError("Multiple SQL statements are not allowed.")

    upper = cleaned.upper().lstrip()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise DatabaseError("Only SELECT / WITH queries are allowed.")

    return cleaned


def execute_query(sql: str, db_path: str | Path | None = None, limit: int = 100) -> dict[str, Any]:
    safe_sql = validate_sql(sql)
    if "LIMIT" not in safe_sql.upper():
        safe_sql = f"{safe_sql} LIMIT {limit}"

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(safe_sql)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        data = [dict(row) for row in rows]
        return {"sql": safe_sql, "columns": columns, "rows": data, "row_count": len(data)}
    except sqlite3.Error as exc:
        raise DatabaseError(f"SQL error: {exc}") from exc
    finally:
        conn.close()


def get_sales_date_context(db_path: str | Path | None = None) -> dict[str, str]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT MIN(sale_date), MAX(sale_date), COUNT(*) FROM sales"
        ).fetchone()
        return {
            "min_sale_date": (row[0] or "")[:10],
            "max_sale_date": (row[1] or "")[:10],
            "sale_count": str(row[2] or 0),
        }
    finally:
        conn.close()


def get_schema_summary(
    db_path: str | Path | None = None,
    *,
    topic: str | None = None,
) -> str:
    topic_tables = _tables_for_topic(topic)
    conn = get_connection(db_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        lines = []
        for (table_name,) in tables:
            if topic_tables and table_name not in topic_tables:
                continue
            cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            col_desc = ", ".join(f"{c[1]} ({c[2]})" for c in cols)
            lines.append(f"- {table_name}: {col_desc}")
        return "\n".join(lines)
    finally:
        conn.close()


def _tables_for_topic(topic: str | None) -> set[str] | None:
    if not topic:
        return None
    mapping = {
        "sales": {"sales", "sale_items", "medicines", "customers", "employees"},
        "stock": {"medicines", "stock"},
        "cash": {"cash_register", "employees", "sales"},
        "supplier": {"suppliers", "purchases", "purchase_items", "supplier_payments"},
        "customer": {"customers", "sales"},
        "udhaar": {"customers", "sales"},
        "reconciliation": {"reconciliation_flags", "cash_register", "stock", "purchases", "sales"},
    }
    return mapping.get(topic)
