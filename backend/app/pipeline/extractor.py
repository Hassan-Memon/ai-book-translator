"""PDF extraction: text layer when it exists, the free OCR ladder when it
does not, a vision model only for pages the ladder read badly.

Every page comes back as line blocks with geometry (so the format mapper can
find headings and the chunker can find paragraphs) plus, for OCRed pages, an
engine name and a quality report the UI shows to the reviewer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import fitz

from app.core.languages import guess_language
from app.pipeline.ocr import OcrLadder

logger = logging.getLogger(__name__)

# A text layer with fewer letters than this is treated as absent: many scans
# carry a junk invisible layer ("Nitro", page numbers only) that would
# otherwise hide the real text.
MIN_TEXT_LAYER_CHARS = 40


def _image_coverage(page: Any, blocks: list[dict[str, Any]]) -> float:
    """Share of the page area covered by images (0..1)."""
    area = float(page.rect.width * page.rect.height) or 1.0
    covered = 0.0
    for block in blocks:
        if block.get("type") == "image" and len(block.get("bbox") or ()) == 4:
            x0, y0, x1, y1 = block["bbox"]
            covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return min(1.0, covered / area)


class PDFExtractor:
    """Extract text from PDF documents with OCR support."""

    def __init__(
        self,
        config: Any,
        provider: Any = None,
        book_id: Any = None,
        source_language: str = "en",
    ):
        self.config = config
        self.provider = provider  # LLMProvider used for vision OCR (optional)
        self.book_id = book_id
        self.source_language = source_language
        self.ladder = OcrLadder(
            config,
            provider=provider,
            book_id=book_id,
            source_language=source_language,
            extra_languages=list(getattr(config, "ocr_extra_languages", []) or []),
        )

    async def extract(self, pdf_path: Path, progress: Any = None) -> dict[str, Any]:
        """Extract text and metadata from a PDF file.

        Returns:
            is_scanned  - True when at least one page needed OCR
            pages       - list of per-page dicts (text, blocks, ocr, ...)
            page_count  - total pages in the document
            errors      - non-fatal extraction issues
            ocr_summary - engines used, mean quality, escalated page count
        """
        doc = fitz.open(pdf_path)
        result: dict[str, Any] = {
            "is_scanned": False,
            "pages": [],
            "page_count": doc.page_count,
            "errors": [],
            "ocr_summary": {"pages_ocr": 0, "escalated": 0, "engines": {}, "mean_quality": None},
        }
        qualities: list[float] = []

        for page_num in range(doc.page_count):
            page = doc[page_num]
            if progress is not None:
                await progress(
                    0.05 + 0.85 * page_num / max(doc.page_count, 1),
                    f"extracting page {page_num + 1}/{doc.page_count}",
                )
            page_result = await self._extract_page(page, page_num)
            result["pages"].append(page_result)
            if page_result.get("used_ocr"):
                result["is_scanned"] = True
                summary = result["ocr_summary"]
                summary["pages_ocr"] += 1
                engine = page_result.get("ocr_engine") or "none"
                summary["engines"][engine] = summary["engines"].get(engine, 0) + 1
                if page_result.get("ocr_escalated"):
                    summary["escalated"] += 1
                q = (page_result.get("ocr_quality") or {}).get("score")
                if q is not None:
                    qualities.append(float(q))
            if page_result.get("errors"):
                result["errors"].extend(page_result["errors"])

        if qualities:
            result["ocr_summary"]["mean_quality"] = round(sum(qualities) / len(qualities), 3)
        doc.close()
        return result

    async def _extract_page(self, page: Any, page_num: int) -> dict[str, Any]:
        """Extract text from a single page, falling back to OCR when needed."""
        result: dict[str, Any] = {
            "page_number": page_num,
            "text": "",
            "used_ocr": False,
            "blocks": [],
            "errors": [],
        }

        try:
            blocks = self._extract_blocks(page)
            text = "\n".join(b["text"] for b in blocks if b.get("text", "").strip())
            letters = sum(1 for ch in text if ch.isalpha())

            # A short text layer is fine on a real text page (a chapter title
            # page); it is junk on a scan, where a big image covers the page.
            if letters >= MIN_TEXT_LAYER_CHARS or (
                letters > 0 and _image_coverage(page, blocks) < 0.5
            ):
                result["text"] = text
                result["blocks"] = blocks
                result["language_guess"] = guess_language(text)
                return result

            logger.info("page %s: no usable text layer, running OCR", page_num)
            result["used_ocr"] = True
            ocr = await self.ladder.ocr_page(page, page_num)
            ocr = await self.ladder.maybe_escalate(page, page_num, ocr)
            body = [b for b in ocr.blocks if b.get("kind", "text") == "text"]
            result["blocks"] = body
            result["text"] = "\n".join(b["text"] for b in body if b.get("text", "").strip())
            result["ocr_engine"] = ocr.engine
            result["ocr_escalated"] = ocr.escalated
            result["ocr_quality"] = ocr.quality.as_dict() if ocr.quality else None
            result["ocr_seconds"] = round(ocr.seconds, 2)
            result["language_guess"] = guess_language(result["text"]) if result["text"] else None
            for warning in ocr.warnings:
                result["errors"].append(f"Page {page_num + 1}: {warning}")
            if ocr.quality:
                logger.info(
                    "page %s: OCR via %s, quality %.2f (%d words, %.1fs)",
                    page_num,
                    ocr.engine,
                    ocr.quality.score,
                    ocr.quality.words,
                    ocr.seconds,
                )

        except Exception as e:
            result["errors"].append(f"Page {page_num + 1}: {e}")
            logger.error("Error extracting page %s: %s", page_num, e)

        return result

    # ------------------------------------------------------------------
    # direct text extraction (text-based PDFs)
    # ------------------------------------------------------------------

    def _extract_blocks(self, page: Any) -> list[dict[str, Any]]:
        """Extract structured line blocks from a text-based PDF page."""
        blocks: list[dict[str, Any]] = []
        raw_page = page.get_text("rawdict")

        for block in raw_page.get("blocks", []):
            if block.get("type") == 1:  # image block
                blocks.append({"type": "image", "bbox": tuple(block.get("bbox", ()))})
                continue
            if block.get("type") != 0:
                continue

            for line_index, line in enumerate(block.get("lines", [])):
                spans = line.get("spans", [])
                text = "".join(self._span_text(s) for s in spans).strip()
                if not text:
                    continue

                font_names = [s.get("font", "") for s in spans if s.get("font")]
                font_sizes = [
                    float(s.get("size", 0)) for s in spans if float(s.get("size", 0) or 0)
                ]
                flags = [int(s.get("flags", 0) or 0) for s in spans]

                blocks.append(
                    {
                        "type": "text",
                        "bbox": tuple(line.get("bbox") or block.get("bbox") or ()),
                        "text": text,
                        "font_name": self._dominant_value(font_names, default="unknown"),
                        "font_size": self._average(font_sizes, default=12.0),
                        "flags": max(flags) if flags else 0,
                        "line_index": line_index,
                        "page_width": float(page.rect.width),
                    }
                )

        return blocks

    def _span_text(self, span: dict[str, Any]) -> str:
        if "text" in span:
            return str(span["text"])
        return "".join(char.get("c", "") for char in span.get("chars", []))

    def _dominant_value(self, values: list[str], default: str) -> str:
        return max(set(values), key=values.count) if values else default

    def _average(self, values: list[float], default: float) -> float:
        return sum(values) / len(values) if values else default


async def sniff_pdf(pdf_path: Path, config: Any, max_pages: int = 3) -> dict[str, Any]:
    """Quick look at a PDF before the book is created: page count, whether a
    text layer exists, and a language guess from the first pages (OCR of page
    one when there is no text layer). Powers the upload wizard's auto-detect."""
    doc = fitz.open(pdf_path)
    info: dict[str, Any] = {
        "page_count": doc.page_count,
        "has_text_layer": False,
        "language_guess": None,
        "sample": "",
    }
    sample_parts: list[str] = []
    for i in range(min(max_pages, doc.page_count)):
        text = doc[i].get_text("text") or ""
        if sum(1 for ch in text if ch.isalpha()) >= MIN_TEXT_LAYER_CHARS:
            sample_parts.append(text)
    if sample_parts:
        info["has_text_layer"] = True
    else:
        # Scanned: let Tesseract's script detector choose the packs, then OCR
        # the first content page with those packs and guess from markers.
        from app.pipeline.ocr.engines import TesseractCliEngine
        from app.pipeline.ocr.preprocess import render_page

        script_to_codes = {
            "Arabic": ("ar", "ur", "fa"),
            "Latin": ("en",),
            "Devanagari": ("hi",),
            "Bengali": ("bn",),
            "Cyrillic": ("ru",),
            "Hebrew": ("he",),
            "Han": ("zh",),
            "Japanese": ("ja",),
            "Hangul": ("ko",),
            "Thai": ("th",),
            "Greek": ("el",),
        }
        page_index = min(1, doc.page_count - 1)  # page 2 is usually content, not cover
        rendered = render_page(doc[page_index], dpi=min(200, config.ocr_dpi))
        cli = TesseractCliEngine(psm=config.ocr_psm, binary=config.tesseract_cmd)
        codes: tuple[str, ...] = ("ar", "ur", "fa", "en")
        if cli.available():
            script = cli.detect_script(rendered, None)
            info["script"] = script
            if script in script_to_codes:
                codes = script_to_codes[script]
        ladder = OcrLadder(
            config, source_language=codes[0], extra_languages=list(codes[1:]) + ["en"]
        )
        ocr = await ladder.ocr_page(doc[page_index], page_index)
        sample_parts.append(ocr.text)
        info["ocr_quality"] = ocr.quality.as_dict() if ocr.quality else None
        info["ocr_engine"] = ocr.engine
    doc.close()
    sample = "\n".join(sample_parts)
    info["sample"] = sample[:600]
    info["language_guess"] = guess_language(sample)
    return info
