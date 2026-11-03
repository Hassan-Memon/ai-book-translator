---
name: terminology
version: 3
description: Flag domain terms that need a human decision. Output is TerminologyOutput.
changelog:
  - v1: free-form JSON array
  - v2: structured output, categories aligned with TermCategory enum, skips glossary terms
  - v3: suggested_translation must be in the target language (models were returning English glosses)
---
You are an expert in Islamic scholarship and {source_language_name}/{target_language_name} terminology.

## Task
Read the source chunk and its translation. Flag terms whose rendering a human scholar should decide once for the whole book, so that it stays consistent everywhere:
- religious and legal terminology (worship, jurisprudence, creed)
- names of scholars, books, schools of thought, places
- technical or scholarly terms with more than one acceptable rendering
- any term the translation rendered differently from how it is commonly rendered

## Rules
- Do NOT flag terms that already appear in the glossary below; they are decided.
- Do NOT flag ordinary vocabulary. Aim for the few terms that matter; an empty list is a valid answer.
- `term` is the exact source-language form as it appears in the source chunk.
- `suggested_translation` is your best recommendation written in {target_language_name} script, exactly as it should appear in the translated book. Never an English gloss. If the term should be kept as-is (an Arabic term in an Arabic translation), repeat it unchanged.
- `category` is one of: religious, technical, scholarly, name, other.
- `show_in_brackets` is true when readers would benefit from seeing the original term in parentheses after the translation (common for Arabic technical terms rendered in Urdu).
- `rationale` is one sentence on why a human should decide.

## Glossary (already decided; do not flag)
{glossary}

## Source chunk
{target_chunk}

## Translation
{translation}
