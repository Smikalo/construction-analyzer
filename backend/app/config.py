"""Process-wide configuration loaded from env vars."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM provider
    llm_provider: Literal["openai", "ollama"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Optional visual-only document analysis
    document_analysis_enabled: bool = False
    document_analysis_mode: Literal["visual_only"] = "visual_only"
    document_analysis_api_key: str = ""
    document_analysis_model: str = "gpt-4o-mini"

    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "qwen3:1.7b"

    # MemoryPalace
    memory_palace_database_url: str = (
        "postgresql://construction:construction@postgres:5432/memory_palace"
    )
    memory_palace_embedding_model: str = "nomic-embed-text"
    memory_palace_llm_model: str = "qwen3:1.7b"
    memory_palace_instance_id: str = "construction-analyzer"

    # LangGraph checkpointer
    checkpoint_db_path: str = "/app/data/checkpoints.sqlite"

    # Document ingestion
    documents_dir: str = "/app/data/documents"
    registry_db_path: str = "/app/data/registry.sqlite"
    report_sessions_db_path: str = "/app/data/report_sessions.sqlite"
    max_upload_bytes: int = 25_000_000

    # CAD/export conversion (optional; blank command template disables it)
    engineering_converter_command_template: str = ""
    engineering_converter_timeout_seconds: int = 30
    engineering_converter_output_dir: str = "/app/data/conversions"
    engineering_converter_output_extension: str = ".pdf"
    engineering_converter_smoke_input_path: str = ""

    # Knowledge base backend selector: "fake" (tests/dev) or "memorypalace"
    kb_backend: Literal["fake", "memorypalace"] = "fake"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_for_tests() -> None:
    """Test-only hook so we can reload env vars between tests."""
    global _settings
    _settings = None
