#!/usr/bin/env python3
"""CLI: ask EasyRecon a question from the terminal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from rag.reports import daily_report, format_whatsapp_report
from rag.sql_agent import ask_safe


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask EasyRecon a pharmacy question")
    parser.add_argument("question", nargs="?", help="Question in Urdu/English")
    parser.add_argument("--report", action="store_true", help="Print daily report (no LLM)")
    parser.add_argument("--whatsapp", action="store_true", help="Print WhatsApp-style report")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--model", default=None, help="Ollama model override")
    parser.add_argument("--session", default=None, help="Pharmacy session ID (chat memory)")
    args = parser.parse_args()

    if args.report or args.whatsapp:
        report = daily_report()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        elif args.whatsapp:
            print(format_whatsapp_report(report))
        else:
            print(json.dumps(report["summary"], indent=2))
        return

    if not args.question:
        parser.print_help()
        sys.exit(1)

    result = ask_safe(args.question, model=args.model, session_id=args.session)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if result.get("off_topic"):
        print(result.get("answer", ""))
        sys.exit(0)

    if result.get("error") and not result.get("answer"):
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if result.get("sql"):
        print(f"\nSQL: {result['sql']}")
        print(f"Rows: {result.get('row_count', 0)}\n")
    print(result.get("answer", ""))


if __name__ == "__main__":
    main()
