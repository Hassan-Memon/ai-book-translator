"""The provider layer against a stand-in chat model: text, tagged, JSON
fallback with repair, retries on transient errors, the ledger, factories,
and the OCR language-pack manager."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents.schemas import VerificationOutput
from app.core.config import settings
from app.llm.catalog import provider_spec
from app.llm.provider import (
    AnthropicProvider,
    CallContext,
    CallRecord,
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    RuntimeLlm,
    build_provider,
    resolve_openai_compatible_base,
)
from app.pipeline.ocr import tessdata


class _Msg:
    def __init__(self, content: str):
        self.content = content
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 20}


class _ScriptedChat:
    """Minimal stand-in for a LangChain chat model."""

    def __init__(self, answers: list[Any]):
        self.answers = list(answers)
        self.prompts: list[Any] = []

    async def ainvoke(self, prompt: Any) -> _Msg:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Msg(answer)


class _Provider(LLMProvider):
    name = "scripted"
    supports_structured = False

    def __init__(self, answers: list[Any], **kw: Any):
        cfg = settings.model_copy(update={"llm_max_retries": 2})
        records: list[CallRecord] = []

        async def recorder(rec: CallRecord) -> None:
            records.append(rec)

        super().__init__("gpt-4.1-mini", cfg=cfg, recorder=recorder, **kw)
        self.records = records
        self._chat = _ScriptedChat(answers)

    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        return self._chat


CTX = CallContext(
    node="verify", book_id=None, chunk_index=1, prompt_name="verification", prompt_version=3
)


async def test_text_call_strips_thinking_and_records_cost() -> None:
    p = _Provider(["<think>hmm</think>  Bonjour  "])
    assert await p.ainvoke_text("Say hi", CTX) == "Bonjour"
    rec = p.records[0]
    assert rec.status == "ok" and rec.input_tokens == 100 and rec.output_tokens == 20
    assert rec.cost_usd > 0 and rec.prompt_version == 3


async def test_tagged_call_falls_back_to_whole_answer_and_errors_on_empty() -> None:
    p = _Provider(
        ["<translation>نص</translation><notes>a</notes>", "just text", "<think>x</think>"]
    )
    assert await p.ainvoke_tagged("t", ["translation", "notes"], CTX) == {
        "translation": "نص",
        "notes": "a",
    }
    assert (await p.ainvoke_tagged("t", ["translation"], CTX))["translation"] == "just text"
    assert p.records[1].extra.get("untagged") is True
    with pytest.raises(LLMOutputError):
        await p.ainvoke_tagged("t", ["translation"], CTX)
    assert p.records[-1].status == "parse_error"


async def test_structured_json_mode_repairs_small_model_output() -> None:
    sloppy = 'Sure!\n```json\n{"score": 0.7, "summary": "line1\nline2", "suggestions": [],}\n```'
    p = _Provider([sloppy, "no json here"])
    out = await p.ainvoke_structured("review this", VerificationOutput, CTX)
    assert out.score == 0.7 and out.summary == "line1\nline2"
    assert "JSON schema" in p._chat.prompts[0]
    with pytest.raises(LLMOutputError):
        await p.ainvoke_structured("again", VerificationOutput, CTX)
    assert p.records[-1].status == "parse_error"


async def test_transient_errors_are_retried_and_auth_errors_are_not() -> None:
    p = _Provider([RuntimeError("429 rate limit"), "ok"])
    assert await p.ainvoke_text("x", CTX) == "ok"
    assert p.records[0].attempts == 2

    p = _Provider([RuntimeError("401 invalid api key"), "never"])
    with pytest.raises(LLMError):
        await p.ainvoke_text("x", CTX)
    assert p.records[0].status == "error" and p.records[0].attempts == 1


async def test_vision_and_ping_use_the_chat_model() -> None:
    p = _Provider(["page text", "OK."])
    assert await p.ainvoke_vision("read", "aGk=", CTX, mime="image/jpeg") == "page text"
    message = p._chat.prompts[0][0]
    assert message.content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert await p.aping() == "OK."


def test_factory_builds_each_provider_kind_and_explains_missing_keys() -> None:
    with pytest.raises(LLMConfigError, match="needs an API key"):
        build_provider(RuntimeLlm(provider="openai", model="gpt-4.1"))
    with pytest.raises(LLMConfigError, match="Unknown LLM provider"):
        build_provider(RuntimeLlm(provider="nope", model="x"))
    with pytest.raises(LLMConfigError):
        build_provider(RuntimeLlm(provider="anthropic", model="claude-sonnet-5-5"))

    oa = build_provider(RuntimeLlm(provider="openrouter", model="m", api_key="k"))
    assert isinstance(oa, OpenAICompatibleProvider) and oa.base_url.endswith("/api/v1")
    assert not oa.is_local and not oa.supports_structured
    local = build_provider(RuntimeLlm(provider="lmstudio", model="qwen3-4b"))
    assert local.is_local and local.api_key == "not-needed"
    custom = build_provider(
        RuntimeLlm(provider="openai_compatible", model="m", base_url="http://127.0.0.1:9000/v1")
    )
    assert custom.is_local and custom.base_url == "http://127.0.0.1:9000/v1"
    ol = build_provider(RuntimeLlm(provider="ollama", model="qwen3:8b"))
    assert isinstance(ol, OllamaProvider) and ol.is_local
    an = build_provider(RuntimeLlm(provider="anthropic", model="claude-sonnet-5-5", api_key="k"))
    assert isinstance(an, AnthropicProvider)
    # The LangChain clients construct without network access.
    assert oa.chat_model is not None and ol.chat_model is not None and an.chat_model is not None
    assert ol.json_chat_model is not None


def test_openai_compatible_base_urls_are_normalised() -> None:
    assert resolve_openai_compatible_base("https://models.github.ai/inference") == (
        "https://models.github.ai/inference/openai/"
    )
    assert (
        resolve_openai_compatible_base("https://openrouter.ai/api")
        == "https://openrouter.ai/api/v1"
    )
    assert resolve_openai_compatible_base(
        "https://generativelanguage.googleapis.com/v1beta"
    ).endswith("/openai/")
    assert resolve_openai_compatible_base("http://localhost:1234/v1/") == "http://localhost:1234/v1"
    assert provider_spec("GROQ") is not None


# ---------------------------------------------------------------- tessdata


def _pack(directory: Path, lang: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{lang}.traineddata").write_bytes(b"x" * 10)


def test_ensure_packs_uses_system_copies_and_downloads_missing(tmp_path, monkeypatch) -> None:
    system = tmp_path / "system"
    managed = tmp_path / "managed"
    _pack(system, "eng")
    _pack(system, "osd")
    monkeypatch.setattr(tessdata, "system_tessdata_dirs", lambda: [system])
    downloaded: list[str] = []

    def fake_download(lang: str, dest: Path, repo: str = "best", timeout: float = 120.0) -> Path:
        downloaded.append(lang)
        _pack(dest, lang)
        return dest / f"{lang}.traineddata"

    monkeypatch.setattr(tessdata, "download_pack", fake_download)

    # Everything available in one system dir: use it directly.
    directory, usable = tessdata.ensure_packs(["eng"], managed)
    assert directory == system and usable == ["eng"]

    # A missing pack: copy what exists, download the rest, into the managed dir.
    directory, usable = tessdata.ensure_packs(["urd", "eng"], managed)
    assert directory == managed and usable == ["urd", "eng"] and downloaded == ["urd"]
    assert tessdata.installed_langs(managed) >= {"urd", "eng", "osd"}
    assert tessdata.all_installed_langs(managed) >= {"urd", "eng"}

    # Offline: a pack that cannot be found is dropped, not fatal.
    directory, usable = tessdata.ensure_packs(["hin"], managed, allow_download=False)
    assert usable == [] and directory is None
    assert tessdata.ensure_packs([], managed) == (None, [])


def test_download_failure_is_reported_not_raised(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tessdata, "system_tessdata_dirs", lambda: [])

    def broken(*_a: Any, **_k: Any) -> Path:
        raise RuntimeError("offline")

    monkeypatch.setattr(tessdata, "download_pack", broken)
    assert tessdata.ensure_packs(["tha"], tmp_path / "m") == (None, [])
