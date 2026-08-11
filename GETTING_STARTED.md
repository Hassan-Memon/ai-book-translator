# TranslateBook AI — Complete Setup Guide

## Project Status

**✅ Built & Ready to Test:**
- PDF extraction pipeline (PyMuPDF + OCR)
- Format mapper (structure detection)
- Semantic chunking engine
- LangGraph translation agents
- FastAPI backend with REST API
- GitHub Models integration
- Database schema (tables created)

---

## Quick Start (5 minutes)

### 1. Database Setup

Database tables are already created ✓

Verify:
```bash
docker exec translatebook-db psql -U translatebook -d translatebook -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';"
```

Should show: 6 tables

### 2. GitHub Models Setup (Optional - for real translations)

Without a GitHub token, the system uses a Mock provider for testing.

To enable real translations via GitHub Models:

1. Get a token: https://github.com/settings/personal-access-tokens/new
2. Create fine-grained token (any scope works)
3. Copy token to `.env`:

```env
GITHUB_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=github
```

Test it:
```bash
cd backend
python app/test_llm.py
```

### 3. Start the Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Server runs at: **http://localhost:8000**

Health check:
```bash
curl http://localhost:8000/health
# Response: {"status":"ok","version":"0.1.0"}
```

---

## Test the Pipeline

### Option A: Upload PDF via API

```bash
curl -X POST http://localhost:8000/api/v1/books/upload \
  -F "title=Test Book" \
  -F "file=@test.pdf" \
  -F "source_language=ur" \
  -F "target_language=ar"
```

Response: Book ID + extraction results

### Option B: CLI Tool

```bash
cd backend

# Process a PDF locally
python -m app.cli process ./test.pdf --title "My Book" --source-lang ur --target-lang ar

# List processed books
python -m app.cli list-books
```

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/books/upload` | Upload PDF, extract, chunk |
| GET | `/api/v1/books/{book_id}` | Get book status & progress |
| GET | `/api/v1/books` | List all books |
| GET | `/health` | Health check |

---

## Architecture Overview

```
┌─────────────────────────────────────────┐
│     PDF Upload                          │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  1. Extraction (PyMuPDF + OCR)          │
│     → Text + blocks + metadata          │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  2. Format Mapping (Structure Detection)│
│     → Headings, bold, alignment, RTL    │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  3. Semantic Chunking                   │
│     → Respect paragraph boundaries      │
│     → Maintain ±2 context neighbors     │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  4. Store Chunks in Database            │
│     → Each chunk = 1 translation item   │
└────────────────┬────────────────────────┘
                 │
         (Ready for Translation Phase)
         (LangGraph Agents: T1, V, Term)
```

---

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── api/routes.py        # REST endpoints
│   ├── agents/              # LangGraph agents
│   │   ├── translation_agent.py
│   │   ├── verification_agent.py
│   │   └── terminology_agent.py
│   ├── pipeline/            # Core pipeline
│   │   ├── extractor.py
│   │   ├── format_mapper.py
│   │   ├── chunker.py
│   │   └── pipeline.py
│   ├── models/              # SQLAlchemy ORM
│   │   ├── book.py
│   │   ├── chunk.py
│   │   └── ...
│   ├── llm/                 # LLM providers
│   │   └── provider.py      # GitHub Models, Mock, etc.
│   └── core/                # Configuration
│       ├── config.py
│       └── database.py
├── alembic/                 # Database migrations
├── pyproject.toml           # Dependencies
└── test_llm.py             # Test GitHub Models
```

---

## Development Commands

### Backend

```bash
# Start development server
cd backend
uvicorn app.main:app --reload

# Run CLI
python -m app.cli --help

# Test LLM provider
python app/test_llm.py

# Initialize database (if needed)
python app/db_init.py

# Run tests
pytest tests/
```

### Database

```bash
# Access PostgreSQL
docker exec -it translatebook-db psql -U translatebook -d translatebook

# Check tables
\dt

# View books
SELECT id, title, status, total_chunks FROM book;
```

---

## Troubleshooting

### "Database connection refused"
- Database tables are already created ✓
- API will work for extraction/chunking
- Full migrations may require manual setup

### "GITHUB_TOKEN not set"
- This is optional
- System will use Mock provider for testing
- Add token to .env for real translations

### "ModuleNotFoundError: No module named 'easyocr'"
- OCR is optional
- Install with: `uv sync --extra ocr-local`
- Without it, vision LLM OCR is used

### "Port 8000 already in use"
- Change port: `uvicorn app.main:app --port 8001`
- Or kill existing process: `lsof -ti:8000 | xargs kill -9`

---

## Next Steps

1. ✅ PDF extraction — Ready to test
2. ✅ Chunking engine — Ready to test
3. ⏳ Translation agent — Ready with GitHub Models
4. ⏳ Verification agent — Ready with GitHub Models
5. ⏳ Terminology agent — Ready with GitHub Models
6. 🔜 React frontend — Not yet built
7. 🔜 Export (PDF/DOCX) — Not yet built

---

## Example Workflow

```bash
# 1. Start backend
cd backend && uvicorn app.main:app --reload &

# 2. Upload a book
curl -X POST http://localhost:8000/api/v1/books/upload \
  -F "title=Islamic Philosophy" \
  -F "file=@philosophy.pdf"

# Response:
# {"id": "abc-123", "total_chunks": 42, ...}

# 3. Check status
curl http://localhost:8000/api/v1/books/abc-123

# 4. (Coming soon) Start translation
# POST http://localhost:8000/api/v1/books/abc-123/translate

# 5. (Coming soon) Review translations
# Visit http://localhost:5173 (React frontend)
```

---

## Support

- **Docs**: README.md (architecture overview)
- **Config**: `.env` (all settings)
- **Prompts**: `./prompts/` (LLM templates, versioned)
- **Database**: `./backend/alembic/versions/` (schema migrations)

