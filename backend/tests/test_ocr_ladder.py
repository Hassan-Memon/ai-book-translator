"""Free OCR ladder: layout reconstruction, quality scoring, engine selection.

Pure-geometry tests run everywhere. The end-to-end test renders a synthetic
page and OCRs it; it is skipped when no Tesseract engine is usable.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.pipeline.ocr import tessdata
from app.pipeline.ocr.engines import MuPdfTesseractEngine, TesseractCliEngine
from app.pipeline.ocr.ladder import OcrLadder
from app.pipeline.ocr.layout import (
    OcrLine,
    OcrWord,
    dehyphenate,
    detect_columns,
    group_lines,
    order_lines,
    split_wide_gaps,
    tag_margins,
)
from app.pipeline.ocr.preprocess import RenderedPage, enhance, ink_ratio, otsu_threshold
from app.pipeline.ocr.quality import assess


def _w(
    text: str,
    x0: float,
    y0: float,
    w: float = 30,
    h: float = 10,
    conf: float | None = 90,
    line: int = 0,
    block: int = 0,
) -> OcrWord:
    return OcrWord(
        text=text, bbox=(x0, y0, x0 + w, y0 + h), conf=conf, block=block, para=0, line=line
    )


def test_group_lines_and_wide_gap_splitting() -> None:
    # Two words on the left page and two on the right page stitched into one line.
    words = [_w("a", 10, 10), _w("b", 45, 10), _w("c", 400, 10), _w("d", 435, 10)]
    lines = group_lines(words)
    assert len(lines) == 2
    assert sorted(ln.text(rtl=False) for ln in lines) == ["a b", "c d"]
    single = OcrLine(words=[_w("x", 0, 0), _w("y", 35, 0)])
    assert len(split_wide_gaps(single)) == 1


def test_two_column_detection_and_rtl_reading_order() -> None:
    page_w = 600.0
    lines: list[OcrLine] = []
    # left column (x 20-250) and right column (x 350-580), 8 lines each
    for i in range(8):
        lines.append(OcrLine(words=[_w(f"L{i}", 20, 20 + i * 15, w=230)]))
        lines.append(OcrLine(words=[_w(f"R{i}", 350, 20 + i * 15, w=230)]))
    cols = detect_columns(lines, page_w)
    assert len(cols) == 2
    ordered = order_lines(lines, page_w, rtl=True)
    texts = [ln.text(rtl=True) for ln in ordered]
    assert texts[:8] == [f"R{i}" for i in range(8)]  # right column first for RTL
    assert texts[8:] == [f"L{i}" for i in range(8)]
    ordered_ltr = order_lines(lines, page_w, rtl=False)
    assert [ln.text(rtl=False) for ln in ordered_ltr][:8] == [f"L{i}" for i in range(8)]


def test_spanning_heading_splits_bands() -> None:
    page_w = 600.0
    heading = OcrLine(words=[_w("TITLE", 50, 100, w=500)])
    top_left = OcrLine(words=[_w("a", 20, 20, w=200)])
    top_right = OcrLine(words=[_w("b", 350, 20, w=200)])
    bottom_left = OcrLine(words=[_w("c", 20, 150, w=200)])
    bottom_right = OcrLine(words=[_w("d", 350, 150, w=200)])
    lines = [bottom_right, heading, top_left, bottom_left, top_right]
    for i in range(6):  # enough narrow lines for column detection
        lines.append(OcrLine(words=[_w(f"x{i}", 20, 200 + i * 12, w=200)]))
        lines.append(OcrLine(words=[_w(f"y{i}", 350, 200 + i * 12, w=200)]))
    ordered = [ln.text(rtl=False) for ln in order_lines(lines, page_w, rtl=False)]
    assert ordered.index("a") < ordered.index("b") < ordered.index("TITLE") < ordered.index("c")


def test_margin_tagging_marks_page_numbers_and_running_heads() -> None:
    page_w, page_h = 600.0, 800.0
    number = OcrLine(words=[_w("۱۹", 290, 10)])
    head = OcrLine(words=[_w("Book", 100, 12, w=120)])
    body = OcrLine(words=[_w("body", 50, 300, w=500)])
    tag_margins([number, head, body], page_w, page_h)
    assert number.kind == "page_number" and head.kind == "running_head" and body.kind == "text"


def test_dehyphenate_joins_latin_words() -> None:
    assert dehyphenate(["transla-", "tion works", "end"]) == ["translation works", "end"]


def test_quality_scores_separate_clean_from_garbage() -> None:
    clean = assess(
        "هذا كتاب عربي عن الفقه والحديث يقرأه الطلاب في المدارس",
        languages=["ar"],
        word_confs=[90] * 10,
    )
    garbage = assess(
        "الارشادويؤيدهمافىغايةالتحقيقمنهان BU Ay LLL كمافى", languages=["ar"], word_confs=[40] * 5
    )
    assert clean.score > 0.9
    assert garbage.score < 0.6
    assert garbage.garbage_ratio > clean.garbage_ratio
    no_conf = assess("هذا كتاب عربي عن الفقه والحديث", languages=["ar"])
    assert no_conf.mean_conf is None and no_conf.score <= 0.82
    assert assess("", languages=["ar"]).score == 0.0


def test_preprocess_helpers() -> None:
    img = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(img).rectangle((10, 10, 40, 40), fill=0)
    assert 0.05 < ink_ratio(img) < 0.15
    assert ink_ratio(Image.new("L", (10, 10), 255)) == 0.0
    import numpy as np

    arr = np.asarray(img)
    assert 0 <= otsu_threshold(arr) < 255  # any value between the two peaks is valid
    assert enhance(img, binarize=True).getextrema() == (0, 255)
    gradient = np.tile(np.arange(256, dtype=np.uint8), (4, 1))
    assert 100 < otsu_threshold(gradient) < 156


def _engine_available() -> bool:
    return TesseractCliEngine().available() or MuPdfTesseractEngine().available()


@pytest.mark.skipif(not _engine_available(), reason="no Tesseract engine on this machine")
def test_ladder_reads_a_synthetic_english_page(tmp_path) -> None:
    import fitz

    tdir, packs = tessdata.ensure_packs(["eng"], settings.tessdata_dir, allow_download=False)
    if not packs:
        pytest.skip("eng.traineddata not installed")
    W, H = 1200, 800
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=36) if hasattr(ImageFont, "load_default") else None
    for i, line in enumerate(
        ["The quick brown fox jumps over the lazy dog.", "Reading order matters more than letters."]
    ):
        draw.text((80, 120 + i * 70), line, fill=0, font=font)
    path = tmp_path / "page.png"
    img.save(path)
    doc = fitz.open()
    page = doc.new_page(width=W * 72 / 150, height=H * 72 / 150)
    page.insert_image(page.rect, filename=str(path))
    pdf = tmp_path / "scan.pdf"
    doc.save(pdf)
    doc.close()

    ladder = OcrLadder(settings, source_language="en")
    scanned = fitz.open(pdf)
    import asyncio

    result = asyncio.run(ladder.ocr_page(scanned[0], 0))
    assert result.engine in ("tesseract", "mupdf", "easyocr")
    text = result.text.lower()
    assert "quick" in text and "fox" in text and "reading" in text
    assert text.index("quick") < text.index("reading")
    assert result.quality is not None and result.quality.score > 0.5
    rp = RenderedPage(image=img, dpi=150, page_width_pt=W * 72 / 150, page_height_pt=H * 72 / 150)
    assert rp.to_points(150, 0, 300, 0)[0] == pytest.approx(72.0)
