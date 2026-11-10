"""Script-aware sentence segmentation and numbered alignment.

Used by the sentence-aligned translation mode: the source chunk is split into
sentences, each prefixed with ``[n]``; the model must return the same ``[n]``
markers. ``parse_numbered`` then checks every number came back exactly once,
which turns "did the model skip a sentence?" from a judgement call into a
set comparison.
"""

from __future__ import annotations

import re

from app.core.languages import terminators_for

# Abbreviations and markers that end with a terminator but not a sentence.
_NO_BREAK_AFTER = re.compile(
    r"(?:\b[A-Z]\.|\b(?:Dr|Mr|Mrs|Ms|Prof|St|vs|etc|e\.g|i\.e|No|p|pp|ed|vol|cf|ch|fig)\.)$",
    re.IGNORECASE,
)
_DIGIT_DOT = re.compile(r"\d\.$")
_MARKER = re.compile(r"^\s*\[(\d{1,3})\]\s*")
_MARKER_ANY = re.compile(r"\[(\d{1,3})\]")


def split_sentences(text: str, language: str, max_len: int = 400) -> list[str]:
    """Split into sentences on the language's terminators, keeping the
    terminator. Paragraph breaks always split. Very long runs without any
    terminator are split on clause punctuation so one "sentence" never
    exceeds ``max_len`` characters."""
    terms = set(terminators_for(language))
    closers = {'"', "”", "»", "’", "'", ")", "]", "﴾", "﴿"}
    sentences: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        buf: list[str] = []
        i = 0
        n = len(para)
        while i < n:
            ch = para[i]
            buf.append(ch)
            if ch in terms:
                # swallow runs like "?!" or "..." and closing quotes
                j = i + 1
                while j < n and (para[j] in terms or para[j] in closers):
                    buf.append(para[j])
                    j += 1
                candidate = "".join(buf).strip()
                if ch == "." and j < n:
                    nxt = para[j:].lstrip()[:1]
                    # "Dr. Smith", "vol. 2": abbreviations never end a sentence.
                    # "2. It": a number before the dot ends one only when the
                    # next word starts with a capital letter.
                    if _NO_BREAK_AFTER.search(candidate) or (
                        _DIGIT_DOT.search(candidate) and not nxt.isupper()
                    ):
                        i = j
                        continue
                if candidate:
                    sentences.append(candidate)
                buf = []
                i = j
                continue
            i += 1
        rest = "".join(buf).strip()
        if rest:
            sentences.append(rest)
    # Secondary split for overlong sentences (lists, poetry, OCR without stops).
    out: list[str] = []
    for s in sentences:
        if len(s) <= max_len:
            out.append(s)
            continue
        parts = re.split(r"(?<=[،,;؛:])\s+", s)
        buf2 = ""
        for p in parts:
            if buf2 and len(buf2) + len(p) + 1 > max_len:
                out.append(buf2.strip())
                buf2 = p
            else:
                buf2 = f"{buf2} {p}".strip()
        if buf2:
            out.append(buf2.strip())
    return out


def number_sentences(sentences: list[str]) -> str:
    return "\n".join(f"[{i + 1}] {s}" for i, s in enumerate(sentences))


def parse_numbered(text: str, expected: int) -> tuple[dict[int, str], list[str]]:
    """Parse ``[n] ...`` lines. Returns ``(by_number, problems)``.

    Tolerates markers not at line start (small models sometimes run two
    sentences together) by splitting on every marker occurrence.
    """
    problems: list[str] = []
    by_number: dict[int, str] = {}
    positions = [(m.start(), m.end(), int(m.group(1))) for m in _MARKER_ANY.finditer(text)]
    if not positions:
        return {}, ["no [n] markers found in the output"]
    for idx, (start, end, num) in enumerate(positions):
        stop = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        segment = text[end:stop].strip()
        if num in by_number:
            problems.append(f"sentence [{num}] appears more than once")
            by_number[num] = f"{by_number[num]} {segment}".strip()
        else:
            by_number[num] = segment
        if start > 0 and idx == 0 and text[:start].strip():
            problems.append("text before the first marker was dropped")
    missing = [n for n in range(1, expected + 1) if n not in by_number]
    extra = [n for n in by_number if n < 1 or n > expected]
    if missing:
        problems.append(f"missing sentence(s): {missing}")
    if extra:
        problems.append(f"unexpected marker(s): {extra}")
    empty = [n for n, s in by_number.items() if not s]
    if empty:
        problems.append(f"empty translation for sentence(s): {empty}")
    return by_number, problems


def join_numbered(by_number: dict[int, str], expected: int, source_sentences: list[str]) -> str:
    """Assemble the translation in order; a sentence the model dropped is
    filled with its source so nothing silently disappears (the gate flags it)."""
    parts: list[str] = []
    for n in range(1, expected + 1):
        parts.append(by_number.get(n) or source_sentences[n - 1])
    return " ".join(p.strip() for p in parts if p.strip())


def strip_markers(text: str) -> str:
    return _MARKER_ANY.sub("", text).strip()
