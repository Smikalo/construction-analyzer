"""Pin the LLM provider factory.

We do not exercise the real provider clients here; we only assert the factory
selects the right LangChain class based on settings. The integration tests in
the e2e suite are what actually hit OpenAI / Ollama.
"""

from __future__ import annotations

import pytest
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.agent.llm import get_llm
from app.config import Settings


class TestLLMFactory:
    def test_openai_provider_returns_chatopenai(self) -> None:
        settings = Settings(
            llm_provider="openai",
            openai_api_key="sk-test",
            openai_model="gpt-4o-mini",
        )
        llm = get_llm(settings)
        assert isinstance(llm, ChatOpenAI)
        assert llm.model_name == "gpt-4o-mini"

    def test_ollama_provider_returns_chatollama(self) -> None:
        settings = Settings(
            llm_provider="ollama",
            ollama_host="http://ollama:11434",
            ollama_model="qwen3:1.7b",
        )
        llm = get_llm(settings)
        assert isinstance(llm, ChatOllama)
        assert llm.model == "qwen3:1.7b"

    def test_openai_without_key_raises(self) -> None:
        settings = Settings(llm_provider="openai", openai_api_key="")
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            get_llm(settings)

    def test_factory_uses_default_settings_when_none_passed(self, monkeypatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_MODEL", "qwen3:1.7b")
        from app.config import reset_settings_for_tests

        reset_settings_for_tests()
        llm = get_llm()
        assert isinstance(llm, ChatOllama)
        reset_settings_for_tests()
