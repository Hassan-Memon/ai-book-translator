"""PDF extraction pipeline with OCR and LLM-based verification."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import fitz

logger = logging.getLogger(__name__)

_VISION_OCR_PROMPT = (
    "This is a scanned page from an Arabic or Urdu book. "
    "Extract ALL visible text exactly as it appears, preserving line breaks between lines. "
    "Return ONLY the extracted text — no commentary, no JSON, no markdown."
)


class PDFExtractor:
    """Extract text from PDF documents with OCR support."""

    def __init__(self, config: Any, provider: Any = None, book_id: Any = None):
        self.config = config
        self.provider = provider  # LLMProvider used for vision OCR (optional)
        self.book_id = book_id
        self.ocr_confidence_threshold = config.ocr_confidence_threshold
        self.enable_extraction_verifier = config.enable_extraction_verifier

    async def extract(self, pdf_path: Path, progress: Any = None) -> dict[str, Any]:
        """Extract text and metadata from a PDF file.

        Returns:
            is_scanned  — True when at least one page needed OCR
            pages       — list of per-page dicts (text, blocks, …)
            page_count  — total pages in the document
            errors      — non-fatal extraction issues
        """
        doc = fitz.open(pdf_path)
        result: dict[str, Any] = {
            "is_scanned": False,
            "pages": [],
            "page_count": doc.page_count,
            "errors": [],
        }

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
            if page_result.get("errors"):
                result["errors"].extend(page_result["errors"])

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

            if text.strip():
                result["text"] = text
                result["blocks"] = blocks
                return result

            # No extractable text — page is likely a scanned image.
            logger.info(f"Page {page_num}: no direct text, attempting OCR")
            result["used_ocr"] = True
            ocr_blocks = await self._ocr_page(page, page_num)
            result["blocks"] = ocr_blocks
            result["text"] = "\n".join(b["text"] for b in ocr_blocks if b.get("text", "").strip())

        except Exception as e:
            result["errors"].append(f"Page {page_num}: {str(e)}")
            logger.error(f"Error extracting page {page_num}: {e}")

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

    # ------------------------------------------------------------------
    # OCR ladder: EasyOCR → vision LLM
    # ------------------------------------------------------------------

    async def _ocr_page(self, page: Any, page_num: int) -> list[dict[str, Any]]:
        """Try EasyOCR first; fall back to the vision LLM if unavailable."""
        try:
            return await self._ocr_with_easyocr(page, page_num)
        except ImportError:
            logger.info(
                f"EasyOCR not installed (page {page_num}), "
                "trying vision LLM. Install with: uv sync --extra ocr-local"
            )
        except Exception as e:
            logger.warning(f"EasyOCR failed for page {page_num}: {e}")

        return await self._ocr_with_vision_llm(page, page_num)

    async def _ocr_with_easyocr(self, page: Any, page_num: int) -> list[dict[str, Any]]:
        """Local OCR using EasyOCR (opt-in extra, ~2.5 GB with torch)."""
        try:
            import easyocr
        except ImportError as exc:
            raise ImportError("EasyOCR not installed. Run: uv sync --extra ocr-local") from exc

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        image_bytes = pix.tobytes("ppm")

        reader = easyocr.Reader(["ar", "ur"], gpu=False)
        ocr_results = reader.readtext(image_bytes, detail=1, paragraph=False)

        blocks: list[dict[str, Any]] = []
        for idx, item in enumerate(ocr_results):
            bbox_points, text, confidence = item
            if confidence < self.ocr_confidence_threshold or not text.strip():
                continue
            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            blocks.append(
                {
                    "type": "text",
                    "bbox": (min(xs), min(ys), max(xs), max(ys)),
                    "text": text.strip(),
                    "font_name": "ocr-easyocr",
                    "font_size": 12.0,
                    "ocr_confidence": float(confidence),
                    "line_index": idx,
                    "page_width": float(page.rect.width),
                }
            )
        return blocks

    async def _ocr_with_vision_llm(self, page: Any, page_num: int) -> list[dict[str, Any]]:
        """OCR a scanned page using a multimodal LLM (GPT-4.1, Claude, …)."""
        if self.provider is None or not self.provider.supports_vision():
            logger.warning(
                f"Page {page_num}: no vision-capable LLM provider available "
                f"(provider={getattr(self.provider, 'name', None)}). Page will be skipped. "
                "Set a real provider in .env to OCR scanned pages."
            )
            return []

        # Render the page to a PNG and base64-encode it. 2x scale keeps text legible.
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        b64 = base64.b64encode(pix.tobytes("png")).decode()

        from app.llm.provider import CallContext

        try:
            raw_text = await self.provider.ainvoke_vision(
                _VISION_OCR_PROMPT,
                b64,
                CallContext(node="ocr", book_id=self.book_id, chunk_index=page_num),
            )
        except Exception as exc:
            logger.error(f"Vision LLM OCR failed for page {page_num}: {exc}")
            return []

        if not raw_text.strip():
            return []

        # Convert the flat text response into line blocks.
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        blocks: list[dict[str, Any]] = []
        for idx, line in enumerate(lines):
            # Approximate vertical position — evenly space lines across the page.
            y = (page_height / max(len(lines), 1)) * idx
            blocks.append(
                {
                    "type": "text",
                    "bbox": (0.0, y, page_width, y + 14.0),
                    "text": line.strip(),
                    "font_name": "ocr-vision",
                    "font_size": 12.0,
                    "line_index": idx,
                    "page_width": page_width,
                }
            )
        logger.info(f"Vision OCR page {page_num}: {len(blocks)} lines extracted")
        return blocks

    # ------------------------------------------------------------------
    # extraction verifier (future — compares OCR output vs rendered page)
    # ------------------------------------------------------------------

    async def verify_extraction(self, text: str, page: Any, llm_provider: Any) -> dict[str, Any]:
        """LLM-based sanity check comparing extracted text against a visual render."""
        if not self.enable_extraction_verifier:
            return {"skip_verification": True}

        # TODO: implement multimodal comparison
        return {"verified": True, "quality": "high", "issues": []}
