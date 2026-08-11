from __future__ import annotations

from types import SimpleNamespace

import fitz

from app.models.base import ContentType
from app.pipeline.chunker import SemanticChunker
from app.pipeline.extractor import PDFExtractor
from app.pipeline.format_mapper import FormatMapper


def test_format_mapper_detects_rtl_heading_and_quranic_verse() -> None:
    mapper = FormatMapper(SimpleNamespace())

    heading = mapper.map_format(
        [{
            "type": "text",
            "text": "فصل اول: علم کی فضیلت",
            "font_name": "NotoNaskhArabic-Bold",
            "font_size": 20,
            "bbox": (180, 50, 420, 80),
            "page_width": 600,
        }],
        page_num=3,
        source_language="ur",
    )[0]
    verse = mapper.map_format(
        [{
            "type": "text",
            "text": "﴿اقرأ باسم ربك الذي خلق﴾",
            "font_name": "NotoNaskhArabic-Regular",
            "font_size": 13,
            "bbox": (60, 120, 540, 145),
            "page_width": 600,
        }],
        page_num=3,
        source_language="ur",
    )[0]

    assert heading.type == "heading_2"
    assert heading.bold is True
    assert heading.rtl is True
    assert heading.alignment == "center"
    assert heading.content_class == "heading"
    assert verse.content_class == "quranic_verse"


def test_semantic_chunker_respects_page_local_metadata() -> None:
    chunker = SemanticChunker(SimpleNamespace(chunk_target_chars=40))
    pages = [
        {"blocks": [{"type": "text", "text": "باب اول"}, {"type": "text", "text": "مختصر متن۔"}]},
        {"blocks": [{"type": "text", "text": "فصل دوم"}, {"type": "text", "text": "اگلا متن۔"}]},
    ]
    metadata = [
        [
            {"type": "heading_1", "content_class": "heading"},
            {"type": "text", "content_class": "prose"},
        ],
        [
            {"type": "heading_1", "content_class": "heading"},
            {"type": "text", "content_class": "prose"},
        ],
    ]

    chunks = chunker.chunk_document(pages, metadata)

    assert chunks[0].format_map[0]["type"] == "heading_1"
    assert chunks[-1].format_map[0]["type"] == "heading_1"
    assert all(chunk.content_type in {ContentType.heading, ContentType.prose} for chunk in chunks)


async def test_pdf_extractor_extracts_line_blocks_from_text_pdf(tmp_path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One", fontsize=18)
    page.insert_text((72, 110), "A paragraph that should become an extracted line.", fontsize=12)
    doc.save(pdf_path)
    doc.close()

    extractor = PDFExtractor(
        SimpleNamespace(ocr_confidence_threshold=0.75, enable_extraction_verifier=False)
    )

    result = await extractor.extract(pdf_path)

    assert result["page_count"] == 1
    assert result["is_scanned"] is False
    assert "Chapter One" in result["pages"][0]["text"]
    assert result["pages"][0]["blocks"][0]["font_size"] >= 17
    assert result["pages"][0]["blocks"][0]["page_width"] > 0
