"""Application settings, loaded from environment / .env.

Every knob the pipeline exposes lives here so that nothing reads os.environ
directly. See ../../.env.example for the documented set.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


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
        "postgresql+asyncpg://translatebook:translatebook@localhost:5433/translatebook"
    )

    # --- llm provider -----------------------------------------------------
    llm_provider: str = "github"

    github_token: str | None = None
    github_base_url: str = "https://models.github.ai/inference"
    github_model: str = "openai/gpt-4.1"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    vision_model: str = "openai/gpt-4.1"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 1536

    # --- pipeline tuning --------------------------------------------------
    ocr_confidence_threshold: float = 0.75
    verification_threshold: float = 0.85
    max_translation_retries: int = 2
    chunk_target_chars: int = 1200
    translation_concurrency: int = 3
    enable_extraction_verifier: bool = True

    # --- storage ----------------------------------------------------------
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    export_dir: Path = BACKEND_DIR / "data" / "exports"
    prompts_dir: Path = REPO_ROOT / "prompts"
    fonts_dir: Path = BACKEND_DIR / "fonts"

    # --- misc -------------------------------------------------------------
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so .env stays readable."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("upload_dir", "export_dir", mode="after")
    @classmethod
    def _resolve_storage(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def sync_database_url(self) -> str:
        """psycopg-free sync URL, used by Alembic's offline mode."""
        return self.database_url.replace("+asyncpg", "")

    def ensure_dirs(self) -> None:
        for directory in (self.upload_dir, self.export_dir, self.fonts_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
