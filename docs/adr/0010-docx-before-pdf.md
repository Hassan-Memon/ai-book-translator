# ADR-0010: Export DOCX before PDF
Date: 2026-11-02 · Status: accepted (implemented in `backend/app/pipeline/exporter_docx.py`)

## Context
A translated book is not finished when it leaves this tool. An editor or publisher will still typeset it. Right-to-left and complex-script PDF generation (Nastaliq shaping, kashida, bidirectional runs with numbers and Latin citations) is hard to do well with Python PDF libraries, and a bad PDF is worse than none.

## Decision
Export DOCX first, with python-docx: headings as Word heading styles, bold lines kept bold, verses and poetry centred, `w:bidi` paragraphs for RTL languages, and the complex-script font set from the language registry (Noto Nastaliq Urdu, Noto Naskh Arabic, Noto Sans Devanagari and so on). Word and LibreOffice then shape the script correctly. Untranslated chunks are written as the source text with an `[untranslated]` marker, so nothing silently disappears.

## Alternatives considered
- **ReportLab PDF with arabic-reshaper and python-bidi**: workable for Arabic, poor for Nastaliq, and painful for mixed runs.
- **HTML to PDF via a headless browser**: good shaping, but a heavy dependency for the default install.
- **EPUB**: useful later for reading. It does not serve editors.

## Consequences
- Easier: the output is editable, fonts and direction are right in mainstream editors, and it is small and dependency-free.
- Harder: users wanting a print-ready PDF must export it from Word or LibreOffice. A PDF/EPUB export remains on the roadmap.
