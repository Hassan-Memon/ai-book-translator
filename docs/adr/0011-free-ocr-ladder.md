# ADR-0011: A free OCR ladder first, vision models only for poor pages
Date: 2026-11-09 · Status: accepted (implemented in `backend/app/pipeline/ocr/`, tests in `tests/test_ocr_ladder.py`)

## Context
Many books people need translated exist only as scans. Until v0.2, the extractor sent every page with no text layer to a vision LLM. That costs money on a cloud model, takes minutes per page on a local one, needs a configured model before a user can even see their book, and fails silently in demo mode. The product must handle 50+ languages, run on a laptop, and work before any model is configured.

## Decision
Read scanned pages with free engines first: Tesseract via the system binary, then the Tesseract build inside PyMuPDF, then EasyOCR if it is installed. Rebuild layout deterministically: lines, wide-gap splits, columns, RTL or LTR reading order, and margin furniture. Score each page with no reference text, using confidence, script validity, garbage and word shape. Escalate only pages below a threshold, first to the next free engine and then to a vision model if one is configured. Language packs come from the language registry and are downloaded on demand. Each chunk carries its OCR score and engine.

## Alternatives considered
- **Vision LLM for every page** (v0.2): the best on Nastaliq, but slow or costly, and unusable without a model.
- **EasyOCR or PaddleOCR as the default**: better on some scripts, but a 2.5 GB torch install, and the wheels lag new CPython releases. EasyOCR is kept as an optional extra.
- **Cloud OCR APIs** (Google Vision, Azure): excellent, but paid, vendor-locked, and they send the user's book off the machine.

## Consequences
- Easier: scanned books extract with zero configuration, offline once the packs are cached, at no cost. Reviewers see which chunks to distrust.
- Harder: Tesseract is weak on Urdu Nastaliq and faint prints, with a mean score of about 0.70 on the sample book. The documentation says so plainly, and the vision escalation exists for exactly that case. The quality score is a heuristic and needs calibration against hand-checked pages, which belongs with the evaluation harness.
