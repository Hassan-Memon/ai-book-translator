"""OCR engines behind one small interface.

Every engine takes a rendered page plus Tesseract language codes and returns
``OcrWord`` objects in PDF-point coordinates. The ladder decides which engine
to call; engines only say whether they are *available* on this machine and
do the recognition.

* ``TesseractCliEngine``: the ``tesseract`` binary via pytesseract. Gives per
  word confidences, which make the quality score sharp. Preferred when
  installed.
* ``MuPdfTesseractEngine``: the Tesseract build that ships inside PyMuPDF.
  Zero extra installs; needs only the ``*.traineddata`` packs (downloaded on
  demand). No confidences.
* ``EasyOcrEngine``: neural OCR (opt-in extra, ~2.5 GB with torch).
* ``VisionLlmEngine``: a multimodal model through the provider layer. The only
  engine that costs money or GPU time, so the ladder uses it last and only
  for pages the free engines read badly.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.pipeline.ocr.layout import OcrWord
from app.pipeline.ocr.preprocess import RenderedPage, enhance

logger = logging.getLogger(__name__)


@dataclass
class EngineResult:
    words: list[OcrWord]
    engine: str
    seconds: float
    has_confidence: bool
    # For engines that return plain text (vision LLM), the raw lines.
    plain_lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class OcrEngine:
    name = "base"
    needs_tessdata = False

    def available(self) -> bool:  # pragma: no cover - trivial
        return False

    def recognise(
        self, rendered: RenderedPage, langs: list[str], tessdata_dir: Path | None
    ) -> EngineResult:  # pragma: no cover - abstract
        raise NotImplementedError


def _point_tessdata(tessdata_dir: Path | None) -> None:
    r"""Tell the tesseract subprocess where the packs are. The environment
    variable is used instead of ``--tessdata-dir`` because pytesseract does not
    quote paths with spaces (``C:\Program Files\...``)."""
    import os

    if tessdata_dir is not None:
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)


class TesseractCliEngine(OcrEngine):
    name = "tesseract"
    needs_tessdata = True

    def __init__(self, psm: int = 3, binary: str | None = None):
        self.psm = psm
        self.binary = binary

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        if self.binary:
            return Path(self.binary).exists()
        return shutil.which("tesseract") is not None or any(
            Path(p).exists()
            for p in (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            )
        )

    def _configure(self) -> Any:
        import pytesseract

        if self.binary:
            pytesseract.pytesseract.tesseract_cmd = self.binary
        elif shutil.which("tesseract") is None:
            for p in (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ):
                if Path(p).exists():
                    pytesseract.pytesseract.tesseract_cmd = p
                    break
        return pytesseract

    def recognise(
        self, rendered: RenderedPage, langs: list[str], tessdata_dir: Path | None
    ) -> EngineResult:
        pytesseract = self._configure()
        started = time.perf_counter()
        image = enhance(rendered.image)
        config = f"--psm {self.psm} -c preserve_interword_spaces=1"
        _point_tessdata(tessdata_dir)
        data = pytesseract.image_to_data(
            image, lang="+".join(langs), config=config, output_type=pytesseract.Output.DICT
        )
        words: list[OcrWord] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = str(data["text"][i]).strip()
            if not text:
                continue
            x, y = float(data["left"][i]), float(data["top"][i])
            w, h = float(data["width"][i]), float(data["height"][i])
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            words.append(
                OcrWord(
                    text=text,
                    bbox=rendered.to_points(x, y, x + w, y + h),
                    conf=conf if conf >= 0 else None,
                    block=int(data["block_num"][i]),
                    para=int(data["par_num"][i]),
                    line=int(data["line_num"][i]),
                )
            )
        return EngineResult(
            words=words,
            engine=self.name,
            seconds=time.perf_counter() - started,
            has_confidence=True,
        )

    def detect_script(self, rendered: RenderedPage, tessdata_dir: Path | None) -> str | None:
        """Orientation & script detection (needs osd.traineddata). Returns the
        Tesseract script name, e.g. 'Arabic', 'Latin', 'Devanagari'."""
        try:
            pytesseract = self._configure()
            _point_tessdata(tessdata_dir)
            osd = pytesseract.image_to_osd(enhance(rendered.image), config="--psm 0")
        except Exception as exc:
            logger.debug("OSD failed: %s", exc)
            return None
        for line in osd.splitlines():
            if line.startswith("Script:"):
                return line.split(":", 1)[1].strip()
        return None


class MuPdfTesseractEngine(OcrEngine):
    """Tesseract compiled into PyMuPDF. The page is OCRed by MuPDF itself, so
    this engine works on the ``fitz.Page`` rather than our rendered image."""

    name = "mupdf"
    needs_tessdata = True

    def __init__(self, page: Any | None = None):
        self.page = page

    def available(self) -> bool:
        try:
            import fitz

            return hasattr(fitz.Page, "get_textpage_ocr")
        except ImportError:  # pragma: no cover
            return False

    def recognise(
        self, rendered: RenderedPage, langs: list[str], tessdata_dir: Path | None
    ) -> EngineResult:
        if self.page is None:
            raise RuntimeError("MuPdfTesseractEngine needs the fitz page")
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"language": "+".join(langs), "dpi": rendered.dpi, "full": True}
        if tessdata_dir is not None:
            kwargs["tessdata"] = str(tessdata_dir)
        textpage = self.page.get_textpage_ocr(**kwargs)
        raw_words = self.page.get_text("words", textpage=textpage)
        words = [
            OcrWord(
                text=str(w[4]).strip(),
                bbox=(float(w[0]), float(w[1]), float(w[2]), float(w[3])),
                conf=None,
                block=int(w[5]),
                para=0,
                line=int(w[6]),
            )
            for w in raw_words
            if str(w[4]).strip()
        ]
        return EngineResult(
            words=words,
            engine=self.name,
            seconds=time.perf_counter() - started,
            has_confidence=False,
        )


class EasyOcrEngine(OcrEngine):
    name = "easyocr"

    _LANG_MAP = {
        "ara": "ar",
        "urd": "ur",
        "fas": "fa",
        "eng": "en",
        "hin": "hi",
        "ben": "bn",
        "rus": "ru",
        "tur": "tr",
        "fra": "fr",
        "deu": "de",
        "spa": "es",
        "chi_sim": "ch_sim",
        "chi_tra": "ch_tra",
        "jpn": "ja",
        "kor": "ko",
        "tha": "th",
    }
    _reader_cache: dict[tuple[str, ...], Any] = {}

    def available(self) -> bool:
        try:
            import easyocr  # noqa: F401

            return True
        except ImportError:
            return False

    def recognise(
        self, rendered: RenderedPage, langs: list[str], tessdata_dir: Path | None
    ) -> EngineResult:
        import easyocr
        import numpy as np

        started = time.perf_counter()
        codes = tuple(dict.fromkeys(self._LANG_MAP.get(lang, "en") for lang in langs))
        reader = self._reader_cache.get(codes)
        if reader is None:
            reader = easyocr.Reader(list(codes), gpu=False, verbose=False)
            self._reader_cache[codes] = reader
        results = reader.readtext(np.asarray(enhance(rendered.image)), detail=1, paragraph=False)
        words: list[OcrWord] = []
        for idx, (box, text, conf) in enumerate(results):
            if not str(text).strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append(
                OcrWord(
                    text=str(text).strip(),
                    bbox=rendered.to_points(min(xs), min(ys), max(xs), max(ys)),
                    conf=float(conf) * 100.0,
                    block=0,
                    para=0,
                    line=idx,
                )
            )
        return EngineResult(
            words=words,
            engine=self.name,
            seconds=time.perf_counter() - started,
            has_confidence=True,
        )


VISION_OCR_PROMPT = (
    "You are transcribing one scanned page of a book written in {language}.\n"
    "Rules:\n"
    "- Output every line of text exactly as printed, one line per printed line, in reading order"
    " ({direction}). Keep columns separate: finish one column before the next.\n"
    "- Keep headings on their own line. Keep footnote markers and numbers as printed.\n"
    "- Skip page numbers and running headers.\n"
    "- Do not translate, summarise, correct or comment. If a word is unreadable write [?].\n"
    "- Return plain text only: no markdown, no JSON, no preamble."
)


class VisionLlmEngine(OcrEngine):
    name = "vision"

    def __init__(self, provider: Any, book_id: Any = None, language: str = "the source language"):
        self.provider = provider
        self.book_id = book_id
        self.language = language

    def available(self) -> bool:
        return self.provider is not None and bool(self.provider.supports_vision())

    async def recognise_async(
        self, rendered: RenderedPage, page_index: int, rtl: bool
    ) -> EngineResult:
        import base64
        import io

        from app.llm.provider import CallContext

        started = time.perf_counter()
        buf = io.BytesIO()
        # JPEG keeps the payload small for local vision models.
        rendered.image.convert("L").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        prompt = VISION_OCR_PROMPT.format(
            language=self.language,
            direction="right-to-left, top-to-bottom" if rtl else "left-to-right, top-to-bottom",
        )
        text = await self.provider.ainvoke_vision(
            prompt,
            b64,
            CallContext(node="ocr", book_id=self.book_id, chunk_index=page_index),
            mime="image/jpeg",
        )
        lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
        return EngineResult(
            words=[],
            engine=self.name,
            seconds=time.perf_counter() - started,
            has_confidence=False,
            plain_lines=lines,
        )
