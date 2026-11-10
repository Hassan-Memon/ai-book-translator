"""Pick the agent strategy for a book given the model it will run on.

The same graph (app/agents/chunk_graph.py) serves a 4B model on a laptop and
a frontier model in the cloud. What changes is *how much scaffolding* the
model gets. Small models do not fail at translating a sentence; they fail at
following instructions over 1,500 characters: they skip a sentence, answer in
the wrong language, add "Here is the translation:", or produce broken JSON.
Every item below is a cheap, deterministic countermeasure for one of those
failures (docs/AGENT_STRATEGY.md explains each).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings, settings
from app.llm.catalog import model_tier

PROFILES = ("auto", "fast", "balanced", "thorough")


@dataclass(frozen=True)
class Strategy:
    profile: str  # fast | balanced | thorough (resolved, never "auto")
    tier: str  # small | medium | large
    # Number the source sentences and require a numbered translation back.
    # Deterministic omission check; the single biggest win for small models.
    sentence_alignment: bool
    # Ask for <translation>...</translation> tags instead of JSON for the
    # translation itself (small models mangle JSON around long RTL text).
    tagged_output: bool
    # Run the deterministic quality gate before spending an LLM call on review.
    gate: bool
    # LLM reviewer with span-level fixes.
    verify: bool
    max_retries: int
    # Second pass that only polishes fluency.
    polish: bool
    # Candidates sampled per chunk; the gate picks the best. Free on local models.
    candidates: int
    # Approved chunks of the same book shown as examples (translation memory).
    memory_examples: int
    # Terminology flags for the human glossary workflow.
    terminology: bool
    # Soft chunk budget in characters (smaller for smaller models).
    chunk_target_chars: int
    # Repair OCR noise with the LLM before translating when quality is poor.
    ocr_cleanup: str  # auto | always | off
    ocr_cleanup_threshold: float
    verification_threshold: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _opt(book_settings: dict[str, Any] | None, key: str, default: Any) -> Any:
    if book_settings and book_settings.get(key) not in (None, "", "auto"):
        return book_settings[key]
    return default


def resolve(
    model: str,
    *,
    cfg: Settings | None = None,
    book_settings: dict[str, Any] | None = None,
    is_local: bool = False,
    fake: bool = False,
) -> Strategy:
    cfg = cfg or settings
    if fake:
        # The deterministic demo provider: plain translate -> verify -> terminology.
        return Strategy(
            profile="balanced",
            tier="large",
            sentence_alignment=False,
            tagged_output=False,
            gate=False,
            verify=True,
            max_retries=int(cfg.max_translation_retries),
            polish=False,
            candidates=1,
            memory_examples=0,
            terminology=True,
            chunk_target_chars=int(cfg.chunk_target_chars),
            ocr_cleanup="off",
            ocr_cleanup_threshold=float(cfg.ocr_cleanup_threshold),
            verification_threshold=float(cfg.verification_threshold),
        )
    tier = model_tier(model)

    profile = str(_opt(book_settings, "quality_profile", cfg.quality_profile)).lower()
    if profile not in PROFILES or profile == "auto":
        # Small models need the scaffolding; big models are good enough that
        # the balanced path (translate -> gate -> verify) is the sweet spot.
        profile = "thorough" if tier == "small" else "balanced"

    align_setting = str(_opt(book_settings, "sentence_alignment", cfg.sentence_alignment)).lower()
    if align_setting == "auto":
        sentence_alignment = tier in ("small", "medium")
    else:
        sentence_alignment = align_setting in ("on", "true", "1", "yes")

    polish_setting = str(_opt(book_settings, "polish_pass", cfg.polish_pass)).lower()
    if polish_setting == "auto":
        polish = profile == "thorough" and tier != "large"
    else:
        polish = polish_setting in ("on", "true", "1", "yes")

    candidates = int(_opt(book_settings, "translation_candidates", cfg.translation_candidates))
    if candidates <= 1 and profile == "thorough" and is_local and tier == "small":
        candidates = 2  # local compute is free; a second sample often fixes an omission
    candidates = max(1, min(5, candidates))

    memory_examples = int(
        _opt(book_settings, "translation_memory_examples", cfg.translation_memory_examples)
    )
    chunk_chars = int(_opt(book_settings, "chunk_target_chars", cfg.chunk_target_chars))
    if tier == "small":
        chunk_chars = min(chunk_chars, 700)
    elif tier == "medium":
        chunk_chars = min(chunk_chars, 1000)

    verify = profile != "fast"
    base_retries = int(_opt(book_settings, "max_translation_retries", cfg.max_translation_retries))
    max_retries = {"fast": 0, "balanced": base_retries, "thorough": max(2, base_retries)}[profile]
    if tier == "small":
        max_retries = max(max_retries, 1)

    return Strategy(
        profile=profile,
        tier=tier,
        sentence_alignment=sentence_alignment,
        tagged_output=tier != "large",
        gate=True,
        verify=verify,
        max_retries=max_retries,
        polish=polish,
        candidates=candidates,
        memory_examples=max(0, min(6, memory_examples)),
        terminology=profile != "fast",
        chunk_target_chars=chunk_chars,
        ocr_cleanup=str(_opt(book_settings, "ocr_llm_cleanup", cfg.ocr_llm_cleanup)).lower(),
        ocr_cleanup_threshold=float(cfg.ocr_cleanup_threshold),
        verification_threshold=float(
            _opt(book_settings, "verification_threshold", cfg.verification_threshold)
        ),
    )
