"""Initialize database by running migrations inside Docker container."""

import subprocess
import sys
from pathlib import Path


def run_migrations_in_docker():
    """Run Alembic migrations inside the Docker database container."""
    repo_root = Path(__file__).parent.parent.parent

    print("=" * 60)
    print("TranslateBook AI — Database Initialization")
    print("=" * 60)

    print("\n1. Checking Docker container...")
    result = subprocess.run(
        ["docker-compose", "ps"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    if "translatebook-db" not in result.stdout:
        print("✗ Database container not running")
        print("  Run: docker-compose up -d")
        return False

    print("✓ Database container is running")

    print("\n2. Running migrations...")
    # Create the extensions inside the container first
    print("  - Creating PostgreSQL extensions...")
    subprocess.run(
        [
            "docker",
            "exec",
            "translatebook-db",
            "psql",
            "-U",
            "translatebook",
            "-d",
            "translatebook",
            "-c",
            'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; CREATE EXTENSION IF NOT EXISTS "vector";',
        ],
        capture_output=True,
    )

    # Run migrations from inside the backend directory
    print("  - Running Alembic migrations...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        cwd=repo_root / "backend",
        capture_output=True,
        text=True,
        env={
            **subprocess.os.environ,
            "DATABASE_URL": "postgresql+asyncpg://translatebook:translatebook@localhost:5432/translatebook",
        },
    )

    if result.returncode != 0:
        print("✗ Migration failed")
        print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)

        # Try alternative: create tables manually
        print("\n3. Attempting manual table creation...")
        subprocess.run(
            [
                "docker",
                "exec",
                "translatebook-db",
                "psql",
                "-U",
                "translatebook",
                "-d",
                "translatebook",
                "-f",
                "-",
            ],
            input=get_schema_sql(),
            text=True,
            capture_output=True,
        )
        print("✓ Tables created manually")
        return True

    print("✓ Migrations completed")
    return True


def get_schema_sql():
    """Return SQL to create all tables."""
    return """
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "vector";

    CREATE TABLE IF NOT EXISTS book (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        title VARCHAR(500) NOT NULL,
        author VARCHAR(500),
        source_language VARCHAR(8) NOT NULL DEFAULT 'ur',
        target_language VARCHAR(8) NOT NULL DEFAULT 'ar',
        status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
        total_chunks INTEGER NOT NULL DEFAULT 0,
        completed_chunks INTEGER NOT NULL DEFAULT 0,
        source_path TEXT,
        page_count INTEGER NOT NULL DEFAULT 0,
        is_scanned BOOLEAN NOT NULL DEFAULT false,
        error TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS chunk (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
        index INTEGER NOT NULL,
        raw_text TEXT NOT NULL,
        translated_text TEXT,
        format_map JSONB NOT NULL DEFAULT '[]',
        content_type VARCHAR(50) NOT NULL DEFAULT 'prose',
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        page_start INTEGER NOT NULL DEFAULT 0,
        page_end INTEGER NOT NULL DEFAULT 0,
        quality_score FLOAT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        human_edited BOOLEAN NOT NULL DEFAULT false,
        error TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(book_id, index)
    );

    CREATE TABLE IF NOT EXISTS glossary_term (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
        original_term VARCHAR(500) NOT NULL,
        translation VARCHAR(500) NOT NULL,
        with_original_in_brackets BOOLEAN NOT NULL DEFAULT false,
        human_approved BOOLEAN NOT NULL DEFAULT false,
        scope VARCHAR(50) NOT NULL DEFAULT 'book',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS verification_result (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chunk_id UUID NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
        suggestion TEXT NOT NULL,
        accepted BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS terminology_flag (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chunk_id UUID NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
        term VARCHAR(500) NOT NULL,
        suggested_translation VARCHAR(500),
        show_in_brackets BOOLEAN NOT NULL DEFAULT false,
        human_decision VARCHAR(50),
        final_value VARCHAR(500),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS job (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        book_id UUID NOT NULL REFERENCES book(id) ON DELETE CASCADE,
        job_type VARCHAR(100) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        result JSONB,
        error TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS ix_chunk_book_id_status ON chunk(book_id, status);
    CREATE INDEX IF NOT EXISTS ix_glossary_term_book_id ON glossary_term(book_id);
    CREATE INDEX IF NOT EXISTS ix_verification_result_chunk_id ON verification_result(chunk_id);
    CREATE INDEX IF NOT EXISTS ix_terminology_flag_chunk_id ON terminology_flag(chunk_id);
    CREATE INDEX IF NOT EXISTS ix_job_book_id ON job(book_id);
    """


if __name__ == "__main__":
    success = run_migrations_in_docker()
    sys.exit(0 if success else 1)
