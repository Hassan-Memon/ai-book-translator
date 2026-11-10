# ADR-0009: Glossary lookup with trigram similarity now, embeddings later
Date: 2026-11-02 · Status: partially implemented (trigram in `services/glossary.py`, trigram memory in `services/translation.py`; embeddings planned)

## Context
The glossary holds the decided rendering of each term for a book. Small glossaries go into every prompt in full. Large ones (hundreds of terms) would crowd the prompt, so the right subset has to be found per chunk. Inflected and variant spellings ("صلاة" and "الصلاة") make exact matching miss.

## Decision
Use `pg_trgm` similarity (a GIN index on `glossary_term.original_term`) for lookups today. The `embedding` column (pgvector) already exists and is nullable, so semantic search can replace trigram matching without changing callers or the schema. v0.3 reuses the same trigram approach for translation memory, selecting the approved chunks most similar to the one being translated.

## Alternatives considered
- **Embeddings first**: needs an embedding endpoint, which local and demo setups may not have.
- **Exact match only**: misses inflected forms.
- **A separate vector database**: another service for a few thousand rows.

## Consequences
- Easier: works offline and with every provider, in one database.
- Harder: trigram similarity is spelling-based and misses synonyms. The glossary is still sent whole while books stay under a few hundred terms.
