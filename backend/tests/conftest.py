"""Test fixtures.

Integration tests run against a real Postgres (TEST_DATABASE_URL, default
translatebook_test on the docker-compose server). The schema is created with
Alembic once per session and every table is truncated between tests. No test
touches a real LLM: the FakeProvider is deterministic.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command

os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("WORKER_INLINE", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("CHECKPOINTER", "postgres")

if sys.platform == "win32":
    # Same loop the app uses (app/core/eventloop.py): psycopg async needs a selector loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core import config as config_module  # noqa: E402

TEST_URL = os.environ.get("TEST_DATABASE_URL", config_module.settings.test_database_url)
# Point the whole app at the test database before any engine is created.
os.environ["DATABASE_URL"] = TEST_URL
config_module.get_settings.cache_clear()
config_module.settings = config_module.get_settings()
assert config_module.settings.database_url == TEST_URL

import app.core.database as database_module  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = (
    "app_setting",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "llm_call",
    "job",
    "terminology_flag",
    "verification_result",
    "glossary_term",
    "chunk",
    "book",
)


def _migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    # Alembic's env.py uses asyncio.run(); run it in a thread-free context
    # before the pytest-asyncio loop starts.
    _migrate(TEST_URL)


@pytest.fixture(autouse=True)
async def _clean_tables() -> None:
    yield
    async with database_module.engine.begin() as conn:
        # Checkpoint tables only exist once a saver has run setup(); skip missing ones.
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        existing = {r[0] for r in rows}
        tables = [t for t in TABLES if t in existing]
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(config_module.settings, "export_dir", tmp_path / "exports")
    return tmp_path


@pytest.fixture
def fake_provider():
    from app.llm.provider import FakeProvider
    from app.llm.recorder import record_llm_call

    return FakeProvider(cfg=config_module.settings, recorder=record_llm_call)


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """A tiny 2-page text PDF with Urdu-looking content and a «flagged» term."""
    import fitz

    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One", fontsize=20)
    page.insert_text((72, 110), "First paragraph about «salah» and worship.", fontsize=12)
    page.insert_text((72, 130), "Second sentence continues the thought.", fontsize=12)
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Chapter Two", fontsize=20)
    page2.insert_text((72, 110), "A paragraph on the second page.", fontsize=12)
    doc.save(path)
    doc.close()
    return path
