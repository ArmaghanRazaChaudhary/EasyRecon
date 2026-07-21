"""LLM client for EasyRecon — Groq intent + answers, local Qwen for SQL."""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

Role = Literal["intent", "local"]

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:27b")
OLLAMA_SQL_MODEL = os.getenv("OLLAMA_SQL_MODEL", OLLAMA_MODEL)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
EXPLAIN_PROVIDER = os.getenv("EXPLAIN_PROVIDER", "groq").lower()  # groq = fast; local = qwen

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_INTENT_MODEL = os.getenv("GROQ_INTENT_MODEL", "llama-3.3-70b-versatile")
INTENT_PROVIDER = os.getenv("INTENT_PROVIDER", "groq").lower()


class LLMError(RuntimeError):
    pass


def _groq_chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float,
    timeout: float,
) -> str:
    if not GROQ_API_KEY:
        raise LLMError(
            "GROQ_API_KEY not set. Get a free key at https://console.groq.com "
            "and add it to .env"
        )
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        response = httpx.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise LLMError("Cannot connect to Groq API. Check internet connection.") from exc
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"Groq API error: {exc.response.text}") from exc

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _ollama_chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float,
    timeout: float,
    num_predict: int | None = None,
) -> str:
    options: dict[str, Any] = {"temperature": temperature}
    if num_predict is not None:
        options["num_predict"] = num_predict
        options["num_ctx"] = 8192

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }
    try:
        response = httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise LLMError(
            "Cannot connect to Ollama. Is it running? Try: ollama serve"
        ) from exc
    except httpx.HTTPStatusError as exc:
        body = exc.response.text
        if exc.response.status_code == 404 and "not found" in body.lower():
            raise LLMError(
                f"Model '{model}' not found. Run: ollama pull {model}"
            ) from exc
        raise LLMError(f"Ollama error: {body}") from exc

    data = response.json()
    return data["message"]["content"].strip()


def chat_intent(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: float = 60.0,
) -> str:
    """Scope + intent understanding — Groq by default, Ollama fallback."""
    use_groq = INTENT_PROVIDER == "groq" and bool(GROQ_API_KEY)
    if use_groq:
        return _groq_chat(
            messages,
            model=model or GROQ_INTENT_MODEL,
            temperature=temperature,
            timeout=timeout,
        )
    return _ollama_chat(
        messages,
        model=model or OLLAMA_MODEL,
        temperature=temperature,
        timeout=timeout,
        num_predict=600,
    )


def chat_local(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: float = 180.0,
    num_predict: int | None = None,
    sql: bool = False,
) -> str:
    """Local Ollama — use sql=True for SQL generation with smaller token budget."""
    return _ollama_chat(
        messages,
        model=model or (OLLAMA_SQL_MODEL if sql else OLLAMA_MODEL),
        temperature=temperature,
        timeout=timeout,
        num_predict=num_predict,
    )


def chat_explain(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> str:
    """Short Roman Urdu answer — Groq by default (fast), local fallback."""
    if EXPLAIN_PROVIDER == "groq" and GROQ_API_KEY:
        return _groq_chat(
            messages,
            model=GROQ_INTENT_MODEL,
            temperature=temperature,
            timeout=timeout,
        )
    return _ollama_chat(
        messages,
        model=OLLAMA_MODEL,
        temperature=temperature,
        timeout=timeout,
        num_predict=350,
    )


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: float = 180.0,
    role: Role = "local",
) -> str:
    if role == "intent":
        return chat_intent(messages, model=model, temperature=temperature, timeout=timeout)
    return chat_local(messages, model=model, temperature=temperature, timeout=timeout)


def list_ollama_models(timeout: float = 10.0) -> list[str]:
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise LLMError("Cannot connect to Ollama.") from exc
    models = response.json().get("models", [])
    return [m["name"] for m in models]


def health_check() -> dict[str, Any]:
    ollama_models: list[str] = []
    ollama_ok = False
    try:
        ollama_models = list_ollama_models()
        ollama_ok = True
    except LLMError:
        pass

    groq_configured = bool(GROQ_API_KEY)
    model_ready = ollama_ok and any(
        m == OLLAMA_MODEL or m.startswith(f"{OLLAMA_MODEL}:")
        for m in ollama_models
    )
    return {
        "intent_provider": INTENT_PROVIDER,
        "explain_provider": EXPLAIN_PROVIDER,
        "groq_configured": groq_configured,
        "groq_model": GROQ_INTENT_MODEL,
        "ollama_url": OLLAMA_BASE_URL,
        "ollama_model": OLLAMA_MODEL,
        "ollama_sql_model": OLLAMA_SQL_MODEL,
        "ollama_models_available": ollama_models,
        "ollama_ready": model_ready,
        "intent_ready": groq_configured if INTENT_PROVIDER == "groq" else model_ready,
    }


OllamaError = LLMError
