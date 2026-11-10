"""The OCR ladder: free engines first, score, escalate only when needed.

``OcrLadder.ocr_page`` is the one entry point the extractor calls. It returns
ordered lines (as block dicts the format mapper already understands) plus a
quality report, and never raises for a bad page: a page the ladder cannot
read comes back empty with a warning, so one unreadable scan never kills a
400-page job.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.core.languages import get_language, language_name, tesseract_langs
from app.pipeline.ocr import tessdata as tessdata_mod
from app.pipeline.ocr.engines import (
    EasyOcrEngine,
    EngineResult,
    MuPdfTesseractEngine,
    OcrEngine,
    TesseractCliEngine,
    VisionLlmEngine,
)
from app.pipeline.ocr.layout import OcrLine, group_lines, order_lines, tag_margins
from app.pipeline.ocr.preprocess import RenderedPage, ink_ratio, render_page
from app.pipeline.ocr.quality import QualityReport, assess

logger = logging.getLogger(__name__)

FREE_ENGINE_ORDER = ("tesseract", "mupdf", "easyocr")


@dataclass
class PageOcr:
    blocks: list[dict[str, Any]]
    engine: str | None
    quality: QualityReport | None
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    escalated: bool = False

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.blocks if b.get("text"))


def _free_engines(cfg: Settings, page: Any) -> list[OcrEngine]:
    engines: list[OcrEngine] = [
        TesseractCliEngine(psm=cfg.ocr_psm, binary=cfg.tesseract_cmd),
        MuPdfTesseractEngine(page),
        EasyOcrEngine(),
    ]
    wanted = (cfg.ocr_engine or "auto").lower()
    if wanted == "auto":
        return [e for e in engines if e.available()]
    if wanted in ("vision", "none"):
        return []
    return [e for e in engines if e.name == wanted and e.available()]


def ocr_status(cfg: Settings | None = None) -> dict[str, Any]:
    """What the settings screen shows: which engines exist, which packs are
    installed, and what the ladder would do for a scanned page."""
    cfg = cfg or settings
    cli = TesseractCliEngine(psm=cfg.ocr_psm, binary=cfg.tesseract_cmd)
    mupdf = MuPdfTesseractEngine()
    easy = EasyOcrEngine()
    installed = sorted(tessdata_mod.all_installed_langs(cfg.tessdata_dir))
    return {
        "engine_setting": cfg.ocr_engine,
        "engines": [
            {
                "name": "tesseract",
                "label": "Tesseract (system binary)",
                "available": cli.available(),
                "confidence": True,
                "hint": "Install Tesseract 5 and make sure `tesseract` is on PATH.",
            },
            {
                "name": "mupdf",
                "label": "Tesseract (bundled in PyMuPDF)",
                "available": mupdf.available(),
                "confidence": False,
                "hint": "Always available; language packs download on first use.",
            },
            {
                "name": "easyocr",
                "label": "EasyOCR (neural, optional)",
                "available": easy.available(),
                "confidence": True,
                "hint": "uv sync --extra ocr-neural (about 2.5 GB with torch).",
            },
        ],
        "tessdata_dir": str(cfg.tessdata_dir),
        "system_tessdata_dirs": [str(p) for p in tessdata_mod.system_tessdata_dirs()],
        "installed_packs": installed,
        "download_packs": cfg.ocr_download_packs,
        "pack_repo": cfg.ocr_pack_repo,
        "dpi": cfg.ocr_dpi,
        "escalation_threshold": cfg.ocr_escalation_threshold,
        "vision_policy": cfg.ocr_vision,
    }


class OcrLadder:
    def __init__(
        self,
        cfg: Settings | None = None,
        *,
        provider: Any = None,
        book_id: Any = None,
        source_language: str = "en",
        extra_languages: list[str] | None = None,
    ):
        self.cfg = cfg or settings
        self.provider = provider
        self.book_id = book_id
        self.source_language = source_language
        # Books quote other languages (Arabic inside Urdu, Latin citations in
        # anything). OCR with the source packs plus these.
        self.languages = [source_language] + [
            code for code in (extra_languages or []) if code != source_language
        ]
        lang = get_language(source_language)
        self.rtl = bool(lang and lang.rtl)
        self._tessdata: tuple[Path | None, list[str]] | None = None

    # -- language packs -------------------------------------------------------

    def _packs(self) -> tuple[Path | None, list[str]]:
        if self._tessdata is None:
            wanted: list[str] = []
            for code in self.languages:
                wanted.extend(tesseract_langs(code))
            # Latin digits/citations appear in every script's books.
            if "eng" not in wanted:
                wanted.append("eng")
            self._tessdata = tessdata_mod.ensure_packs(
                wanted,
                self.cfg.tessdata_dir,
                allow_download=self.cfg.ocr_download_packs,
                repo=self.cfg.ocr_pack_repo,
            )
            directory, usable = self._tessdata
            logger.info("tessdata dir=%s packs=%s", directory, usable)
        return self._tessdata

    # -- main entry -----------------------------------------------------------

    async def ocr_page(self, page: Any, page_index: int) -> PageOcr:
        """OCR one ``fitz.Page``. Runs engines in a worker thread."""
        try:
            return await asyncio.to_thread(self._ocr_page_sync, page, page_index)
        except Exception as exc:
            logger.error("OCR failed on page %s: %s", page_index, exc)
            return PageOcr(blocks=[], engine=None, quality=None, warnings=[str(exc)])

    def _ocr_page_sync(self, page: Any, page_index: int) -> PageOcr:
        rendered = render_page(page, dpi=self.cfg.ocr_dpi)
        if ink_ratio(rendered.image) < 0.002:
            return PageOcr(blocks=[], engine="blank", quality=None, warnings=[])

        engines = _free_engines(self.cfg, page)
        if not engines:
            return PageOcr(
                blocks=[],
                engine=None,
                quality=None,
                warnings=["no free OCR engine available"],
            )
        tessdata_dir, packs = self._packs()
        if not packs:
            return PageOcr(
                blocks=[],
                engine=None,
                quality=None,
                warnings=["no Tesseract language packs available (offline?)"],
            )

        best: PageOcr | None = None
        best_rank = -1.0
        for engine in engines:
            try:
                result = engine.recognise(rendered, packs, tessdata_dir)
            except Exception as exc:
                logger.warning("%s failed on page %s: %s", engine.name, page_index, exc)
                continue
            candidate = self._assemble(result, rendered)
            rank = _rank(candidate)
            if best is None or rank > best_rank + 0.05:
                best, best_rank = candidate, rank
            # A good read from the first engine is final; only try the next
            # free engine when this one did badly.
            if best.quality and best.quality.score >= self.cfg.ocr_escalation_threshold:
                break
        if best is None:
            return PageOcr(blocks=[], engine=None, quality=None, warnings=["all engines failed"])
        return best

    # -- vision escalation (async, so it lives on the event loop) ------------

    async def maybe_escalate(self, page: Any, page_index: int, current: PageOcr) -> PageOcr:
        """Re-read a poorly OCRed page with a vision model when policy allows."""
        policy = (self.cfg.ocr_vision or "auto").lower()
        if policy == "off":
            return current
        if (
            policy == "auto"
            and current.quality
            and (current.quality.score >= self.cfg.ocr_escalation_threshold)
        ):
            return current
        engine = VisionLlmEngine(
            self.provider, book_id=self.book_id, language=language_name(self.source_language)
        )
        if not engine.available():
            if policy == "always":
                current.warnings.append("vision OCR requested but the provider has no vision model")
            return current
        rendered = await asyncio.to_thread(render_page, page, self.cfg.ocr_dpi)
        try:
            result = await engine.recognise_async(rendered, page_index, self.rtl)
        except Exception as exc:
            current.warnings.append(f"vision OCR failed: {exc}")
            return current
        candidate = self._assemble(result, rendered)
        candidate.escalated = True
        # Vision has no confidences, so compare on script validity + garbage.
        if current.quality is None or (
            candidate.quality and candidate.quality.score >= current.quality.score
        ):
            logger.info(
                "page %s: vision OCR replaced %s (%.2f -> %.2f)",
                page_index,
                current.engine,
                current.quality.score if current.quality else 0.0,
                candidate.quality.score if candidate.quality else 0.0,
            )
            return candidate
        return current

    # -- assembly -------------------------------------------------------------

    def _assemble(self, result: EngineResult, rendered: RenderedPage) -> PageOcr:
        width, height = rendered.page_width_pt, rendered.page_height_pt
        blocks: list[dict[str, Any]] = []
        confs: list[float] = []

        if result.plain_lines:
            # Vision output: no geometry, so lines are already in reading order.
            step = height / max(len(result.plain_lines), 1)
            for idx, text in enumerate(result.plain_lines):
                blocks.append(
                    _block(
                        text,
                        (0.0, idx * step, width, idx * step + 14.0),
                        width,
                        result.engine,
                        None,
                        idx,
                    )
                )
        else:
            lines: list[OcrLine] = group_lines(result.words)
            tag_margins(lines, width, height)
            ordered = order_lines(lines, width, self.rtl)
            idx = 0
            for ln in ordered:
                text = ln.text(self.rtl).strip()
                if not text:
                    continue
                conf = ln.conf
                if conf is not None:
                    if conf < self.cfg.ocr_confidence_threshold * 100 and len(text) <= 2:
                        continue  # stray specks recognised as a letter
                    confs.extend(w.conf for w in ln.words if w.conf is not None)
                block = _block(text, ln.bbox, width, result.engine, conf, idx)
                block["kind"] = ln.kind
                block["column"] = ln.column
                blocks.append(block)
                idx += 1

        text = "\n".join(b["text"] for b in blocks if b.get("kind", "text") == "text")
        report = assess(text, languages=self.languages, word_confs=confs or None)
        return PageOcr(
            blocks=blocks,
            engine=result.engine,
            quality=report,
            seconds=result.seconds,
            warnings=list(result.warnings),
        )


def _rank(page: PageOcr) -> float:
    """Comparable score across engines: a result without word confidences
    cannot be verified, so it is handicapped against one that has them."""
    if page.quality is None:
        return -1.0
    score = page.quality.score
    if page.quality.mean_conf is None:
        score -= 0.15
    return score


def _block(
    text: str,
    bbox: tuple[float, float, float, float],
    page_width: float,
    engine: str,
    conf: float | None,
    idx: int,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "text",
        "bbox": tuple(bbox),
        "text": text,
        "font_name": f"ocr-{engine}",
        "font_size": max(6.0, min(40.0, float(bbox[3] - bbox[1]) * 0.8)),
        "flags": 0,
        "line_index": idx,
        "page_width": page_width,
        "kind": "text",
        "column": 0,
    }
    if conf is not None:
        block["ocr_confidence"] = round(conf / 100.0, 3)
    return block
