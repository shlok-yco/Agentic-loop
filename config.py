"""
config.py — Centralised settings for the VisualizationTool API.

All values are loaded from environment variables (or a .env file).
Import the pre-built singleton:

    from src.config import settings
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Paths ────────────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent  # project root


# ── Settings model ───────────────────────────────────────────────────────────


class Settings(BaseSettings):
    """
    Single source of truth for every configurable value in the project.
    Override any field by setting the corresponding env-var or .env entry.
    """

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # OPENAI_API_KEY == openai_api_key
        extra="ignore",  # silently ignore unknown env-vars
    )

    # ── FastAPI ──────────────────────────────────────────────────────────────

    app_title: str = "VisualizationTool API"
    app_description: str = "Agentic BI pipeline powered by LangGraph + FastAPI."
    app_version: str = "0.1.0"

    api_host: str = Field(default="0.0.0.0", description="Bind address for Uvicorn.")
    api_port: int = Field(default=5000, ge=1024, le=65535)
    api_reload: bool = Field(default=False, description="Hot-reload (dev only).")
    api_workers: int = Field(default=1, ge=1, description="Uvicorn worker count.")

    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"

    # CORS — comma-separated list of allowed origins, e.g.
    # CORS_ORIGINS="http://localhost:3000,https://app.example.com"
    cors_origins: list[str] = Field(default=["*"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # ── LLM / OpenAI ────────────────────────────────────────────────────────

    openai_api_key: SecretStr = Field(
        ...,
        description="OpenAI secret key — required.",
    )

    # Primary model used by the Supervisor / reasoning agents.
    llm_model: str = Field(
        default="gpt-5.2",
        description="OpenAI chat-completion model identifier.",
    )

    # Cheaper / faster model for lightweight tasks (e.g. column mapping).
    llm_fast_model: str = Field(
        default="gpt-4o-mini",
        description="Lightweight model for quick classification tasks.",
    )

    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=4096, ge=1)

    # ── LangGraph / Agent ────────────────────────────────────────────────────

    # Maximum number of steps the graph executor will run before aborting.
    langgraph_recursion_limit: int = Field(
        default=200,
        ge=1,
        description="LangGraph recursion / step limit (prevents infinite loops).",
    )

    # How many times an agent division may retry before the Supervisor aborts.
    max_qa_retries: int = Field(default=3, ge=0)

    # Checkpointer backend: "memory" (dev) or "sqlite" (persistent dev/staging).
    checkpointer_backend: Literal["memory", "sqlite"] = "memory"

    # Path for the SQLite checkpointer DB (only used when backend == "sqlite").
    sqlite_db_path: Path = Field(
        default=ROOT_DIR / "checkpoints.db",
        description="SQLite file for LangGraph checkpoint persistence.",
    )

    # ── Artifact / File Paths ────────────────────────────────────────────────

    # Template from .env: "ARTIFACTS/{team}/"
    artifact_path: str = Field(
        default="ARTIFACTS/{team}/",
        description="Artifact root template. Use str.format(team=...) to resolve.",
    )

    # Resolved absolute root for all run artifacts.
    artifact_root: Path = ROOT_DIR / "artifacts"

    # Temporary directory for intermediate pipeline files.
    tmp_dir: Path = ROOT_DIR / ".tmp"

    # ── Tavily (web-scraping / knowledge-base builder) ───────────────────────

    tavily_api_key: SecretStr | None = Field(
        default=None,
        description="Tavily API key — required only for knowledge-base scraping.",
    )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def get_artifact_dir(self, team: str) -> Path:
        """Return the resolved, created artifact directory for *team*."""
        path = Path(self.artifact_path.format(team=team))
        if not path.is_absolute():
            path = self.artifact_root / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        """Create all runtime directories that must exist before the app starts."""
        for d in (self.artifact_root, self.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def openai_api_key_str(self) -> str:
        """Return the raw API key string (unwrap SecretStr)."""
        return self.openai_api_key.get_secret_value()

    @property
    def tavily_api_key_str(self) -> str | None:
        """Return the raw Tavily key string, or None if not set."""
        return self.tavily_api_key.get_secret_value() if self.tavily_api_key else None


# ── Singleton ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.
    Call ``get_settings.cache_clear()`` in tests to force a reload.
    """
    s = Settings()  # type: ignore[call-arg]
    s.ensure_dirs()
    return s


# Convenience alias — import this everywhere:
#   from src.config import settings
settings: Settings = get_settings()
