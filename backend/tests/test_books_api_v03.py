"""v0.3 book endpoints: language validation, sniff, per-book settings, OCR extraction."""

from __future__ import annotations

import fitz
import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.main import create_app
from app.pipeline.extractor import PDFExtractor
from app.pipeline.ocr import tessdata
from app.pipeline.ocr.engines import MuPdfTesseractEngine, TesseractCliEngine


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t")


async def test_upload_rejects_unknown_language_and_keeps_domain(sample_pdf, tmp_storage) -> None:
    async with _client() as client:
        files = {"file": ("s.pdf", sample_pdf.read_bytes(), "application/pdf")}
        r = await client.post(
            "/api/v1/books", files=files, data={"source_language": "xx", "target_language": "ar"}
        )
        assert r.status_code == 400 and "Unknown language" in r.json()["detail"]

        r = await client.post(
            "/api/v1/books",
            files=files,
            data={
                "title": "Sample",
                "author": "A. Writer",
                "source_language": "en",
                "target_language": "hi",
                "domain": "novel / fiction",
                "instructions": "Warm tone.",
            },
        )
        assert r.status_code == 201, r.text
        book = r.json()
        assert book["author"] == "A. Writer" and book["domain"] == "novel / fiction"
        assert book["instructions"] == "Warm tone." and book["settings"] == {}

        r = await client.patch(
            f"/api/v1/books/{book['id']}",
            json={"domain": "history", "settings": {"quality_profile": "thorough", "x": ""}},
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["domain"] == "history"
        assert detail["settings"] == {"quality_profile": "thorough"}, "empty values are dropped"


async def test_sniff_reads_text_layer_and_guesses_language(sample_pdf) -> None:
    async with _client() as client:
        r = await client.post(
            "/api/v1/books/sniff",
            files={"file": ("s.pdf", sample_pdf.read_bytes(), "application/pdf")},
        )
        assert r.status_code == 200, r.text
        info = r.json()
        assert info["page_count"] == 2 and info["has_text_layer"] is True
        assert info["language_guess"] == "en"
        assert "Chapter One" in info["sample"]

        r = await client.post(
            "/api/v1/books/sniff", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        assert r.status_code == 400


def _engine_ready() -> bool:
    if not (TesseractCliEngine().available() or MuPdfTesseractEngine().available()):
        return False
    return bool(tessdata.ensure_packs(["eng"], settings.tessdata_dir, allow_download=False)[1])


@pytest.mark.skipif(not _engine_ready(), reason="no Tesseract engine with the eng pack")
async def test_extractor_ocrs_a_scanned_page_and_reports_quality(tmp_path) -> None:
    W, H = 1240, 1754  # A4 at 150 dpi
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    lines = [
        "Chapter One",
        "It was the best of times, it was the worst of times,",
        "it was the age of wisdom, it was the age of foolishness.",
        "We had everything before us, we had nothing before us.",
    ]
    for i, line in enumerate(lines):
        draw.text((110, 160 + i * 70), line, fill=0, font=font)
    draw.text((W // 2, H - 90), "17", fill=0, font=font)  # page number, should be dropped
    png = tmp_path / "scan.png"
    img.save(png)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, filename=str(png))
    pdf = tmp_path / "scan.pdf"
    doc.save(pdf)
    doc.close()

    result = await PDFExtractor(settings, source_language="en").extract(pdf)
    page0 = result["pages"][0]
    assert result["is_scanned"] and page0["used_ocr"]
    text = page0["text"].lower()
    assert "best of times" in text and "foolishness" in text
    assert text.index("best of times") < text.index("nothing before us")
    assert "17" not in page0["text"].split(), "page number tagged as margin furniture"
    assert page0["ocr_quality"]["score"] > 0.6
    assert page0["language_guess"] == "en"
    assert result["ocr_summary"]["pages_ocr"] == 1
