"""Evaluation harness: metrics, golden-set validation, judge plumbing, and a
full run of the real chunk graph over the starter golden set (offline)."""

from __future__ import annotations

import json

import pytest

from app.core.config import REPO_ROOT, settings
from app.evals import metrics
from app.evals.golden import GoldenItem, load_golden, validate_golden
from app.evals.judge import calibrate, degrade, model_family, same_family
from app.evals.runner import EvalConfig, bootstrap_ci, run_eval, select_items, write_results
from app.llm.provider import FakeProvider

STARTER = REPO_ROOT / "docs" / "evals" / "golden" / "starter-v1.jsonl"


# ------------------------------------------------------------------ chrF++


@pytest.mark.parametrize(
    ("hyp", "ref", "expected"),
    [
        # Values computed with sacrebleu 2.x CHRF(word_order=2).sentence_score.
        ("The cat sat on the mat.", "The cat sat on the mat.", 100.0),
        ("The cat is on the mat.", "The cat sat on the mat.", 67.49),
        ("A dog ran in the park!", "The cat sat on the mat.", 11.36),
        (
            "الصلاة عماد الدين، فمن أقامها فقد أقام الدين.",
            "الصلاة عمود الدين، فمن أقامها فقد أقام الدين.",
            87.9,
        ),
        ("नमस्ते, आप कैसे हैं?", "नमस्ते, तुम कैसे हो?", 46.16),
        ("یہ ایک کتاب ہے۔", "یہ کتاب ہے۔", 67.31),
        ("Hi", "Hello there, friend", 4.76),
    ],
)
def test_chrf_matches_sacrebleu(hyp: str, ref: str, expected: float) -> None:
    assert metrics.chrf_pp(hyp, ref) == pytest.approx(expected, abs=0.01)


def test_chrf_takes_best_reference_and_handles_empty() -> None:
    refs = ["completely different words here", "The cat sat on the mat."]
    assert metrics.chrf_pp("The cat sat on the mat.", refs) == 100.0
    assert metrics.chrf_pp("", refs) == 0.0
    assert metrics.chrf_pp("   ", "x") == 0.0


# ------------------------------------------------------------------ terms and structure


def test_term_adherence_counts_variants_and_skips_absent_terms() -> None:
    terms = [
        {"source": "نماز", "target": "الصلاة", "variants": ["نمازیں"], "must_match": True},
        {"source": "روزہ", "target": "الصوم", "variants": [], "must_match": True},  # not in source
        {"source": "دین", "target": "الدين", "variants": [], "must_match": False},  # advisory
    ]
    report = metrics.term_adherence("أقيموا الصلاة", "نمازیں دین", terms)
    assert report["expected"] == 1 and report["matched"] == 1 and report["adherence"] == 1.0
    miss = metrics.term_adherence("أقيموا العبادة", "نماز", terms)
    assert miss["adherence"] == 0.0 and miss["missing"] == ["نماز"]
    assert metrics.term_adherence("x", "nothing", terms)["adherence"] is None


def test_structure_report() -> None:
    src_list = "1. Read.\n2. Mark.\n3. Write."
    assert metrics.structure_report("1. اقرأ.\n2. ضع.\n3. اكتب.", src_list, "numbered_list")[
        "preserved"
    ]
    merged = metrics.structure_report("اقرأ وضع واكتب.", src_list, "numbered_list")
    assert merged["checks"]["list_items"] is False
    # Footnote markers survive in other digit systems.
    note = metrics.structure_report("(۱) یہ کہانی", "(1) This story", "footnote")
    assert note["checks"]["footnote_markers"] is True
    assert not metrics.structure_report("یہ کہانی", "(1) This story", "footnote")["preserved"]
    heading = metrics.structure_report("الفصل\nالأول", "Chapter One", "heading")
    assert heading["checks"]["single_line_heading"] is False
    verse = "﴿اقْرَأْ﴾"
    assert metrics.structure_report(verse, verse, "quranic_verse")["checks"]["verse_brackets"]
    assert not metrics.structure_report("", "text", "prose")["preserved"]


# ------------------------------------------------------------------ golden set


def test_starter_golden_set_is_valid() -> None:
    items = load_golden(STARTER)
    assert len(items) >= 15
    assert validate_golden(items) == []
    pairs = {i.pair for i in items}
    assert {"en→ar", "en→ur", "en→hi", "ur→ar"} <= pairs
    assert any(i.adversarial for i in items)
    # Release rules are stricter and the starter set does not claim to meet them.
    assert validate_golden(items, release=True)


def test_validation_catches_contract_violations() -> None:
    base = {
        "id": "x-1",
        "source_lang": "ur",
        "target_lang": "ar",
        "content_type": "prose",
        "source": "نماز",
        "reference": "الصلاة",
        "split": "dev",
    }
    items = [
        GoldenItem.model_validate(base),
        GoldenItem.model_validate(base),  # duplicate id
        GoldenItem.model_validate({**base, "id": "x-2", "source_lang": "zz"}),
        GoldenItem.model_validate(
            {**base, "id": "x-3", "terms": [{"source": "روزہ", "target": "الصوم"}]}
        ),
        GoldenItem.model_validate({**base, "id": "x-4", "content_type": "quranic_verse"}),
        GoldenItem.model_validate({**base, "id": "x-5", "target_lang": "ur"}),
    ]
    problems = "\n".join(validate_golden(items))
    assert "duplicate id" in problems
    assert "unknown language code 'zz'" in problems
    assert "'روزہ'" in problems
    assert "passthrough" in problems
    assert "same" in problems


def test_select_items_filters() -> None:
    items = load_golden(STARTER)
    assert all(i.split == "test" for i in select_items(items, EvalConfig(split="test")))
    only = select_items(items, EvalConfig(split=None, pairs=["en->hi"]))
    assert only and {i.pair for i in only} == {"en→hi"}
    assert len(select_items(items, EvalConfig(split=None, limit=2))) == 2


# ------------------------------------------------------------------ judge


def test_model_family() -> None:
    assert model_family("gpt-4.1-mini") == "openai"
    assert model_family("openai/gpt-4.1") == "openai"
    assert model_family("aya-expanse:8b") == "cohere"
    assert model_family("llama3.1:8b") == "meta"
    assert model_family("qwen3:4b") == model_family("qwen2.5vl:7b") == "qwen"
    assert same_family("gemma3:12b", "gemini-2.5-flash")
    assert not same_family("aya-expanse:8b", "llama3.1:8b")


def test_degrade_targets_an_axis() -> None:
    bad, axis = degrade("First sentence. Second sentence.")
    assert axis == "omissions" and bad == "First sentence."
    bad, axis = degrade("الصلاة عمود الدين", [{"target": "الصلاة"}])
    assert axis == "terminology" and "الصلاة" not in bad


async def test_calibrate_with_fake_judge() -> None:
    items = [i for i in load_golden(STARTER) if i.content_type.value == "prose"][:3]
    result = await calibrate(FakeProvider(cfg=settings), items)
    assert result["agreement"] == 1.0
    assert all(r["reference"]["adequacy"] == 5 for r in result["items"])


def test_bootstrap_ci_is_reproducible() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert bootstrap_ci(values) == bootstrap_ci(values)
    lo, hi = bootstrap_ci(values)
    assert lo < 30.0 < hi
    assert bootstrap_ci([1.0, 2.0]) is None


# ------------------------------------------------------------------ full run


async def test_run_eval_end_to_end_with_real_graph(tmp_path) -> None:
    """The harness drives the product's chunk graph: passthrough for the Quranic
    verse, the glossary seeded from terms, every item scored, cost and call
    counts captured without a database, cache reused on the second run."""
    items = load_golden(STARTER)
    translator = FakeProvider(cfg=settings)
    conf = EvalConfig(split=None, cache_dir=tmp_path / "cache", note="test")
    run = await run_eval(items, translator, judge_provider=FakeProvider(cfg=settings), conf=conf)

    by_id = {r["id"]: r for r in run["items"]}
    assert len(by_id) == len(items)
    verse = by_id["ur-ar-0004"]
    assert verse["chrf"] == 100.0 and verse["structure"]["preserved"]
    assert verse["llm_calls"] == 0  # passthrough: no model call
    prose = by_id["en-ur-0001"]
    assert prose["llm_calls"] >= 1 and prose["translation"].startswith("[fake-")
    assert prose["terms_expected"] == 2
    # The glossary reached the translation prompt.
    prompts = [p for kind, p in translator.calls if "لومڑی" in p]
    assert prompts, "decided terms were not passed to the graph as glossary"
    assert translator.recorder is None  # restored after the run

    agg = run["aggregate"]
    assert agg["items"] == len(items) and agg["errors"] == 0
    assert set(agg["by_pair"]) == {"en→ar", "en→ur", "en→hi", "ur→ar"}
    assert agg["judge"]["mean"] is not None
    meta = run["meta"]
    assert meta["prompt_versions"]["translation"] >= 1 and meta["prompt_versions"]["judge"] == 1
    assert any("same family" in w for w in meta["warnings"])

    path = write_results(run, tmp_path / "results", STARTER.name)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["meta"]["golden"] == STARTER.name
    readme = (tmp_path / "results" / "README.md").read_text(encoding="utf-8")
    assert "| `fake-1` |" in readme and path.name in readme

    again = await run_eval(items, FakeProvider(cfg=settings), conf=conf)
    cached = [r for r in again["items"] if r["cached"]]
    assert len(cached) == len(items)  # nothing re-translated
    assert sum(r["llm_calls"] for r in again["items"]) == agg["llm_calls"]


async def test_only_cached_rescoring_never_calls_the_translator(tmp_path) -> None:
    items = [i for i in load_golden(STARTER) if i.pair == "ur→ar"]
    conf = EvalConfig(split=None, cache_dir=tmp_path)
    await run_eval(items[:2], FakeProvider(cfg=settings), conf=conf)  # caches two items

    translator = FakeProvider(cfg=settings)
    conf.only_cached = True
    run = await run_eval(items, translator, conf=conf)
    ids = {r["id"] for r in run["items"]}
    # Two cached items plus the Quranic verse (passthrough needs no model).
    assert ids == {items[0].id, items[1].id, "ur-ar-0004"}
    assert translator.calls == []
    assert any("partial run" in w and "ur-ar-0003" in w for w in run["meta"]["warnings"])
