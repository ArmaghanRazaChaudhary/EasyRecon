"""Schema context and prompts for the SQL agent."""

# SQL prompts are built dynamically in rag/prompts.py from live DB schema.

ANSWER_SYSTEM_PROMPT = """Legacy — use rag.answer_format.build_explain_system instead."""

EXTRACT_SQL_PROMPT = "Rewrite as a single SQLite SELECT only inside ```sql``` block."
