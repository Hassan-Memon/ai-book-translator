"""Semantic chunking that respects paragraph and section boundaries."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.models.base import ContentType

logger = logging.getLogger(__name__)


@dataclass
class SemanticChunk:
    """Represents one semantic unit of a book."""

    index: int
    raw_text: str
    format_map: list[dict[str, Any]]
    content_type: ContentType
    page_start: int
    page_end: int


class SemanticChunker:
    """Intelligently chunk document text respecting boundaries."""

    def __init__(self, config: Any):
        self.config = config
        self.target_chars = config.chunk_target_chars
        self.min_chunk_chars = self.target_chars * 0.5
        self.max_chunk_chars = self.target_chars * 2.0

    def chunk_document(
        self,
        pages: list[dict[str, Any]],
        format_metadata: list[list[Any]],
    ) -> list[SemanticChunk]:
        """Convert extracted pages into semantic chunks."""
        # Combine all text and metadata
        all_lines = []

        for page_idx, page in enumerate(pages):
            page_line_index = 0
            for line in page.get("blocks", []):
                if line["type"] == "text":
                    all_lines.append({
                        "text": line["text"],
                        "page": page_idx,
                        "metadata": self._get_metadata_for_line(
                            page_idx, page_line_index, format_metadata
                        ),
                    })
                    page_line_index += 1

        # Chunk by semantic boundaries
        chunks = self._create_chunks(all_lines)
        return chunks

    def _get_metadata_for_line(
        self, page_idx: int, line_idx: int, format_metadata: list[list[Any]]
    ) -> dict[str, Any]:
        """Get format metadata for a specific line."""
        if page_idx < len(format_metadata) and line_idx < len(format_metadata[page_idx]):
            meta = format_metadata[page_idx][line_idx]
            return meta
        return {}

    def _create_chunks(self, lines: list[dict[str, Any]]) -> list[SemanticChunk]:
        """Create chunks respecting paragraph and section boundaries."""
        chunks = []
        current_chunk_lines = []
        current_chunk_text = ""
        current_page_start = 0
        current_index = 0

        for line in lines:
            text = line["text"]
            page = line["page"]
            metadata = line["metadata"]

            if not current_chunk_text:
                current_page_start = page

            # Check if this line is a heading or boundary indicator
            is_heading = metadata.get("type", "").startswith("heading_")
            is_paragraph_break = self._is_paragraph_break(current_chunk_text, text)
            is_section_break = self._is_section_break(text)

            # Calculate if adding this line would exceed target
            separator = "\n\n" if is_paragraph_break else "\n"
            tentative_text = current_chunk_text + separator + text
            tentative_length = len(tentative_text)

            # Finalize chunk if:
            # 1. We've hit max size
            # 2. We encounter a heading after minimum size
            # 3. We encounter a section break
            # 4. We hit a paragraph boundary after target size
            should_finalize = (
                (tentative_length > self.max_chunk_chars)
                or (is_heading and len(current_chunk_text) > self.min_chunk_chars)
                or (is_section_break and len(current_chunk_text) > self.min_chunk_chars)
                or (is_paragraph_break and len(current_chunk_text) >= self.target_chars)
            )

            if should_finalize and current_chunk_text.strip():
                # Save current chunk
                chunk = self._finalize_chunk(
                    current_index,
                    current_chunk_lines,
                    current_chunk_text,
                    current_page_start,
                    page,
                )
                chunks.append(chunk)

                current_chunk_lines = []
                current_chunk_text = ""
                current_index += 1

            # Add line to current chunk
            current_chunk_lines.append(line)
            current_chunk_text = tentative_text.lstrip("\n")

        # Finalize last chunk
        if current_chunk_text.strip():
            chunk = self._finalize_chunk(
                current_index,
                current_chunk_lines,
                current_chunk_text,
                current_page_start,
                lines[-1]["page"] if lines else 0,
            )
            chunks.append(chunk)

        return chunks

    def _is_paragraph_break(self, current_text: str, next_text: str) -> bool:
        """Detect likely paragraph boundaries between two adjacent lines."""
        if not current_text:
            return False

        previous = current_text.rstrip()
        next_text = next_text.strip()
        if not previous or not next_text:
            return False

        sentence_endings = (".", "?", "!", "۔", "؟", "؛", ":", "»", "”")
        starts_new_item = bool(
            re.match(r"^\(?[\d\u06f0-\u06f9\u0660-\u0669]+[\).\u06d4]", next_text)
        )
        return previous.endswith(sentence_endings) or starts_new_item

    def _is_section_break(self, text: str) -> bool:
        """Detect section breaks or structural boundaries."""
        text = text.strip()

        # Empty lines or minimal content
        if len(text) < 3:
            return False

        # Common section indicators
        section_patterns = [
            r"^(Chapter|Chapitre|الفصل|فصل|باب|سورة|کتاب)",
            r"^(Section|المقطع|الجزء|مبحث|تنبیہ|تمہید)",
            r"^---+$",  # Horizontal lines
            r"^===+$",
        ]

        for pattern in section_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True

        return False

    def _finalize_chunk(
        self,
        index: int,
        lines: list[dict[str, Any]],
        text: str,
        page_start: int,
        page_end: int,
    ) -> SemanticChunk:
        """Finalize a chunk with metadata."""
        # Determine dominant content type
        content_type = self._infer_content_type(lines)

        # Build format map from all lines in chunk
        format_map = [line["metadata"] for line in lines]

        return SemanticChunk(
            index=index,
            raw_text=text.strip(),
            format_map=format_map,
            content_type=content_type,
            page_start=page_start,
            page_end=page_end,
        )

    def _infer_content_type(self, lines: list[dict[str, Any]]) -> ContentType:
        """Infer content type from lines in chunk."""
        # Count content types
        type_counts = {}
        for line in lines:
            content_class = line.get("metadata", {}).get("content_class", "prose")
            type_counts[content_class] = type_counts.get(content_class, 0) + 1

        # Dominant type
        if type_counts:
            dominant = max(type_counts, key=type_counts.get)
            try:
                return ContentType(dominant)
            except ValueError:
                if dominant in {"chapter_heading", "section_heading", "heading_1", "heading_2"}:
                    return ContentType.heading
                if dominant == "verse":
                    return ContentType.quranic_verse
                return ContentType.prose

        return ContentType.prose

    def create_chunk_neighbors(
        self, chunks: list[SemanticChunk]
    ) -> dict[int, dict[str, str]]:
        """Create neighbor context for each chunk (n-2..n+2)."""
        neighbors = {}

        for i, _chunk in enumerate(chunks):
            neighbors[i] = {
                "n_minus_2": chunks[i - 2].raw_text if i >= 2 else "",
                "n_minus_1": chunks[i - 1].raw_text if i >= 1 else "",
                "n_plus_1": chunks[i + 1].raw_text if i < len(chunks) - 1 else "",
                "n_plus_2": chunks[i + 2].raw_text if i < len(chunks) - 2 else "",
            }

        return neighbors
