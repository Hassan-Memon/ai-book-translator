"""LLM provider layer.

One object, ``LLMProvider``, wraps a LangChain chat model and gives the rest
of the app exactly two calls:

    await provider.ainvoke_text(prompt, ctx)                -> str
    await provider.ainvoke_structured(prompt, Schema, ctx)  -> Schema

Both apply timeouts, retries with exponential backoff on retryable errors,
and record one ``llm_call`` row per invocation (tokens, cost, latency,
prompt version). Structured calls go through ``with_structured_output`` when
the model supports it and fall back to "ask for JSON, strip fences, validate
with Pydantic"; a response that still fails validation raises
``LLMOutputError`` (ADR-0005: parse failures are errors, not empty results).

Providers (set LLM_PROVIDER in .env):
  github     — GitHub Models (free tier, default)
  openai     — OpenAI
  anthropic  — Anthropic Claude   (needs: uv sync --extra anthropic)
  nvidia     — NVIDIA NIM (OpenAI-compatible)
  ollama     — Local Ollama       (needs: uv sync --extra ollama + ollama running)
  fake       — Deterministic offline provider used by tests and demo mode
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings, settings
from app.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class LLMError(RuntimeError):
    """Base class for provider failures."""


class LLMOutputError(LLMError):
    """The model answered but the answer could not be parsed into the schema."""


class LLMConfigError(LLMError):
    """Provider is not configured (missing key / package)."""


@dataclass
class CallContext:
    """Where a call comes from, for the llm_call ledger."""

    node: str
    book_id: uuid.UUID | str | None = None
    chunk_index: int | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None


@dataclass
class CallRecord:
    node: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    status: str = "ok"
    error: str | None = None
    book_id: uuid.UUID | str | None = None
    chunk_index: int | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _is_retryable(exc: BaseException) -> bool:
    """429/5xx/timeouts are retryable; auth/validation errors are not."""
    if isinstance(exc, LLMOutputError | LLMConfigError | ValidationError):
        return False
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(k in name for k in ("timeout", "ratelimit", "apiconnection", "internalserver")):
        return True
    return any(
        k in text for k in ("429", "rate limit", "timed out", "502", "503", "504", "overloaded")
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = _FENCE.sub("", text).strip()
    # Some models prepend a sentence before the JSON object; keep the outermost braces.
    if not text.startswith(("{", "[")):
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return text


def _usage(response: Any) -> tuple[int, int]:
    meta = getattr(response, "usage_metadata", None) or {}
    if meta:
        return int(meta.get("input_tokens", 0) or 0), int(meta.get("output_tokens", 0) or 0)
    rm = getattr(response, "response_metadata", None) or {}
    usage = rm.get("token_usage") or rm.get("usage") or {}
    return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


class LLMProvider:
    """Thin, testable façade over a LangChain chat model."""

    name: str = "base"

    def __init__(self, model: str, *, cfg: Settings | None = None, recorder: Any = None):
        self.model = model
        self.cfg = cfg or settings
        self.recorder = recorder  # async callable(CallRecord) -> None, or None
        self._chat: Any = None

    # -- subclasses provide the LangChain model ------------------------------
    def _build_chat_model(self) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def chat_model(self) -> Any:
        if self._chat is None:
            self._chat = self._build_chat_model()
        return self._chat

    def supports_vision(self) -> bool:
        return True

    # -- public API -----------------------------------------------------------
    async def ainvoke_text(self, prompt: str, ctx: CallContext) -> str:
        response, record = await self._invoke(lambda m: m.ainvoke(prompt), ctx)
        await self._record(record)
        content = getattr(response, "content", response)
        return content if isinstance(content, str) else str(content)

    async def ainvoke_structured(self, prompt: str, schema: type[T], ctx: CallContext) -> T:
        record: CallRecord | None = None
        try:
            structured = self.chat_model.with_structured_output(schema, include_raw=True)
            raw, record = await self._invoke(lambda _m: structured.ainvoke(prompt), ctx)
            parsed = raw.get("parsed") if isinstance(raw, dict) else None
            if isinstance(parsed, schema):
                await self._record(record)
                return parsed
            # with_structured_output could not parse: fall through to manual JSON.
            raw_msg = raw.get("raw") if isinstance(raw, dict) else None
            text = getattr(raw_msg, "content", "") if raw_msg is not None else ""
            result = self._parse_json(text, schema)
            await self._record(record)
            return result
        except LLMOutputError:
            if record:
                record.status = "parse_error"
                await self._record(record)
            raise
        except (NotImplementedError, AttributeError, TypeError, ValueError) as exc:
            # Model has no structured-output support: ask for JSON explicitly.
            logger.debug(
                "structured output unsupported for %s (%s); using JSON mode", self.model, exc
            )
        json_prompt = (
            f"{prompt}\n\nRespond with a single JSON object matching this JSON schema and nothing "
            f"else:\n{json.dumps(schema.model_json_schema())}"
        )
        response, record = await self._invoke(lambda m: m.ainvoke(json_prompt), ctx)
        try:
            result = self._parse_json(getattr(response, "content", ""), schema)
        except LLMOutputError:
            record.status = "parse_error"
            await self._record(record)
            raise
        await self._record(record)
        return result

    async def ainvoke_vision(
        self, text: str, image_b64: str, ctx: CallContext, mime: str = "image/png"
    ) -> str:
        from langchain_core.messages import HumanMessage

        message = HumanMessage(
            content=[
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ]
        )
        response, record = await self._invoke(lambda m: m.ainvoke([message]), ctx)
        await self._record(record)
        content = getattr(response, "content", "")
        return content if isinstance(content, str) else str(content)

    # -- internals ------------------------------------------------------------
    @staticmethod
    def _parse_json(text: str, schema: type[T]) -> T:
        candidate = _strip_fences(text or "")
        try:
            return schema.model_validate_json(candidate)
        except ValidationError as exc:
            raise LLMOutputError(
                f"{schema.__name__}: response did not match schema: {exc.errors()[:3]}; "
                f"head={candidate[:200]!r}"
            ) from exc

    async def _invoke(self, call: Any, ctx: CallContext) -> tuple[Any, CallRecord]:
        record = CallRecord(
            node=ctx.node,
            provider=self.name,
            model=self.model,
            book_id=ctx.book_id,
            chunk_index=ctx.chunk_index,
            prompt_name=ctx.prompt_name,
            prompt_version=ctx.prompt_version,
        )
        started = time.perf_counter()
        attempts = 0
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max(1, self.cfg.llm_max_retries)),
                wait=wait_exponential_jitter(initial=1, max=20),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    attempts += 1
                    response = await call(self.chat_model)
        except RetryError as exc:  # pragma: no cover - reraise=True makes this rare
            record.status = "error"
            record.error = str(exc)
            record.attempts = attempts
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            await self._record(record)
            raise LLMError(str(exc)) from exc
        except Exception as exc:
            record.status = "error"
            record.error = f"{type(exc).__name__}: {exc}"[:2000]
            record.attempts = attempts
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            await self._record(record)
            raise LLMError(record.error) from exc

        record.attempts = attempts
        record.latency_ms = int((time.perf_counter() - started) * 1000)
        usage_source = response.get("raw") if isinstance(response, dict) else response
        record.input_tokens, record.output_tokens = _usage(usage_source)
        record.cost_usd = estimate_cost(self.model, record.input_tokens, record.output_tokens)
        return response, record

    async def _record(self, record: CallRecord | None) -> None:
        if record is None or self.recorder is None:
            return
        try:
            await self.recorder(record)
        except Exception as exc:  # never let bookkeeping break the pipeline
            logger.warning("llm_call recording failed: %s", exc)


def resolve_openai_compatible_base(base_url: str) -> str:
    """GitHub Models serves the OpenAI-compatible API under ``/inference/openai``;
    other OpenAI-compatible hosts (OpenRouter, NVIDIA, local servers) expect
    their own ``/v1`` root. Accept either and normalise."""
    url = base_url.rstrip("/")
    if "models.github.ai" in url:
        return url + "/openai/" if not url.endswith("/openai") else url + "/"
    if "openrouter.ai" in url and not url.endswith("/v1"):
        return url + "/v1" if url.endswith("/api") else url + "/api/v1"
    return url


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class _OpenAICompatible(LLMProvider):
    base_url: str | None = None
    api_key: str | None = None

    def _build_chat_model(self) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigError("langchain-openai not installed. Run: uv sync") from exc
        kwargs: dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "temperature": self.cfg.llm_temperature,
            "timeout": self.cfg.llm_timeout_seconds,
            "max_tokens": self.cfg.llm_max_output_tokens,
            "max_retries": 0,  # tenacity owns retries
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return ChatOpenAI(**kwargs)


class GitHubModelsProvider(_OpenAICompatible):
    name = "github"

    def __init__(self, token: str | None, model: str, base_url: str, **kw: Any):
        if not token:
            raise LLMConfigError(
                "GITHUB_TOKEN is not set. Create a fine-grained PAT with the 'Models' permission "
                "at https://github.com/settings/personal-access-tokens and put it in .env, or set "
                "LLM_PROVIDER=fake."
            )
        super().__init__(model, **kw)
        self.api_key = token
        self.base_url = resolve_openai_compatible_base(base_url)


class OpenAIProvider(_OpenAICompatible):
    name = "openai"

    def __init__(self, api_key: str | None, model: str, **kw: Any):
        if not api_key:
            raise LLMConfigError("OPENAI_API_KEY is not set.")
        super().__init__(model, **kw)
        self.api_key = api_key


class NvidiaProvider(_OpenAICompatible):
    name = "nvidia"

    def __init__(self, api_key: str | None, model: str, base_url: str, **kw: Any):
        if not api_key:
            raise LLMConfigError("NVIDIA_API_KEY is not set.")
        super().__init__(model, **kw)
        self.api_key = api_key
        self.base_url = base_url


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str, **kw: Any):
        if not api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set.")
        super().__init__(model, **kw)
        self.api_key = api_key

    def _build_chat_model(self) -> Any:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise LLMConfigError("Run: uv sync --extra anthropic") from exc
        return ChatAnthropic(
            api_key=self.api_key,
            model_name=self.model,
            temperature=self.cfg.llm_temperature,
            timeout=self.cfg.llm_timeout_seconds,
            max_tokens=self.cfg.llm_max_output_tokens,
            max_retries=0,
        )


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, **kw: Any):
        super().__init__(model, **kw)
        self.base_url = base_url

    def supports_vision(self) -> bool:
        return False

    def _build_chat_model(self) -> Any:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise LLMConfigError("Run: uv sync --extra ollama") from exc
        return ChatOllama(
            base_url=self.base_url,
            model=self.model,
            temperature=self.cfg.llm_temperature,
            num_predict=self.cfg.llm_max_output_tokens,
        )


class FakeProvider(LLMProvider):
    """Deterministic offline provider.

    Translation: returns the source wrapped in a marker so tests can assert it
    was "translated". Verification: scores 0.95 unless the translation contains
    the word FAIL (used to exercise the retry loop). Terminology: flags any
    source token wrapped in «guillemets», so tests can control flags precisely.
    Also used in demo mode when no API key is configured.
    """

    name = "fake"

    def __init__(self, **kw: Any):
        super().__init__("fake-1", **kw)
        self.calls: list[tuple[str, str]] = []
        self.fail_next: int = 0  # raise LLMError on the next N calls (tests)
        self.fail_on_node: dict[str, int] = {}  # {"verify": 1}: fail that node's next N calls

    def _build_chat_model(self) -> Any:  # pragma: no cover - never used
        raise NotImplementedError

    def supports_vision(self) -> bool:
        return False

    async def _fake(self, kind: str, prompt: str, ctx: CallContext) -> CallRecord:
        delay_ms = getattr(self.cfg, "fake_llm_delay_ms", 0)
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        self.calls.append((kind, prompt))
        record = CallRecord(
            node=ctx.node,
            provider=self.name,
            model=self.model,
            book_id=ctx.book_id,
            chunk_index=ctx.chunk_index,
            prompt_name=ctx.prompt_name,
            prompt_version=ctx.prompt_version,
            input_tokens=len(prompt) // 4,
            output_tokens=64,
            latency_ms=1,
        )
        node_failures = self.fail_on_node.get(ctx.node, 0)
        if node_failures > 0:
            self.fail_on_node[ctx.node] = node_failures - 1
        if self.fail_next > 0 or node_failures > 0:
            self.fail_next = max(0, self.fail_next - 1)
            record.status = "error"
            record.error = "fake failure"
            await self._record(record)
            raise LLMError("fake failure")
        await self._record(record)
        return record

    async def ainvoke_text(self, prompt: str, ctx: CallContext) -> str:
        await self._fake("text", prompt, ctx)
        return "fake response"

    async def ainvoke_structured(self, prompt: str, schema: type[T], ctx: CallContext) -> T:
        from app.agents.schemas import TerminologyOutput, TranslationOutput, VerificationOutput

        await self._fake(schema.__name__, prompt, ctx)
        target = _between(prompt, "## TARGET CHUNK (translate exactly this)", "## Context after")
        if schema is TranslationOutput:
            return schema.model_validate(
                {"translation": f"[fake-{ctx.prompt_version}] {target}", "notes": []}
            )
        if schema is VerificationOutput:
            translation = _between(prompt, "## Translation under review", None)
            bad = "FAIL" in translation
            return schema.model_validate(
                {
                    "score": 0.3 if bad else 0.95,
                    "summary": "fake: issues found" if bad else "fake: looks fine",
                    "suggestions": (
                        [
                            {
                                "issue": "contains FAIL",
                                "original_span": "FAIL",
                                "suggested": "PASS",
                                "severity": "high",
                            }
                        ]
                        if bad
                        else []
                    ),
                }
            )
        if schema is TerminologyOutput:
            source = _between(prompt, "## Source chunk", "## Translation")
            flags = [
                {
                    "term": t,
                    "suggested_translation": f"{t}-ar",
                    "category": "religious",
                    "show_in_brackets": True,
                    "rationale": "fake flag",
                }
                for t in re.findall(r"«([^»]+)»", source)
            ]
            return schema.model_validate({"flags": flags})
        return schema.model_validate({})

    async def ainvoke_vision(
        self, text: str, image_b64: str, ctx: CallContext, mime: str = "image/png"
    ) -> str:
        await self._fake("vision", text, ctx)
        return ""


def _between(text: str, start: str, end: str | None) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = text.find(end, i) if end else -1
    return (text[i:j] if j >= 0 else text[i:]).strip()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm_provider(
    cfg: Settings | None = None, *, recorder: Any = None, name: str | None = None
) -> LLMProvider:
    """Instantiate the configured provider. Raises LLMConfigError when the
    chosen provider lacks credentials (callers decide whether to fall back)."""
    cfg = cfg or settings
    provider = (name or cfg.llm_provider).lower().strip()
    kw = {"cfg": cfg, "recorder": recorder}
    if provider == "github":
        return GitHubModelsProvider(cfg.github_token, cfg.github_model, cfg.github_base_url, **kw)
    if provider == "openai":
        return OpenAIProvider(cfg.openai_api_key, cfg.openai_model, **kw)
    if provider == "anthropic":
        return AnthropicProvider(cfg.anthropic_api_key, cfg.anthropic_model, **kw)
    if provider == "nvidia":
        return NvidiaProvider(cfg.nvidia_api_key, cfg.nvidia_model, cfg.nvidia_base_url, **kw)
    if provider == "ollama":
        return OllamaProvider(cfg.ollama_base_url, cfg.ollama_model, **kw)
    if provider in ("fake", "mock"):
        return FakeProvider(**kw)
    raise LLMConfigError(f"Unknown LLM_PROVIDER {provider!r}")
