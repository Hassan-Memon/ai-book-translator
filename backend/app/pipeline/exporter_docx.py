"""DOCX export (ADR-0010: DOCX before PDF).

Walks the book's chunks in order and writes the translation with the
structure recovered from each chunk's ``format_map``: headings become Word
heading styles, bold lines stay bold, direction and font come from the
language registry (right-to-left for Arabic, Urdu, Persian, Hebrew; a Noto
font that shapes the script correctly in Word/LibreOffice). Untranslated
chunks are written as the source text with a marker so nothing is silently
dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from app.core.languages import font_for, is_rtl


def _set_rtl(paragraph: Any, rtl: bool) -> None:
    if not rtl:
        return
    ppr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    ppr.append(bidi)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _set_font(run: Any, font: str, size: float | None = None, bold: bool = False) -> None:
    run.font.name = font
    rpr = run._r.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:cs"), font)
    rfonts.set(qn("w:ascii"), font)
    rfonts.set(qn("w:hAnsi"), font)
    if size:
        run.font.size = Pt(size)
    run.font.bold = bold
    if bold:
        b = OxmlElement("w:bCs")
        rpr.append(b)


def _heading_level(format_map: list[dict[str, Any]]) -> int | None:
    for entry in format_map[:1]:
        t = str(entry.get("type", ""))
        if t.startswith("heading_"):
            try:
                return max(1, min(3, int(t.split("_", 1)[1])))
            except ValueError:
                return 1
    return None


def export_book_docx(
    *,
    title: str,
    source_language: str,
    target_language: str,
    chunks: list[dict[str, Any]],
    out_path: Path,
) -> Path:
    """``chunks`` items: {index, raw_text, translated_text, content_type, format_map, status}."""
    rtl = is_rtl(target_language)
    font = font_for(target_language)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = font
    style.font.size = Pt(13)

    title_p = doc.add_paragraph()
    _set_rtl(title_p, rtl)
    _set_font(title_p.add_run(title), font, 22, bold=True)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for chunk in chunks:
        text = chunk.get("translated_text") or ""
        untranslated = not text.strip()
        if untranslated:
            text = f"[untranslated] {chunk.get('raw_text', '')}"
        level = _heading_level(chunk.get("format_map") or [])
        is_heading = level is not None or chunk.get("content_type") == "heading"
        bold_line = bool((chunk.get("format_map") or [{}])[0].get("bold"))

        if is_heading:
            p = doc.add_heading(level=level or 1)
            _set_rtl(p, rtl)
            _set_font(p.add_run(text.strip()), font, 18 - 2 * ((level or 1) - 1), bold=True)
            continue

        for para in [t for t in text.split("\n\n") if t.strip()]:
            p = doc.add_paragraph()
            _set_rtl(p, rtl)
            if chunk.get("content_type") in ("quranic_verse", "hadith", "poetry"):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_font(p.add_run(para.strip()), font, 13, bold=bold_line)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
