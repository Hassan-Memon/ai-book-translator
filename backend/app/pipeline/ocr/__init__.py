"""Free, model-less OCR for scanned books (ADR-0011).

The ladder in :mod:`app.pipeline.ocr.ladder` reads a page the way a careful
human would, without any LLM:

1. render the page at 300 dpi, grey, auto-contrast (``preprocess``);
2. recognise words with bounding boxes and confidences (``engines``:
   Tesseract CLI, Tesseract bundled inside PyMuPDF, EasyOCR);
3. rebuild lines, detect columns and read them in the script's direction,
   drop page numbers and running heads (``layout``);
4. score the page with no reference text: word confidence, share of letters
   in the expected script, garbage ratio (``quality``);
5. only when the score is poor *and* the user configured a vision-capable
   model, escalate that page to vision OCR.

Language packs are resolved from the registry in :mod:`app.core.languages`
and downloaded on demand (``tessdata``), so any of the 50+ languages works
with nothing installed beyond the core dependencies.
"""

from app.pipeline.ocr.ladder import OcrLadder, ocr_status

__all__ = ["OcrLadder", "ocr_status"]
