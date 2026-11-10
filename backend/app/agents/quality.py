"""Deterministic quality gate for a translation: catches, in microseconds and
for free, the failures small models make most often, so the LLM reviewer is
spent on meaning rather than on "the model answered in English".

Every check returns a ``Check`` with a severity. ``gate()`` combines them into
a score and a list of concrete instructions the retry prompt can feed back
to the model ("sentence [4] is missing", "output must be in Arabic script").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.languages import get_language, normalize_text, script_ratio

_PREAMBLE = re.compile(
    r"^\s*(here (is|are) (the|your) translation|translation\s*:|sure[,!]|certainly[,!]|"
    r"below is|the translation (is|of)|voici|aquí está|以下是|ترجمہ\s*:|الترجمة\s*:)",
    re.IGNORECASE,
)
_FOOTNOTE_MARKERS = re.compile(r"\(\d{1,3}\)|\[\d{1,3}\]|(?<!\d)[۰-۹٠-٩]{1,3}(?!\d)")
_LIST_MARKERS = re.compile(r"^\s*(?:\(?[\d۰-۹٠-٩]+[).۔]|[-•*])", re.MULTILINE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TAGS = re.compile(r"</?(translation|notes|output|result)>", re.IGNORECASE)


@dataclass
class Check:
    name: str
    ok: bool
    severity: str = "medium"  # low | medium | high
    detail: str = ""
    instruction: str = ""  # what to tell the model on retry


@dataclass
class GateResult:
    score: float
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(c.severity == "high" and not c.ok for c in self.checks)

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def instructions(self) -> list[str]:
        return [c.instruction for c in self.problems if c.instruction]

    def as_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 3),
            "passed": self.passed,
            "problems": [
                {
                    "name": c.name,
                    "severity": c.severity,
                    "detail": c.detail,
                    "instruction": c.instruction,
                }
                for c in self.problems
            ],
        }


def clean_model_output(text: str) -> str:
    """Strip reasoning blocks, stray tags, markdown fences and chat preambles
    that small models wrap around the answer."""
    text = _THINK.sub("", text or "")
    text = _TAGS.sub("", text)
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE)
    lines = text.strip().splitlines()
    if lines and _PREAMBLE.match(lines[0]) and len(lines) > 1:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _length_ratio_band(source_lang: str, target_lang: str) -> tuple[float, float]:
    """Plausible target/source character ratio. Script pairs differ: Arabic is
    terse, Urdu and Latin are longer, CJK is far shorter than alphabets."""
    src = get_language(source_lang)
    tgt = get_language(target_lang)
    base = (0.6, 1.8)
    if src and tgt:
        if not src.spaced and tgt.spaced:
            return (1.2, 4.5)
        if src.spaced and not tgt.spaced:
            return (0.2, 0.9)
        if src.script == "Arabic" and tgt.script == "Latin":
            return (0.9, 2.2)
        if src.script == "Latin" and tgt.script == "Arabic":
            return (0.5, 1.3)
        if src.code == "ur" and tgt.code == "ar":
            return (0.55, 1.4)
        if src.code == "ar" and tgt.code == "ur":
            return (0.8, 1.9)
    return base


def gate(
    source: str,
    translation: str,
    *,
    source_language: str,
    target_language: str,
    glossary: list[dict[str, object]] | None = None,
    missing_sentences: list[int] | None = None,
) -> GateResult:
    checks: list[Check] = []
    src = normalize_text(source or "")
    out = normalize_text(translation or "")

    # 1. emptiness
    if not out.strip():
        checks.append(
            Check("empty", False, "high", "empty translation", "Return the full translation.")
        )
        return GateResult(0.0, checks)

    # 2. wrong language / untranslated copy
    tgt = get_language(target_language)
    src_lang = get_language(source_language)
    same_script = bool(tgt and src_lang and tgt.script == src_lang.script)
    ratio_target = script_ratio(out, target_language)
    if tgt and ratio_target < 0.6:
        checks.append(
            Check(
                "target_script",
                False,
                "high",
                f"only {ratio_target:.0%} of letters are in {tgt.script} script",
                f"Write the translation in {tgt.name} ({tgt.script} script) only.",
            )
        )
    else:
        checks.append(Check("target_script", True))
    if not same_script and src_lang:
        leak = script_ratio(out, source_language)
        if leak > 0.35:
            checks.append(
                Check(
                    "source_leak",
                    False,
                    "high",
                    f"{leak:.0%} of letters are still in the source script",
                    "Do not copy the source text; translate every sentence.",
                )
            )
    if src.strip() and out.strip() == src.strip():
        checks.append(
            Check(
                "copied",
                False,
                "high",
                "translation is identical to the source",
                "Translate the text; do not return it unchanged.",
            )
        )

    # 3. length ratio
    lo, hi = _length_ratio_band(source_language, target_language)
    ratio = len(out) / max(1, len(src))
    if len(src) >= 80 and (ratio < lo or ratio > hi):
        sev = "high" if ratio < lo * 0.7 or ratio > hi * 1.4 else "medium"
        what = "too short (possible omission)" if ratio < lo else "too long (possible additions)"
        checks.append(
            Check(
                "length_ratio",
                False,
                sev,
                f"length ratio {ratio:.2f} outside {lo}-{hi}: {what}",
                "Translate every sentence once; add nothing that is not in the source."
                if ratio < lo
                else "Remove commentary or explanations that are not in the source.",
            )
        )
    else:
        checks.append(Check("length_ratio", True))

    # 4. preamble / chatter
    if _PREAMBLE.match(out):
        checks.append(
            Check(
                "preamble",
                False,
                "medium",
                "starts with a chat preamble",
                "Output only the translation, with no introduction.",
            )
        )

    # 5. structure: paragraph count, list markers, footnote markers
    src_paras = len([p for p in re.split(r"\n\s*\n", src) if p.strip()])
    out_paras = len([p for p in re.split(r"\n\s*\n", out) if p.strip()])
    if src_paras >= 2 and abs(src_paras - out_paras) > max(1, src_paras // 3):
        checks.append(
            Check(
                "paragraphs",
                False,
                "low",
                f"{src_paras} source paragraphs vs {out_paras} in translation",
                "Keep the same paragraph breaks as the source.",
            )
        )
    src_lists = len(_LIST_MARKERS.findall(src))
    out_lists = len(_LIST_MARKERS.findall(out))
    if src_lists >= 2 and out_lists < src_lists - 1:
        checks.append(
            Check(
                "list_items",
                False,
                "medium",
                f"{src_lists} list items in source, {out_lists} in translation",
                "Keep every numbered or bulleted item, with its number.",
            )
        )
    src_fn = set(_FOOTNOTE_MARKERS.findall(src))
    if src_fn:
        out_fn = set(_FOOTNOTE_MARKERS.findall(out))
        lost = src_fn - out_fn
        if len(lost) > max(1, len(src_fn) // 2):
            checks.append(
                Check(
                    "footnote_markers",
                    False,
                    "low",
                    f"footnote markers missing: {sorted(lost)[:5]}",
                    "Keep footnote markers such as (1) exactly where they appear.",
                )
            )

    # 6. glossary adherence
    if glossary:
        expected = 0
        missing_terms: list[str] = []
        for entry in glossary:
            term = str(entry.get("original_term", "")).strip()
            rendering = str(entry.get("translation", "")).strip()
            if term and rendering and term in src:
                expected += 1
                if rendering not in out:
                    missing_terms.append(f"{term} → {rendering}")
        if expected:
            if missing_terms:
                checks.append(
                    Check(
                        "glossary",
                        False,
                        "medium",
                        f"{len(missing_terms)}/{expected} glossary terms not used",
                        "Use the glossary renderings exactly: " + "; ".join(missing_terms[:6]),
                    )
                )
            else:
                checks.append(Check("glossary", True))

    # 7. sentence alignment report (from the segmenter)
    if missing_sentences:
        checks.append(
            Check(
                "sentences",
                False,
                "high",
                f"sentences not translated: {missing_sentences[:8]}",
                f"Translate sentences {missing_sentences[:8]}; every [n] must appear once.",
            )
        )

    # score: start at 1, subtract by severity
    penalty = {"high": 0.35, "medium": 0.15, "low": 0.05}
    score = 1.0 - sum(penalty[c.severity] for c in checks if not c.ok)
    return GateResult(max(0.0, min(1.0, score)), checks)
