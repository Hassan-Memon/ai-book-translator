"""Language registry, model catalog, agent strategy, segmenter, quality gate."""

from __future__ import annotations

from app.agents import strategy
from app.agents.quality import clean_model_output, gate
from app.agents.segmenter import join_numbered, number_sentences, parse_numbered, split_sentences
from app.core.config import settings
from app.core.languages import (
    LANGUAGES,
    font_for,
    get_language,
    guess_language,
    is_rtl,
    script_ratio,
    tesseract_langs,
)
from app.llm.catalog import PROVIDERS, model_supports_vision, model_tier
from app.llm.provider import parse_tagged, repair_json, strip_thinking

# --- languages ---------------------------------------------------------------


def test_registry_has_many_languages_with_unique_codes() -> None:
    codes = [lang.code for lang in LANGUAGES]
    assert len(codes) >= 45
    assert len(set(codes)) == len(codes)
    assert get_language("UR") is not None and get_language("en-US").code == "en"
    assert get_language("xx") is None


def test_language_metadata_drives_fonts_direction_and_ocr() -> None:
    assert is_rtl("ar") and is_rtl("ur") and is_rtl("he") and not is_rtl("en")
    assert font_for("ur") == "Noto Nastaliq Urdu"
    assert font_for("hi").startswith("Noto")
    assert tesseract_langs("ur") == ["urd", "ara"]
    assert tesseract_langs("unknown") == ["eng"]


def test_guess_language_from_script_and_markers() -> None:
    assert guess_language("یہ ایک اردو جملہ ہے۔ کتاب پڑھیں") == "ur"
    assert guess_language("هذا كتاب عربي عن الفقه والحديث") == "ar"
    assert guess_language("این یک کتاب فارسی است که خواندن آن آسان است") == "fa"
    assert guess_language("This is plain English text.") == "en"
    assert guess_language("यह हिन्दी का वाक्य है") == "hi"
    assert guess_language("12345 ...") is None
    # candidates narrow the search
    assert guess_language("هذا كتاب", candidates=("ar", "en")) == "ar"


def test_script_ratio_detects_wrong_language_output() -> None:
    assert script_ratio("هذا نص عربي", "ar") == 1.0
    assert script_ratio("this is english", "ar") == 0.0
    assert 0.4 < script_ratio("نص عربي mixed", "ar") < 0.7


# --- catalog / strategy ----------------------------------------------------------


def test_model_tiers_and_vision() -> None:
    assert model_tier("qwen3:4b") == "small"
    assert model_tier("qwen3:8b") == "medium"
    assert model_tier("gemma3:12b") == "medium"
    assert model_tier("llama-3.3-70b-versatile") == "large"
    assert model_tier("gpt-4.1") == "large"
    assert model_tier("gpt-4.1-mini") == "medium"
    assert model_tier("claude-sonnet-5-5") == "large"
    assert model_supports_vision("qwen2.5vl:7b")
    assert model_supports_vision("gemma3:4b")
    assert not model_supports_vision("llama3.1:8b")
    assert {"ollama", "lmstudio", "openai", "anthropic", "gemini", "openrouter"} <= set(PROVIDERS)


def test_strategy_scales_scaffolding_with_model_size() -> None:
    small = strategy.resolve("qwen3:4b", cfg=settings, is_local=True)
    large = strategy.resolve("gpt-4.1", cfg=settings)
    assert small.profile == "thorough" and small.sentence_alignment and small.tagged_output
    assert small.chunk_target_chars <= 700 and small.candidates >= 2 and small.polish
    assert large.profile == "balanced" and not large.sentence_alignment
    assert not large.tagged_output and large.candidates == 1
    forced = strategy.resolve("gpt-4.1", cfg=settings, book_settings={"quality_profile": "fast"})
    assert forced.profile == "fast" and not forced.verify and forced.max_retries == 0
    fake = strategy.resolve("fake-1", cfg=settings, fake=True)
    assert not fake.gate and not fake.sentence_alignment


# --- segmenter -------------------------------------------------------------------


def test_split_sentences_handles_urdu_arabic_and_abbreviations() -> None:
    urdu = "یہ پہلا جملہ ہے۔ یہ دوسرا جملہ ہے؟ تیسرا!"
    assert split_sentences(urdu, "ur") == ["یہ پہلا جملہ ہے۔", "یہ دوسرا جملہ ہے؟", "تیسرا!"]
    english = "Dr. Smith wrote vol. 2. It sold well. See p. 3."
    assert split_sentences(english, "en") == [
        "Dr. Smith wrote vol. 2.",
        "It sold well.",
        "See p. 3.",
    ]
    assert split_sentences("One paragraph\n\nSecond paragraph", "en") == [
        "One paragraph",
        "Second paragraph",
    ]


def test_numbered_round_trip_and_missing_detection() -> None:
    sentences = ["A.", "B.", "C."]
    numbered = number_sentences(sentences)
    assert numbered == "[1] A.\n[2] B.\n[3] C."
    by_number, problems = parse_numbered("[1] x [2] y\n[3] z", 3)
    assert by_number == {1: "x", 2: "y", 3: "z"} and problems == []
    by_number, problems = parse_numbered("[1] x\n[3] z", 3)
    assert any("missing" in p for p in problems)
    assert join_numbered(by_number, 3, sentences) == "x B. z"
    assert parse_numbered("no markers", 2)[1]


# --- quality gate ------------------------------------------------------------------


def test_gate_catches_wrong_script_copy_and_empty() -> None:
    src = "یہ ایک اردو کتاب ہے جو دین کے بارے میں ہے اور اس میں بہت سے مسائل بیان ہوئے ہیں۔"
    empty = gate(src, "", source_language="ur", target_language="ar")
    assert not empty.passed
    english = gate(
        src,
        "This is an English answer instead of Arabic.",
        source_language="ur",
        target_language="ar",
    )
    assert not english.passed and any(c.name == "target_script" for c in english.problems)
    copied = gate(src, src, source_language="ur", target_language="ar")
    assert not copied.passed
    good = gate(
        src,
        "هذا كتاب أردي يتحدث عن الدين وقد بُيّنت فيه مسائل كثيرة.",
        source_language="ur",
        target_language="ar",
    )
    assert good.passed and good.score >= 0.9


def test_gate_checks_glossary_and_sentence_alignment() -> None:
    src = "نماز فرض ہے۔ روزہ بھی فرض ہے۔"
    glossary = [{"original_term": "نماز", "translation": "الصلاة"}]
    missing = gate(
        src, "الصوم واجب أيضاً.", source_language="ur", target_language="ar", glossary=glossary
    )
    assert any(c.name == "glossary" for c in missing.problems)
    aligned = gate(
        src,
        "الصلاة واجبة. الصوم واجب أيضاً.",
        source_language="ur",
        target_language="ar",
        glossary=glossary,
        missing_sentences=[2],
    )
    assert not aligned.passed and any(c.name == "sentences" for c in aligned.problems)
    assert aligned.instructions()


def test_clean_model_output_strips_thinking_and_preamble() -> None:
    raw = "<think>reasoning…</think>Here is the translation:\n```\nنص\n```"
    assert clean_model_output(raw) == "نص"


# --- provider parsing helpers -------------------------------------------------------


def test_repair_json_and_tagged_parsing() -> None:
    broken = '<think>hmm</think>Sure: {"score": 0.8, "summary": "ok\nfine", "suggestions": [],}'
    import json

    assert json.loads(repair_json(broken)) == {
        "score": 0.8,
        "summary": "ok\nfine",
        "suggestions": [],
    }
    tagged = parse_tagged(
        "<think>x</think><TRANSLATION>hello</TRANSLATION><notes>n", ["translation", "notes"]
    )
    assert tagged == {"translation": "hello", "notes": "n"}
    assert strip_thinking("<think>a</think> b") == "b"
