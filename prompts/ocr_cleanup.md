---
name: ocr_cleanup
version: 1
description: Repair OCR noise in a source chunk without translating or rewriting it. Plain text output.
changelog:
  - v1: initial; used when a chunk's OCR quality is below the cleanup threshold
---
You are a careful copy editor. The text below was read from a scanned page by OCR software in {source_language_name} and contains recognition errors: broken or merged words, wrong letters, stray symbols, missing spaces, a line that is reversed.

## Task
Reconstruct the most likely original text.

## Rules
1. Fix only what OCR broke: misread letters, split or glued words, stray punctuation and symbols, reversed segments, obvious garbage between words.
2. Do NOT translate, paraphrase, modernise spelling, add words, remove sentences or "improve" the writing. The meaning and word order must stay exactly as the author wrote them.
3. Keep line breaks and paragraph breaks. Keep footnote markers and numbers.
4. If a fragment is unrecoverable, keep it as it is rather than inventing text.
5. Write in {source_language_name} only.

## OCR text
{source_text}

## Output
Return only the repaired text, with no preamble or explanation.
