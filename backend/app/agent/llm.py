"""LLM provider factory.

Selecting the chat LLM is a single source of truth so the rest of the agent
code never imports a concrete provider class. Switching providers is one env var.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import Settings, get_settings


def get_llm(settings: Settings | None = None) -> BaseChatModel:
    s = settings or get_settings()

    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is required when LLM_PROVIDER=openai. "
                "Set it in your environment or switch LLM_PROVIDER to 'ollama'."
            )
        return ChatOpenAI(
            model=s.openai_model,
            api_key=s.openai_api_key,
            temperature=0.2,
            streaming=True,
        )

    if s.llm_provider == "ollama":
        return ChatOllama(
            model=s.ollama_model,
            base_url=s.ollama_host,
            temperature=0.2,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {s.llm_provider!r}")
