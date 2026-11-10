"""Score an OCR result without a reference text.

Four cheap signals, combined into one 0..1 number that drives escalation and
is shown to the reviewer next to each page:

* **confidence**: mean Tesseract word confidence (when the engine has one)
  and the share of words the engine itself was unsure about;
* **script validity**: share of letters that belong to the book's script(s);
  a page of Arabic that comes back as Latin mojibake scores near 0;
* **garbage**: tokens with no letters, "words" too long for the script (lost
  spaces: a classic Tesseract failure on Arabic), stray Latin tokens inside a
  non-Latin book, lines of isolated letters;
* **shape**: mean letters per word far outside what the script produces.

Engines without confidences are capped below engines with them: a page we
cannot verify should never look better than one we can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.languages import get_language, script_of_char, script_ratio

_LETTERS = re.compile(r"\w", re.UNICODE)
_DIGITS = re.compile(r"^[\d٠-٩۰-۹.,:/()\[\]-]+$")

# Longest plausible word (letters) per script before we assume lost spaces.
_MAX_WORD = {"Arabic": 12, "Hebrew": 12, "Latin": 24, "Cyrillic": 24, "Devanagari": 18}
# Typical mean letters per word; far outside this band is a bad read.
_MEAN_BAND = {"Arabic": (2.5, 7.5), "Latin": (2.5, 9.0), "Cyrillic": (3.0, 10.0)}

LOW_CONF = 45.0
NO_CONFIDENCE_CAP = 0.82


@dataclass
class QualityReport:
    score: float  # 0..1
    mean_conf: float | None  # 0..100
    low_conf_ratio: float | None  # share of words below LOW_CONF
    script_validity: float  # 0..1
    garbage_ratio: float  # 0..1
    words: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "score": round(self.score, 3),
            "mean_conf": None if self.mean_conf is None else round(self.mean_conf, 1),
            "low_conf_ratio": None
            if self.low_conf_ratio is None
            else round(self.low_conf_ratio, 3),
            "script_validity": round(self.script_validity, 3),
            "garbage_ratio": round(self.garbage_ratio, 3),
            "words": self.words,
        }


def _token_garbage(word: str, script: str, spaced: bool) -> float:
    """0 = fine, 1 = garbage, 0.5 = suspicious."""
    w = word.strip()
    if not w:
        return 0.0
    if _DIGITS.match(w):
        return 0.0
    letters = [ch for ch in w if ch.isalpha()]
    if not letters:
        return 1.0 if len(w) >= 3 else 0.0
    if spaced and len(letters) > _MAX_WORD.get(script, 24):
        return 1.0
    own = [ch for ch in letters if script_of_char(ch) == script]
    if script != "Latin":
        latin = sum(1 for ch in letters if script_of_char(ch) == "Latin")
        if latin == len(letters):
            # A Latin token in a non-Latin book: a citation ("Beirut") is fine,
            # random caps ("BU", "LLL", "ete") are OCR noise. Suspicious.
            return 0.5 if len(letters) >= 4 and w[1:].islower() else 1.0
        if own and latin and latin < len(letters):
            return 1.0  # scripts glued together inside one token
    if own and len(own) < len(letters) / 2:
        return 1.0
    return 0.0


def assess(
    text: str,
    *,
    languages: list[str],
    word_confs: list[float] | None = None,
) -> QualityReport:
    """Score recognised text for the given candidate languages (book source
    language first; digits and Latin are always tolerated as mixed content)."""
    words = [w for w in re.split(r"\s+", text) if w.strip()]
    n = len(words)
    if n == 0:
        return QualityReport(0.0, None, None, 0.0, 1.0, 0)

    primary = languages[0] if languages else "en"
    lang = get_language(primary)
    script = lang.script if lang else "Latin"
    spaced = lang.spaced if lang else True

    validity = max(script_ratio(text, code) for code in languages) if languages else 1.0
    if script != "Latin":
        # Latin fragments (citations, numbers, roman numerals) are normal in any book.
        validity = min(1.0, validity + 0.5 * script_ratio(text, "en"))

    garbage = sum(_token_garbage(w, script, spaced) for w in words) / n

    if spaced:
        letter_counts = [sum(1 for ch in w if ch.isalpha()) for w in words]
        letter_counts = [c for c in letter_counts if c]
        if letter_counts:
            mean_len = sum(letter_counts) / len(letter_counts)
            lo, hi = _MEAN_BAND.get(script, (2.0, 12.0))
            if mean_len > hi:
                garbage = min(1.0, garbage + (mean_len - hi) / hi)
            elif mean_len < lo:
                garbage = min(1.0, garbage + (lo - mean_len) / lo)

    conf: float | None = None
    low_ratio: float | None = None
    if word_confs:
        usable = [c for c in word_confs if c is not None and c >= 0]
        if usable:
            conf = sum(usable) / len(usable)
            low_ratio = sum(1 for c in usable if c < LOW_CONF) / len(usable)

    if conf is not None and low_ratio is not None:
        bad = max(garbage, low_ratio)
        score = 0.45 * (conf / 100.0) + 0.25 * validity + 0.30 * (1.0 - bad)
    else:
        score = min(NO_CONFIDENCE_CAP, 0.55 * validity + 0.45 * (1.0 - garbage))
    # Very short pages (a title page, a blank with a page number) are not
    # evidence of a bad engine; soften the penalty so they do not escalate.
    if n < 12:
        score = max(score, 0.5)
    return QualityReport(
        score=max(0.0, min(1.0, score)),
        mean_conf=conf,
        low_conf_ratio=low_ratio,
        script_validity=validity,
        garbage_ratio=min(1.0, garbage),
        words=n,
    )
