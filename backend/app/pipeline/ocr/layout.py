"""Turn OCR words into lines in reading order.

Engines give us words with boxes (and, for Tesseract, a confidence per word).
This module rebuilds lines, finds columns, orders them in the script's
direction, and tags margin furniture (page numbers, running heads) so the
chunker can skip it. It is deterministic and needs no model, which is the
whole point: the expensive part of reading a scanned page is layout, not
character recognition, and layout is geometry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points


@dataclass
class OcrWord:
    text: str
    bbox: BBox
    conf: float | None = None  # 0..100, None when the engine has no score
    block: int = 0
    para: int = 0
    line: int = 0


@dataclass
class OcrLine:
    words: list[OcrWord] = field(default_factory=list)
    kind: str = "text"  # text | page_number | running_head
    column: int = 0

    @property
    def bbox(self) -> BBox:
        xs0 = [w.bbox[0] for w in self.words]
        ys0 = [w.bbox[1] for w in self.words]
        xs1 = [w.bbox[2] for w in self.words]
        ys1 = [w.bbox[3] for w in self.words]
        return (min(xs0), min(ys0), max(xs1), max(ys1))

    @property
    def conf(self) -> float | None:
        scored = [w.conf for w in self.words if w.conf is not None and w.conf >= 0]
        return sum(scored) / len(scored) if scored else None

    def text(self, rtl: bool) -> str:
        words = sorted(self.words, key=lambda w: w.bbox[0], reverse=rtl)
        return " ".join(w.text for w in words if w.text)


_NUMERIC_LINE = re.compile(r"^[\s\d٠-٩۰-۹\-–—.()\[\]|]+$")


def group_lines(words: list[OcrWord]) -> list[OcrLine]:
    """Group words that share an engine line id; fall back to geometry when
    the engine gave none (every word on line 0)."""
    if not words:
        return []
    keyed: dict[tuple[int, int, int], OcrLine] = {}
    for w in words:
        key = (w.block, w.para, w.line)
        keyed.setdefault(key, OcrLine()).words.append(w)
    lines = list(keyed.values())
    if len(lines) == 1 and len(words) > 8:
        lines = _group_by_geometry(words)
    split: list[OcrLine] = []
    for ln in lines:
        split.extend(split_wide_gaps(ln))
    return [ln for ln in split if any(w.text.strip() for w in ln.words)]


def split_wide_gaps(line: OcrLine, factor: float = 4.0) -> list[OcrLine]:
    """Engines sometimes stitch the two columns of a page (or the two pages
    of a scanned spread) into one line. A horizontal gap wider than ``factor``
    times the line's median word height is a column boundary; split there."""
    if len(line.words) < 2:
        return [line]
    words = sorted(line.words, key=lambda w: w.bbox[0])
    heights = sorted(max(1.0, w.bbox[3] - w.bbox[1]) for w in words)
    unit = heights[len(heights) // 2]
    parts: list[list[OcrWord]] = [[words[0]]]
    for prev, cur in zip(words, words[1:], strict=False):
        gap = cur.bbox[0] - prev.bbox[2]
        if gap > factor * unit:
            parts.append([cur])
        else:
            parts[-1].append(cur)
    if len(parts) == 1:
        return [line]
    return [OcrLine(words=p, kind=line.kind, column=line.column) for p in parts]


def _group_by_geometry(words: list[OcrWord]) -> list[OcrLine]:
    """Cluster words into lines by vertical overlap."""
    ordered = sorted(words, key=lambda w: (w.bbox[1] + w.bbox[3]) / 2)
    lines: list[OcrLine] = []
    for w in ordered:
        cy = (w.bbox[1] + w.bbox[3]) / 2
        h = max(1.0, w.bbox[3] - w.bbox[1])
        placed = False
        for ln in lines:
            bx = ln.bbox
            lcy = (bx[1] + bx[3]) / 2
            if abs(cy - lcy) < 0.6 * h:
                ln.words.append(w)
                placed = True
                break
        if not placed:
            lines.append(OcrLine(words=[w]))
    return lines


def detect_columns(lines: list[OcrLine], page_width: float) -> list[tuple[float, float]]:
    """Return column x-ranges, left to right. One range means single column.

    A column gap is a vertical band at least 4% of the page wide that no
    non-spanning line crosses. Lines wider than 65% of the page are treated as
    spanning (headings, full-width paragraphs) and ignored for gap finding.
    """
    if not lines or page_width <= 0:
        return [(0.0, page_width)]
    narrow = [ln for ln in lines if (ln.bbox[2] - ln.bbox[0]) < 0.65 * page_width]
    if len(narrow) < max(6, len(lines) // 3):
        return [(0.0, page_width)]
    buckets = 200
    occupancy = [0] * buckets
    for ln in narrow:
        x0, _, x1, _ = ln.bbox
        a = max(0, min(buckets - 1, int(x0 / page_width * buckets)))
        b = max(0, min(buckets - 1, int(x1 / page_width * buckets)))
        for i in range(a, b + 1):
            occupancy[i] += 1
    # Find empty bands inside the text area (ignore outer margins).
    first = next((i for i, v in enumerate(occupancy) if v), None)
    last = next((i for i in range(buckets - 1, -1, -1) if occupancy[i]), None)
    if first is None or last is None:
        return [(0.0, page_width)]
    min_gap = max(4, int(0.04 * buckets))
    gaps: list[tuple[int, int]] = []
    i = first
    while i <= last:
        if occupancy[i] == 0:
            j = i
            while j <= last and occupancy[j] == 0:
                j += 1
            if j - i >= min_gap:
                gaps.append((i, j))
            i = j
        else:
            i += 1
    if not gaps:
        return [(0.0, page_width)]
    bounds = [0.0]
    for a, b in gaps:
        bounds.append(((a + b) / 2) / buckets * page_width)
    bounds.append(page_width)
    return [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)]


def tag_margins(lines: list[OcrLine], page_width: float, page_height: float) -> None:
    """Mark page numbers and running heads in the top/bottom 10% of the page."""
    if page_height <= 0:
        return
    top_band = 0.10 * page_height
    bottom_band = 0.90 * page_height
    for ln in lines:
        x0, y0, x1, y1 = ln.bbox
        in_margin = y1 < top_band or y0 > bottom_band
        if not in_margin:
            continue
        text = ln.text(rtl=False).strip()
        if _NUMERIC_LINE.match(text or "-"):
            ln.kind = "page_number"
        elif (x1 - x0) < 0.6 * page_width and len(text) <= 60:
            ln.kind = "running_head"


def order_lines(lines: list[OcrLine], page_width: float, rtl: bool) -> list[OcrLine]:
    """Reading order: spanning lines split the page into bands; inside a band
    columns are read right-to-left for RTL scripts, else left-to-right, each
    top-to-bottom."""
    if not lines:
        return []
    columns = detect_columns(lines, page_width)
    ncols = len(columns)

    def column_of(ln: OcrLine) -> int:
        x0, _, x1, _ = ln.bbox
        if ncols == 1:
            return 0
        if (x1 - x0) >= 0.65 * page_width:
            return -1  # spanning
        cx = (x0 + x1) / 2
        for idx, (a, b) in enumerate(columns):
            if a <= cx <= b:
                return idx
        return 0

    for ln in lines:
        ln.column = column_of(ln)

    by_y = sorted(lines, key=lambda ln: ln.bbox[1])
    if ncols == 1:
        return by_y

    col_order = list(range(ncols))
    if rtl:
        col_order.reverse()

    out: list[OcrLine] = []
    band: list[OcrLine] = []

    def flush() -> None:
        for c in col_order:
            out.extend(sorted((ln for ln in band if ln.column == c), key=lambda ln: ln.bbox[1]))
        band.clear()

    for ln in by_y:
        if ln.column == -1:
            flush()
            out.append(ln)
        else:
            band.append(ln)
    flush()
    return out


def dehyphenate(lines: list[str]) -> list[str]:
    """Join Latin-script words broken across lines with a trailing hyphen."""
    out: list[str] = []
    carry = ""
    for raw in lines:
        text = carry + raw if carry else raw
        carry = ""
        m = re.search(r"([A-Za-zÀ-ɏ]{2,})-$", text)
        if m:
            carry = m.group(1)
            text = text[: m.start(1)].rstrip()
            if not text:
                continue
        out.append(text)
    if carry:
        out.append(carry)
    return out
