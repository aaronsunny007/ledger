"""LLM clients for free tiers: Gemini, Groq, and Ollama on your own machine.

All three are called over plain HTTP (no vendor SDKs), return JSON text and
report token counts. ``cost_usd`` is the *list-price* cost of the call, even
on a free tier, so the README can say what Ledger would cost at scale.
Prices are per million tokens and change; check them when you report.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

# (input $/1M tokens, output $/1M tokens), list prices for paid tiers.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}

DEFAULT_MODELS = {
    "gemini": ("gemini-2.5-flash-lite", "gemini-2.5-flash"),
    "groq": ("llama-3.1-8b-instant", "llama-3.3-70b-versatile"),
    "ollama": ("qwen2.5:7b-instruct", "qwen2.5:14b-instruct"),
    "fake": ("fake", "fake-large"),
}


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    @property
    def cost_usd(self) -> float:
        p_in, p_out = PRICES.get(self.model, (0.0, 0.0))
        return (self.input_tokens * p_in + self.output_tokens * p_out) / 1_000_000


class LLM(Protocol):
    model: str

    def complete(self, system: str, user: str) -> LLMResult: ...


class _HttpLLM:
    model: str

    def __init__(self, timeout: float = 60, max_retries: int = 3):
        self._http = httpx.Client(timeout=timeout)
        self._max_retries = max_retries

    def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
        for attempt in range(self._max_retries + 1):
            resp = self._http.post(url, json=body, headers=headers)
            # Free tiers rate-limit per minute; back off and try again.
            if resp.status_code in (429, 500, 503) and attempt < self._max_retries:
                wait = float(resp.headers.get("retry-after", 2 ** (attempt + 2)))
                log.warning("LLM %s, retrying in %.0fs", resp.status_code, wait)
                time.sleep(min(wait, 60))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("unreachable")


class GeminiLLM(_HttpLLM):
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str):
        super().__init__()
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set (free key: https://aistudio.google.com)")
        self.model, self._key = model, api_key

    def complete(self, system: str, user: str) -> LLMResult:
        t0 = time.monotonic()
        data = self._post(
            self.URL.format(model=self.model),
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            {"x-goog-api-key": self._key},
        )
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        usage = data.get("usageMetadata", {})
        return LLMResult(
            text="".join(p.get("text", "") for p in parts),
            model=self.model,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )


class OpenAICompatibleLLM(_HttpLLM):
    """Groq (and any OpenAI-compatible endpoint)."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.groq.com/openai/v1"):
        super().__init__()
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set (free key: https://console.groq.com)")
        self.model, self._key, self._base = model, api_key, base_url.rstrip("/")

    def complete(self, system: str, user: str) -> LLMResult:
        t0 = time.monotonic()
        data = self._post(
            f"{self._base}/chat/completions",
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            {"Authorization": f"Bearer {self._key}"},
        )
        usage = data.get("usage", {})
        return LLMResult(
            text=data["choices"][0]["message"]["content"],
            model=self.model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )


class OllamaLLM(_HttpLLM):
    def __init__(self, model: str, url: str = "http://localhost:11434"):
        super().__init__(timeout=300)
        self.model, self._url = model, url.rstrip("/")

    def complete(self, system: str, user: str) -> LLMResult:
        t0 = time.monotonic()
        data = self._post(
            f"{self._url}/api/chat",
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            {},
        )
        return LLMResult(
            text=data["message"]["content"],
            model=self.model,
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )


class FakeLLM:
    """Scripted LLM for tests: ``respond(system, user) -> json text``."""

    def __init__(self, respond: Callable[[str, str], str], model: str = "fake"):
        self.model = model
        self._respond = respond
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> LLMResult:
        self.calls.append((system, user))
        text = self._respond(system, user)
        return LLMResult(
            text=text, model=self.model, input_tokens=len(user) // 4, output_tokens=len(text) // 4
        )


def make_llm(
    provider: str,
    model: str,
    *,
    gemini_api_key: str = "",
    groq_api_key: str = "",
    ollama_url: str = "http://localhost:11434",
) -> LLM:
    if provider == "gemini":
        return GeminiLLM(gemini_api_key, model)
    if provider == "groq":
        return OpenAICompatibleLLM(groq_api_key, model)
    if provider == "ollama":
        return OllamaLLM(model, ollama_url)
    raise ValueError(f"unknown LLM provider {provider!r}")
