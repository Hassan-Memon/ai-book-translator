"""Format and structure detection for extracted PDF content."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FormatMetadata:
    """Format metadata for a single line."""

    line_id: str
    text: str
    type: str  # heading_1, heading_2, bold, italic, prose, poetry, verse, hadith, footnote
    font_size: float | None
    bold: bool
    italic: bool
    alignment: str  # left, center, right, justify
    rtl: bool
    page: int
    content_class: str  # chapter_heading, section_heading, prose, poetry, verse, hadith, footnote


class FormatMapper:
    """Detect structure and formatting from PDF blocks."""

    def __init__(self, config: Any):
        self.config = config
        self.rtl_languages = {"ar", "ur", "he"}

    def map_format(self, blocks: list[dict[str, Any]], page_num: int,
                   source_language: str) -> list[FormatMetadata]:
        """Map format metadata for all blocks on a page."""
        metadata = []

        for line_index, block in enumerate(blocks):
            if block["type"] != "text":
                continue

            meta = self._analyze_block(
                block,
                line_index,
                page_num,
                source_language,
            )
            metadata.append(meta)

        return metadata

    def _analyze_block(self, block: dict[str, Any], line_index: int, page_num: int,
                      source_language: str) -> FormatMetadata:
        """Analyze a single text block."""
        text = block.get("text", "").strip()
        font_size = block.get("font_size", 12)
        font_name = block.get("font_name", "").lower()
        is_rtl = source_language in self.rtl_languages or self._has_rtl_text(text)

        # Detect formatting
        flags = int(block.get("flags", 0) or 0)
        bold = (
            self._is_bold_from_font(font_name)
            or self._is_bold_from_flags(flags)
            or self._is_bold_from_text(text)
        )
        italic = self._is_italic_from_font(font_name) or self._is_italic_from_flags(flags)

        # Detect heading level
        heading_level = self._detect_heading_level(text, font_size, bold)

        # Detect content type
        content_type = self._detect_content_type(text, heading_level)

        # Detect alignment (approximate from bbox if available)
        alignment = self._detect_alignment(block.get("bbox"), is_rtl, block.get("page_width"))

        # Generate line ID
        line_id = f"page{page_num}_line{line_index}"

        # Determine format type
        if heading_level == 1:
            format_type = "heading_1"
        elif heading_level == 2:
            format_type = "heading_2"
        elif heading_level == 3:
            format_type = "heading_3"
        elif bold:
            format_type = "bold"
        elif italic:
            format_type = "italic"
        else:
            format_type = "text"

        return FormatMetadata(
            line_id=line_id,
            text=text,
            type=format_type,
            font_size=font_size,
            bold=bold,
            italic=italic,
            alignment=alignment,
            rtl=is_rtl,
            page=page_num,
            content_class=content_type,
        )

    def _is_bold_from_font(self, font_name: str) -> bool:
        """Check if font name indicates bold."""
        return any(token in font_name for token in ("bold", "black", "semibold", "demi"))

    def _is_bold_from_flags(self, flags: int) -> bool:
        """Check PyMuPDF font flags for bold text."""
        return bool(flags & 16)

    def _is_bold_from_text(self, text: str) -> bool:
        """Heuristic: all-caps or repetitive emphasis might indicate bold."""
        # Simple heuristic: if text is all uppercase AND longer than 3 chars, assume bold
        # (This is imperfect but helps catch some headings)
        return len(text) > 3 and text.isupper()

    def _is_italic_from_font(self, font_name: str) -> bool:
        """Check if font name indicates italic."""
        return "italic" in font_name or "oblique" in font_name

    def _is_italic_from_flags(self, flags: int) -> bool:
        """Check PyMuPDF font flags for italic text."""
        return bool(flags & 2)

    def _has_rtl_text(self, text: str) -> bool:
        """Detect Arabic-family right-to-left scripts directly from text."""
        return bool(re.search(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]", text))

    def _detect_heading_level(self, text: str, font_size: float | None,
                             bold: bool) -> int:
        """Detect heading level from font size and formatting."""
        if font_size is None:
            return 0

        # Heading heuristics
        if font_size >= 24 and bold:
            return 1
        elif font_size >= 18 and bold:
            return 2
        elif font_size >= 14 and bold:
            return 3

        # Check for common heading patterns
        if re.match(r"^(Chapter|الفصل|فصل|باب|سورة|کتاب)", text, re.IGNORECASE):
            return 1
        elif re.match(r"^(Section|المقطع|الجزء|مبحث|تنبیہ|تمہید)", text, re.IGNORECASE):
            return 2

        return 0

    def _detect_content_type(self, text: str, heading_level: int) -> str:
        """Detect content type: prose, poetry, verse, hadith, footnote, etc."""
        text_lower = text.lower()

        # Headings
        if heading_level > 0:
            return "heading"

        # Footnote indicators (typically start with * or number)
        if re.match(r"^[\*\†\‡]|^\(?\d+[\).\u06d4]", text):
            return "footnote"

        # Quranic verse markers
        if re.search(r"[\u06dd۝]|\d+\s*:\s*\d+|﴿.*﴾", text):
            return "quranic_verse"

        # Hadith indicators
        if any(keyword in text_lower for keyword in ["hadith", "حديث", "روى", "رواه"]):
            return "hadith"

        if re.match(r"^\(?[\d\u06f0-\u06f9\u0660-\u0669]+[\).\u06d4]", text):
            return "numbered_list"

        # Poetry detection (lines starting with specific characters or patterns)
        if text.startswith(("-", "—", "˖")) or re.search(r"\s{4,}", text):
            return "poetry"

        # Default to prose
        return "prose"

    def _detect_alignment(self, bbox: tuple[float, float, float, float] | None,
                         is_rtl: bool, page_width: float | None = None) -> str:
        """Detect text alignment from bounding box."""
        if bbox is None:
            return "left" if not is_rtl else "right"

        x0, _, x1, _ = bbox
        page_width = page_width or 595  # Standard letter width in points
        width = x1 - x0

        center_threshold = page_width * 0.08
        center_x = page_width / 2

        if abs((x0 + x1) / 2 - center_x) < center_threshold:
            return "center"
        elif width > (page_width * 0.8):
            return "justify"
        elif x0 < (page_width * 0.2):
            return "left"
        elif x1 > (page_width * 0.8):
            return "right"

        return "right" if is_rtl else "left"

    def to_dict(self, meta: FormatMetadata) -> dict[str, Any]:
        """Convert FormatMetadata to dictionary."""
        return {
            "line_id": meta.line_id,
            "text": meta.text,
            "type": meta.type,
            "font_size": meta.font_size,
            "bold": meta.bold,
            "italic": meta.italic,
            "alignment": meta.alignment,
            "rtl": meta.rtl,
            "page": meta.page,
            "content_class": meta.content_class,
        }
