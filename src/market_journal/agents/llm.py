"""Shared LLM factory.

Centralises model construction so agents stay thin and the offline path is
consistent. Uses langchain-openai's ChatOpenAI. When OpenAI is unavailable
(no key / offline), `get_llm` returns None and agents fall back to deterministic
behaviour.
"""
from __future__ import annotations

from market_journal.config import get_settings


def get_llm(smart: bool = False, temperature: float = 0.2):
    """Return a ChatOpenAI instance, or None when LLMs are unavailable."""
    settings = get_settings()
    if not settings.has_openai:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    model = settings.model_smart if smart else settings.model_cheap
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.openai_api_key,
        timeout=60,
        max_retries=2,
    )


def model_name(smart: bool = False) -> str:
    settings = get_settings()
    return settings.model_smart if smart else settings.model_cheap
