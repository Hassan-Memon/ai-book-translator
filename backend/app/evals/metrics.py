"""Deterministic, reference-based metrics. No dependencies, no model calls.

* :func:`chrf_pp` — chrF++ (Popović 2017): character n-grams 1–6 plus word
  n-grams 1–2, recall weighted (β = 2), 0–100. Character n-grams make it
  fair to morphologically rich languages (Arabic, Urdu, Hindi) where BLEU's
  whole-word matching under-scores correct translations. It follows
  ``sacrebleu.CHRF(word_order=2)`` exactly (same tokenisation and averaging;
  checked to two decimals on English, Arabic, Urdu and Hindi pairs, and
  ``tests/test_evals.py`` pins those values), so scores are comparable with
  published chrF++ numbers without adding the dependency.
* :func:`term_adherence` — decided glossary terms rendered as decided.
* :func:`structure_report` — paragraphs, list items, footnote markers, verse
  brackets and single-line headings survive.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections import Counter
from typing import Any

from app.core.languages import normalize_text

CHAR_ORDER = 6
WORD_ORDER = 2
BETA = 2.0

_PUNCTS = frozenset(string.punctuation)


def _words(text: str) -> list[str]:
    """Whitespace tokens with one leading or trailing ASCII punctuation mark
    split off, exactly as sacrebleu's chrF++ does, so scores are comparable
    with published numbers."""
    out: list[str] = []
    for tok in text.split():
        if len(tok) == 1:
            out.append(tok)
        elif tok[-1] in _PUNCTS:
            out.extend((tok[:-1], tok[-1]))
        elif tok[0] in _PUNCTS:
            out.extend((tok[1:], tok[0]))
        else:
            out.append(tok)
    return out


def _ngrams(seq: list[str] | str, n: int) -> Counter[Any]:
    if isinstance(seq, str):
        return Counter(seq[i : i + n] for i in range(len(seq) - n + 1))
    return Counter(tuple(seq[i : i + n]) for i in range(len(seq) - n + 1))


def _stats(hyp: str, ref: str) -> list[tuple[int, int, int]]:
    """(matches, hyp_total, ref_total) per order: chars 1..6 then words 1..2."""
    h_chars, r_chars = re.sub(r"\s+", "", hyp), re.sub(r"\s+", "", ref)
    h_words, r_words = _words(hyp), _words(ref)
    stats: list[tuple[int, int, int]] = []
    for n in range(1, CHAR_ORDER + 1):
        h, r = _ngrams(h_chars, n), _ngrams(r_chars, n)
        stats.append((sum((h & r).values()), sum(h.values()), sum(r.values())))
    for n in range(1, WORD_ORDER + 1):
        h, r = _ngrams(h_words, n), _ngrams(r_words, n)
        stats.append((sum((h & r).values()), sum(h.values()), sum(r.values())))
    return stats


def _chrf_single(hyp: str, ref: str) -> float:
    # sacrebleu CHRF(word_order=2) without eps smoothing: precision and recall
    # are summed over all orders and divided by the number of orders where
    # both sides have n-grams, then combined into one F-beta.
    eps = 1e-16
    sum_p = sum_r = 0.0
    effective = 0
    for match, h_total, r_total in _stats(hyp, ref):
        sum_p += match / h_total if h_total else eps
        sum_r += match / r_total if r_total else eps
        effective += 1 if h_total and r_total else 0
    if effective == 0:
        return 0.0
    p, r = sum_p / effective, sum_r / effective
    if p + r == 0:
        return 0.0
    b2 = BETA * BETA
    return 100.0 * (1 + b2) * p * r / (b2 * p + r)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", normalize_text(text or "")).strip()


def chrf_pp(hypothesis: str, references: list[str] | str) -> float:
    """chrF++ against the best of one or more references, 0–100."""
    refs = [references] if isinstance(references, str) else list(references)
    hyp = _norm(hypothesis)
    if not hyp:
        return 0.0
    return round(max(_chrf_single(hyp, _norm(r)) for r in refs if r is not None), 2)


def term_adherence(hypothesis: str, source: str, terms: list[dict[str, Any]]) -> dict[str, Any]:
    """For every ``must_match`` term present in the source (or a variant), is
    its decided target present in the hypothesis?"""
    hyp, src = _norm(hypothesis), _norm(source)
    expected: list[str] = []
    missing: list[str] = []
    for term in terms:
        if not term.get("must_match", True):
            continue
        forms = [term["source"], *term.get("variants", [])]
        if not any(_norm(f) in src for f in forms):
            continue
        expected.append(term["source"])
        if _norm(term["target"]) not in hyp:
            missing.append(term["source"])
    rate = None if not expected else round(1 - len(missing) / len(expected), 3)
    return {
        "expected": len(expected),
        "matched": len(expected) - len(missing),
        "missing": missing,
        "adherence": rate,
    }


_LIST_ITEM = re.compile(r"^\s*(?:\(?[0-9٠-٩۰-۹०-९]+[.)\-–:]|[-•*]|[a-zA-Zء-ي][.)])\s+", re.M)
_FOOTNOTE = re.compile(r"\(\s*[0-9٠-٩۰-۹०-९]+\s*\)|\[\s*[0-9٠-٩۰-۹०-९]+\s*\]")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹०१२३४५६७८९", "0123456789" * 3)


def _paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()])


def structure_report(
    hypothesis: str, source: str, content_type: str, expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Structural checks that apply to this item. ``preserved`` = all passed."""
    expected = expected or {}
    hyp, src = hypothesis.strip(), source.strip()
    checks: dict[str, bool] = {}
    if hyp:
        checks["paragraphs"] = _paragraphs(hyp) == _paragraphs(src)
    else:
        checks["non_empty"] = False
    if content_type == "heading" or "heading_level" in expected:
        checks["single_line_heading"] = (
            bool(hyp) and "\n" not in hyp and len(hyp) <= 3 * len(src) + 20
        )
    n_items = expected.get("list_items")
    if n_items is None and content_type == "numbered_list":
        n_items = len(_LIST_ITEM.findall(src))
    if n_items:
        checks["list_items"] = len(_LIST_ITEM.findall(hyp)) == int(n_items)
    markers = expected.get("footnote_markers")
    if markers is None:
        markers = [m.translate(_DIGITS).replace(" ", "") for m in _FOOTNOTE.findall(src)]
    if markers:
        found = {m.translate(_DIGITS).replace(" ", "") for m in _FOOTNOTE.findall(hyp)}
        checks["footnote_markers"] = all(m.translate(_DIGITS) in found for m in markers)
    if expected.get("verse_brackets") or ("﴿" in src and "﴾" in src):
        checks["verse_brackets"] = "﴿" in hyp and "﴾" in hyp
    return {"checks": checks, "preserved": all(checks.values()) if checks else True}


def length_ratio(hypothesis: str, source: str) -> float:
    return round(len(_norm(hypothesis)) / max(1, len(_norm(source))), 3)
