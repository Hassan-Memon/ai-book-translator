# ADR-0003: Prompts are versioned markdown files with front-matter
Date: 2026-11-02 · Status: accepted (implemented in `backend/app/llm/prompts.py`, prompts in `prompts/`)

## Context
Prompt changes move translation quality more than most code changes. They must be reviewable in a diff, traceable to the output they produced, and comparable in the evaluation harness. Prompts embedded in Python strings get edited casually and leave no trace in the data.

## Decision
Each prompt is a markdown file in `prompts/` with a front-matter block holding `name`, an integer `version`, a `description` and a `changelog`. The loader caches the file, checks that every `{placeholder}` is supplied at render time (a missing one raises `PromptError`), and records `prompt_name` and `prompt_version` on every `llm_call` row.

## Alternatives considered
- **Python string constants**: no version, and edits are invisible in the ledger.
- **A prompt-management SaaS**: an external dependency for a self-hosted product, and prompts would live outside the repo.
- **Jinja templates**: more power than needed; `{name}` substitution with strict checking is enough.

## Consequences
- Easier: the cost ledger and the future eval tables can be grouped by prompt version, and a prompt regression shows up as a diff.
- Harder: bump `version` and add a changelog line on every meaningful edit. Placeholders are plain `{name}`, so a literal brace in a prompt must be doubled.
