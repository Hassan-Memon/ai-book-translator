"""Application settings, loaded from environment / .env.

Every knob the pipeline exposes lives here so that nothing reads os.environ
directly. See ../../.env.example for the documented set.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

APP_VERSION = "0.2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # .env is looked for next to the backend dir and at the repo root, so
        # either location works regardless of where uvicorn is launched from.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- database ---------------------------------------------------------
    # 5433 matches docker-compose.yml, which deliberately avoids 5432 because a
    # locally installed PostgreSQL usually already owns that port.
    database_url: str = (
        "postgresql+asyncpg://translatebook:translatebook@localhost:5433/translatebook_v2"
    )
    test_database_url: str = (
        "postgresql+asyncpg://translatebook:translatebook@localhost:5433/translatebook_test"
    )

    # --- server -----------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8010
    # When true the API process also runs the job worker loop (single-process
    # dev mode). Set false in production and run `python -m app.worker`.
    worker_inline: bool = True
    worker_poll_seconds: float = 1.5
    # A running job whose heartbeat is older than this is assumed dead and re-queued.
    job_stale_seconds: int = 600
    worker_id: str | None = None

    # --- llm provider -----------------------------------------------------
    llm_provider: str = "github"

    github_token: str | None = None
    github_base_url: str = "https://models.github.ai/inference"
    github_model: str = "openai/gpt-4.1"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"

    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.3-70b-instruct"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    vision_model: str | None = None  # defaults to the provider's chat model
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 1536

    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 120.0
    # Cap on output tokens per call. Keeps cost bounded and avoids providers
    # that reject requests whose max_tokens exceeds the account's credit.
    llm_max_output_tokens: int = 4000
    llm_max_retries: int = 3

    # --- pipeline tuning --------------------------------------------------
    ocr_confidence_threshold: float = 0.75
    verification_threshold: float = 0.8
    max_translation_retries: int = 1
    chunk_target_chars: int = 1200
    translation_concurrency: int = 3
    # LangGraph checkpointer for per-chunk resume: postgres | memory | none
    # (see app/agents/checkpoint.py)
    checkpointer: str = "postgres"
    # FakeProvider only: simulated latency per call (lets e2e tests kill a worker mid-job).
    fake_llm_delay_ms: int = 0
    enable_extraction_verifier: bool = False
    # Content types that are copied through untouched (never machine-translated).
    # NoDecode: read as a plain comma-separated string (see _split_csv), not JSON.
    passthrough_content_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["quranic_verse"]
    )

    # --- storage ----------------------------------------------------------
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    export_dir: Path = BACKEND_DIR / "data" / "exports"
    prompts_dir: Path = REPO_ROOT / "prompts"
    fonts_dir: Path = BACKEND_DIR / "fonts"
    frontend_dist_dir: Path = REPO_ROOT / "frontend" / "dist"

    # --- misc -------------------------------------------------------------
    log_level: str = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    @field_validator("cors_origins", "passthrough_content_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string so .env stays readable."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("upload_dir", "export_dir", "fonts_dir", mode="after")
    @classmethod
    def _resolve_storage(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def sync_database_url(self) -> str:
        """psycopg-free sync URL, used by Alembic's offline mode."""
        return self.database_url.replace("+asyncpg", "")

    @property
    def active_model(self) -> str:
        """Model id the configured provider will use for chat calls."""
        return {
            "github": self.github_model,
            "anthropic": self.anthropic_model,
            "openai": self.openai_model,
            "nvidia": self.nvidia_model,
            "ollama": self.ollama_model,
        }.get(self.llm_provider.lower(), "fake")

    def ensure_dirs(self) -> None:
        for directory in (self.upload_dir, self.export_dir, self.fonts_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
