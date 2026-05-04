<div align="center">

# ترجمة — TranslateBook AI

### Structure-aware, context-preserving AI book translation pipeline
**Built first for Urdu ↔ Arabic · Designed to scale to all languages**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_Pipeline-FF6B35?style=flat-square&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL_+_PGVector-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active_Development-f59e0b?style=flat-square)]()

[Problem Statement](#the-problem) · [Architecture](#architecture) · [Features](#features) · [Tech Stack](#tech-stack) · [Getting Started](#getting-started) · [Roadmap](#roadmap)

</div>

---

## The Problem

Millions of Islamic scholars, Madrasah students, and Muslim readers across Pakistan, India, and the broader Muslim world sit on opposite sides of a language wall. A Urdu-speaking student at a Madrasah in Lahore cannot access Arabic classical scholarship. An Arabic scholar's work cannot reach the 170 million Urdu speakers who need it.

**Existing tools fail this use case completely:**

- Google Translate destroys formatting — footnotes vanish, headings collapse, poetry becomes prose
- No tool maintains terminology consistency across an entire book (the same Islamic term gets translated five different ways across chapters)
- There is no human review mechanism for sensitive religious or domain-specific terminology
- Scanned PDF books — the most common format in this community — are ignored entirely

This is not a simple translation problem. Classical Islamic texts contain layered structure: chapter headings, sub-headings, footnotes, margin annotations, Quranic verses, Hadith references, and poetry — all with distinct formatting and distinct translation requirements.

**TranslateBook AI solves this end-to-end**, with a Human-in-the-Loop design that keeps a scholar in control of every critical terminology decision.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        TranslateBook AI                         │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────────┐    │
│  │  PDF     │    │  Extraction  │    │   Format Mapper    │    │
│  │  Upload  │───▶│  Engine      │───▶│   (Structure Map)  │    │
│  │          │    │  + OCR       │    │                    │    │
│  └──────────┘    └──────┬───────┘    └─────────┬──────────┘    │
│                         │                      │               │
│                         ▼                      ▼               │
│                  ┌──────────────────────────────────┐          │
│                  │     LLM Extraction Verifier       │          │
│                  │  (confirms extracted = visual)    │          │
│                  └──────────────┬───────────────────┘          │
│                                 │                               │
│                                 ▼                               │
│                  ┌──────────────────────────────────┐          │
│                  │      Semantic Chunking Engine     │          │
│                  │  (respects paragraphs/sections)   │          │
│                  └──────────────┬───────────────────┘          │
│                                 │                               │
│              ┌──────────────────▼──────────────────────┐       │
│              │           LangGraph Pipeline             │       │
│              │                                          │       │
│              │  ┌─────────────────────────────────┐    │       │
│              │  │  Translation Agent               │    │       │
│              │  │  chunk[n-2..n+2] → translate[n] │    │       │
│              │  └──────────────┬──────────────────┘    │       │
│              │                 │                        │       │
│              │  ┌──────────────▼──────────────────┐    │       │
│              │  │  Verification Agent              │    │       │
│              │  │  suggest-only, no full retrans.  │    │       │
│              │  └──────────────┬──────────────────┘    │       │
│              │                 │                        │       │
│              │  ┌──────────────▼──────────────────┐    │       │
│              │  │  Terminology Agent               │    │       │
│              │  │  flags terms → Human Decision   │    │       │
│              │  └──────────────┬──────────────────┘    │       │
│              │                 │                        │       │
│              │  ┌──────────────▼──────────────────┐    │       │
│              │  │  Glossary Memory                 │    │       │
│              │  │  PostgreSQL + PGVector           │    │       │
│              │  └─────────────────────────────────┘    │       │
│              └──────────────────────────────────────────┘       │
│                                 │                               │
│                                 ▼                               │
│              ┌──────────────────────────────────────┐          │
│              │          Export Engine                │          │
│              │     PDF (RTL) · DOCX · JSON           │          │
│              └──────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

### 1. PDF Ingestion & Intelligent Text Extraction

- Upload any PDF: digital (text-based) or scanned (image-based)
- **Auto-detection**: text-based PDFs go through PyMuPDF direct extraction; scanned PDFs trigger the OCR pipeline
- **Arabic/Urdu-aware OCR** using EasyOCR with Arabic trained models — handles right-to-left scripts, Nastaliq and Naskh fonts, and mixed Arabic-Urdu text
- **LLM Extraction Verifier**: a secondary LLM call compares the extracted text against a visual render of the PDF page, flagging any discrepancies before translation begins — this step ensures you are translating what is actually written, not what OCR guessed

### 2. Structure & Format Mapping

Every line of the book gets a structured metadata tag before translation starts:

```json
{
  "line_id": "ch2_p14_l3",
  "text": "فصل اول: علم کی فضیلت",
  "type": "heading_1",
  "font_size": 18,
  "bold": true,
  "alignment": "center",
  "rtl": true,
  "page": 14,
  "content_class": "chapter_heading"
}
```

- Detects: H1/H2/H3 headings, bold, italic, font size, text alignment, footnotes, margin notes
- Classifies content type: prose, poetry, Quranic verse, Hadith, numbered list, footnote
- This Format Map drives formatting reconstruction in the final exported PDF/DOCX

### 3. Semantic Chunking Engine

- Divides the book into meaningful chunks — not by arbitrary token count, but by paragraph and section boundaries
- Each chunk is assigned: position index, neighboring chunks (±2), source page range, content type
- Chunks are stored in PostgreSQL, enabling full resumability — close the app, reopen tomorrow, continue from exactly where you stopped
- Chunk size is tunable: smaller chunks for poetry and Hadith, larger for prose

### 4. Context-Aware Translation Agent (LangGraph)

The core of the pipeline. Built as a LangGraph stateful agent:

- Receives: `chunk[n]` (target) + `chunk[n-2]`, `chunk[n-1]`, `chunk[n+1]`, `chunk[n+2]` (context)
- Instruction to LLM: translate **only** the middle chunk — neighbors are for context awareness only
- Maintains a **per-book Glossary Memory**: terms already decided are injected into every translation prompt, ensuring consistency across the entire book
- RTL-aware output — both Urdu and Arabic are right-to-left; the pipeline preserves directionality in all outputs
- Iterates over every chunk in the book automatically, with progress saved after each chunk

### 5. Verification Agent

A dedicated second-pass agent, separate from the translation agent:

- Receives the translated chunk + its neighbors
- Prompt is strictly constrained: *"If this translation has issues, suggest specific corrections only. Do not retranslate the entire chunk."*
- Returns a diff-style suggestion object, not a replacement — human stays in control
- Suggestions are shown inline in the Review UI; the human accepts, rejects, or edits them

### 6. Terminology Agent (Human-in-the-Loop)

The most distinctive feature of this pipeline — designed specifically for Islamic and scholarly texts:

- Scans every chunk for domain-specific terms: Islamic terminology, classical Arabic titles, scholar names, book names, technical legal/theological terms
- For each flagged term, generates a suggestion: *"Consider showing as: نماز (Salah)"*
- Presents flags to the human reviewer in the UI — one decision at a time
- Human choices: **Accept** · **Reject** · **Edit** · **Apply to whole book**
- All decisions are saved to the book's Glossary — the same term is never flagged twice in the same book

### 7. Glossary & Translation Memory

- Per-book glossary that grows as translation progresses
- Prevents inconsistency: once a term is decided, it translates the same way everywhere
- Powered by PostgreSQL + PGVector: semantic search finds related terms even with spelling variations
- Glossary is exportable as CSV/JSON — reusable across books by the same author or subject area
- Importable: bring your own glossary before starting a new book

### 8. Progress Persistence & Resumability

- Every chunk's state is persisted to the database after completion
- Status tracking per chunk: `pending` → `extracted` → `translated` → `verified` → `terminology_reviewed` → `approved`
- Full resumability: crash, close, restart — the pipeline resumes from the last completed chunk
- Book-level progress dashboard: percentage complete per stage

### 9. Side-by-Side Review UI

- Original text on one side, translation on the other — both in correct RTL rendering
- Inline editing: click any chunk to edit the translation directly
- Verification suggestions displayed as highlighted diffs with Accept/Reject buttons
- Terminology flags shown as inline annotations with one-click decisions
- Keyboard shortcuts for fast review workflow

### 10. Multi-Model Support

- Abstract LLM provider interface — swap between Claude, GPT-4, Gemini, or local Ollama models
- Useful for cost control and quality comparison
- Local model support via Ollama (Qwen2.5 has strong Arabic/Urdu capabilities) — run entirely offline, zero API cost

### 11. Export Engine

- **PDF export**: reconstructs the translated book with original formatting preserved — headings, font sizes, bold, alignment, footnotes, RTL layout
- **DOCX export**: for editors and scholars who want to work in Word
- **JSON export**: structured export of all chunks + translations + glossary — for developers building on top of this pipeline

### 12. Project & Book Manager Dashboard

- Manage multiple books simultaneously
- Per-book status: title, language pair, % translated, % verified, % human-reviewed
- Activity log: see what the pipeline did and when

---

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Backend** | Python 3.11 + FastAPI | Best ecosystem for AI/PDF work; used across all prior experience |
| **AI Pipeline** | LangGraph + LangChain | Stateful agentic flows; battle-tested in production |
| **LLM (Cloud)** | Claude API / OpenAI API | Pluggable; free tiers available for development |
| **LLM (Local)** | Ollama (Qwen2.5, LLaMA 3) | Zero cost; strong Arabic/Urdu support; works offline |
| **PDF Extraction** | PyMuPDF (fitz) | Best Arabic script support; handles complex RTL layout |
| **OCR** | EasyOCR (Arabic model) | Free; accurate on Arabic/Urdu scanned text |
| **Database** | PostgreSQL + PGVector | Chunk storage, glossary semantic search, progress persistence |
| **Task Queue** | FastAPI BackgroundTasks → Celery | Long translation jobs need async processing |
| **Frontend** | React 18 + Vite | Component-based; RTL-capable |
| **UI Components** | shadcn/ui + Tailwind CSS | Professional; accessible; RTL support |
| **PDF Export** | ReportLab | Python-native; full RTL and Arabic font support |
| **DOCX Export** | python-docx | Lightweight; preserves formatting |
| **Containerization** | Docker + Docker Compose | One-command local setup |
| **Search (Glossary)** | PGVector semantic search | Already in stack; avoids extra dependency |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- Git

### Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/hassan-memon/translatebook-ai.git
cd translatebook-ai

# 2. Start infrastructure (PostgreSQL)
docker-compose up -d

# 3. Backend setup
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 4. Environment configuration
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY or OPENAI_API_KEY
# For fully local/free usage: set OLLAMA_BASE_URL=http://localhost:11434

# 5. Database migrations
alembic upgrade head

# 6. Start the backend
uvicorn app.main:app --reload --port 8000

# 7. Frontend setup (new terminal)
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

### Free/Offline Setup (Zero API Cost)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model with strong Arabic/Urdu support
ollama pull qwen2.5:7b

# Set in .env
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_MODEL=ollama/qwen2.5:7b
```

---

## Project Structure

```
translatebook-ai/
│
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI route handlers
│   │   ├── agents/           # LangGraph agent definitions
│   │   │   ├── translation_agent.py
│   │   │   ├── verification_agent.py
│   │   │   └── terminology_agent.py
│   │   ├── pipeline/         # Core pipeline orchestration
│   │   │   ├── extractor.py      # PDF extraction + OCR
│   │   │   ├── format_mapper.py  # Structure detection
│   │   │   ├── chunker.py        # Semantic chunking
│   │   │   └── exporter.py       # PDF/DOCX export
│   │   ├── models/           # SQLAlchemy database models
│   │   ├── prompts/          # All LLM prompt templates (versioned)
│   │   └── core/             # Config, database, dependencies
│   ├── tests/
│   ├── alembic/              # Database migrations
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── BookUpload/
│   │   │   ├── ChunkReview/      # Side-by-side translation review
│   │   │   ├── TerminologyPanel/ # Human-in-the-loop decisions
│   │   │   ├── GlossaryManager/
│   │   │   └── ExportPanel/
│   │   ├── pages/
│   │   └── hooks/
│   └── package.json
│
├── prompts/                  # Prompt templates (plain text, versioned)
│   ├── translation.md
│   ├── verification.md
│   ├── terminology.md
│   └── extraction_verify.md
│
├── docker-compose.yml
└── README.md
```

---

## Data Models

```python
# Core entities

class Book:
    id, title, author
    source_language, target_language   # e.g. "ur", "ar"
    status                             # processing | translating | review | done
    total_chunks, completed_chunks
    created_at, updated_at

class Chunk:
    id, book_id, index
    raw_text                           # original extracted text
    translated_text                    # LLM translation
    format_map                         # JSON: heading level, bold, font size, etc.
    content_type                       # prose | poetry | heading | footnote | verse
    status                             # pending | translated | verified | approved
    page_start, page_end

class GlossaryTerm:
    id, book_id
    original_term                      # e.g. "صلاة"
    translation                        # e.g. "نماز"
    with_original_in_brackets          # bool: show as "نماز (صلاة)"
    human_approved                     # bool
    scope                              # book | global

class VerificationResult:
    id, chunk_id
    suggestion                         # diff-style text suggestion
    accepted                           # bool

class TerminologyFlag:
    id, chunk_id
    term, suggested_translation
    show_in_brackets                   # bool suggestion
    human_decision                     # accepted | rejected | edited
    final_value                        # what was actually used
```

---

## Prompts

All LLM prompts live in `/prompts` as versioned markdown files. This is intentional — prompts are first-class artifacts in this project, not buried in code.

**Example: Translation Prompt**
```
You are a scholarly translator specializing in Islamic literature.
Translate ONLY the [TARGET CHUNK] from {source_lang} to {target_lang}.
The surrounding chunks are provided for context only — do not translate them.

Use the following established glossary for this book:
{glossary}

Preserve the meaning, tone, and scholarly register of the original.
Do not add explanations or commentary.

[CONTEXT BEFORE]
{chunk_n_minus_2}
{chunk_n_minus_1}

[TARGET CHUNK — TRANSLATE THIS]
{chunk_n}

[CONTEXT AFTER]
{chunk_n_plus_1}
{chunk_n_plus_2}
```

---

## Roadmap

### Phase 1 — Foundation (Current)
- [x] Project architecture design
- [x] Data model definition
- [x] Prompt template design
- [ ] PDF extraction pipeline (PyMuPDF + EasyOCR)
- [ ] Format mapper
- [ ] Database schema + migrations
- [ ] Semantic chunking engine

### Phase 2 — Translation Pipeline
- [ ] LangGraph translation agent
- [ ] Glossary memory integration
- [ ] LangGraph verification agent
- [ ] Terminology detection agent
- [ ] Progress persistence & resumability

### Phase 3 — Review UI
- [ ] Book upload & project dashboard
- [ ] Side-by-side chunk review interface
- [ ] Human-in-the-loop terminology panel
- [ ] Verification diff display

### Phase 4 — Export & Polish
- [ ] PDF export with RTL formatting preserved
- [ ] DOCX export
- [ ] Multi-model support (Ollama, Claude, OpenAI)
- [ ] Docker Compose full-stack setup

### Future
- [ ] Language pair expansion beyond Urdu ↔ Arabic
- [ ] Collaborative review (multiple reviewers per book)
- [ ] API for third-party integrations
- [ ] Batch processing multiple books

---

## Target Users

- **Madrasah students and scholars** in Pakistan and India working across Urdu and Arabic
- **Islamic publishers** producing bilingual editions
- **Individual researchers** translating classical texts for personal study
- **Muslim communities** wanting access to scholarship in their native language

---

## Contributing

This project is in active early development. Contributions, issue reports, and feedback are welcome — especially from Urdu/Arabic speakers who can test translation quality.

```bash
git checkout -b feature/your-feature-name
# make changes
git commit -m "feat: describe your change"
git push origin feature/your-feature-name
# open a Pull Request
```

---

## Author

**Hassan Memon** — Python Developer · AI Engineer · LangChain/LangGraph Open Source Contributor

[LinkedIn](https://www.linkedin.com/in/hassan-memon-a109b3257/) · [GitHub](https://github.com/hassan-memon) · hassan.ghaddai@live.com

---

<div align="center">

*Built to bridge the language gap in Islamic scholarship.*
*لغت کی آڑ کو زائل کرنے کے لیے بنایا گیا ایک شاہکار۔*

</div>



[//]: # (# AI Book Translator — Urdu to Arabic with Context-Aware LLMs)

[//]: # (An AI-powered Urdu to Arabic book translator that intelligently processes documents &#40;PDF, Word, Excel, or images&#41;, chunks content based on structure, and uses multi-stage LLM agents to ensure accurate, context-aware, and faithful translation without omissions or additions.)

[//]: # ()
[//]: # ()
[//]: # (have to create an Urdu to Arabic Translation Agent, that will take a file in pdf/doc/docs/excel &#40;or image&#41; format and it will:)

[//]: # (- read the document )

[//]: # (- chunking using smart and new chunking tequniuques on paraghps and and haddings)

[//]: # (- have there should have sevral nodes each responsible for specific task:)

[//]: # (	* translating the chunk word by word must sure it not miss or add any thing throw llm)

[//]: # (	* correct the word by word translation and make it near to the Arabic Context and style but stic to 		the orginal content, no addition and no missing.)

[//]: # (	* comparision between orginal content in Urdu &#40;along with two neighbor chunks in Urdu or we can do 		this step in the next separate step&#41; correct Arabic translation)

[//]: # (			-> if it pass the thereshlod like 80% or 90% it can be dicede after tests so it mark it as correct transtlation and proceed to the next step else mark it as bad and repete the cycle from correction step which is second step.)

[//]: # (	)