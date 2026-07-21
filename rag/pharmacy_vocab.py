"""Pharmacy vocabulary — STT hints + fuzzy medicine name fix (data-driven, not phrase rules)."""

from __future__ import annotations

import difflib
import re
from functools import lru_cache
from typing import Any

from rag.db import DEFAULT_DB_PATH, execute_query

# Common Whisper mishears for Pakistan pharmacy speech
_STATIC_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bpendulum\b", "panadol"),
    (r"\bpina+do+l\b", "panadol"),
    (r"\bpainadol\b", "panadol"),
    (r"\bpenadol\b", "panadol"),
    (r"\bpanad+ol\b", "panadol"),
    (r"\baugmantin\b", "augmentin"),
    (r"\bbrufen\b", "brufen"),
    (r"\bstock\b", "stock"),
    (r"\bstrips?\b", "strips"),
)

PHARMACY_STT_HINT = (
    "Panadol, Panadol Extra, Augmentin, Brufen, stock, strips, tablets, pharmacy, "
    "medicine, sales, cash, supplier, udhaar, Roman Urdu"
)


@lru_cache(maxsize=1)
def _medicine_names(db_path: str | None = None) -> tuple[str, ...]:
    path = db_path or str(DEFAULT_DB_PATH)
    try:
        result = execute_query(
            "SELECT DISTINCT name FROM medicines WHERE is_active = 1 ORDER BY name",
            db_path=path if db_path else None,
        )
        return tuple(r["name"] for r in result.get("rows") or [] if r.get("name"))
    except Exception:
        return ()


def _name_lookup(names: tuple[str, ...]) -> dict[str, str]:
    return {n.lower(): n for n in names}


def fuzzy_medicine_token(token: str, names: tuple[str, ...], cutoff: float = 0.72) -> str | None:
    if len(token) < 4:
        return None
    lower = token.lower()
    lookup = _name_lookup(names)
    if lower in lookup:
        return lookup[lower]
    # Match against first word of multi-word medicines too
    for n in names:
        if lower in n.lower() or n.lower().startswith(lower[:5]):
            return n
    matches = difflib.get_close_matches(lower, [n.lower() for n in names], n=1, cutoff=cutoff)
    if matches:
        return lookup.get(matches[0])
    # Brand partial: "panadol" in "Panadol Extra"
    for n in names:
        if lower in n.lower().replace(" ", ""):
            return n
    return None


def normalize_pharmacy_speech(text: str, db_path: str | None = None) -> str:
    """Fix common STT mishears using static map + medicine list from DB."""
    if not text or not text.strip():
        return text
    out = text
    for pattern, repl in _STATIC_REPLACEMENTS:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    names = _medicine_names(str(db_path) if db_path else None)
    if not names:
        return out.strip()

    words = out.split()
    fixed: list[str] = []
    i = 0
    while i < len(words):
        # Try two-word window for "panadol extra"
        if i + 1 < len(words):
            pair = f"{words[i]} {words[i + 1]}"
            match = fuzzy_medicine_token(pair.replace(" ", ""), names, cutoff=0.65)
            if not match:
                for n in names:
                    if pair.lower() in n.lower():
                        match = n
                        break
            if match:
                fixed.append(match)
                i += 2
                continue
        match = fuzzy_medicine_token(re.sub(r"[^\w]", "", words[i]), names)
        fixed.append(match if match else words[i])
        i += 1
    return " ".join(fixed).strip()


def whisper_initial_prompt(db_path: str | None = None) -> str:
    names = _medicine_names(str(db_path) if db_path else None)
    sample = ", ".join(names[:12]) if names else "Panadol, Augmentin"
    return f"{PHARMACY_STT_HINT}. Medicines: {sample}."


def medicine_phrase_list(db_path: str | None = None, limit: int = 80) -> list[str]:
    """Medicine names for Azure phrase hints / STT boosting."""
    return list(_medicine_names(str(db_path) if db_path else None)[:limit])
