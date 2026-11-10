"""LLM provider layer.

One object, ``LLMProvider``, wraps a LangChain chat model and gives the rest
of the app four calls:

    await provider.ainvoke_text(prompt, ctx)                 -> str
    await provider.ainvoke_tagged(prompt, tags, ctx)         -> dict[tag, str]
    await provider.ainvoke_structured(prompt, Schema, ctx)   -> Schema
    await provider.ainvoke_vision(text, image_b64, ctx)      -> str

All apply timeouts, retries with exponential backoff on retryable errors,
and record one ``llm_call`` row per invocation (tokens, cost, latency,
prompt version).

Structured calls are built to survive small local models: native structured
output where the host supports it, JSON mode on Ollama, and otherwise "ask
for JSON" followed by a repair step (fences, <think> blocks, trailing commas,
smart quotes, a sentence before the object). A response that still fails
validation raises ``LLMOutputError`` (ADR-0005: parse failures are errors,
not empty results).

Providers come from :mod:`app.llm.catalog`; credentials come from the
environment or from the Settings screen (:mod:`app.services.settings`).
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
from app.llm.catalog import PROVIDERS, ProviderSpec, model_supports_vision, provider_spec
from app.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"'})


class LLMError(RuntimeError):
    """Base class for provider failures."""


class LLMOutputError(LLMError):
    """The model answered but the answer could not be parsed into the schema."""


class LLMConfigError(LLMError):
    """Provider is not configured (missing key / package / server)."""


@dataclass
class RuntimeLlm:
    """Effective provider configuration (env defaults merged with UI settings)."""

    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    vision_model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    source: str = "env"  # env | ui

    @property
    def spec(self) -> ProviderSpec | None:
        return provider_spec(self.provider)

    @property
    def is_local(self) -> bool:
        spec = self.spec
        if spec and spec.local:
            return True
        url = (self.base_url or "").lower()
        return "localhost" in url or "127.0.0.1" in url or "0.0.0.0" in url

    def fingerprint(self) -> str:
        return json.dumps(
            [
                self.provider,
                self.model,
                bool(self.api_key),
                (self.api_key or "")[-4:],
                self.base_url,
                self.vision_model,
                self.temperature,
                self.max_output_tokens,
            ]
        )


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


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> reasoning that qwen3/deepseek-r1 style models
    emit before the answer."""
    return _THINK.sub("", text or "").strip()


def _strip_fences(text: str) -> str:
    text = strip_thinking(text)
    text = _FENCE.sub("", text).strip()
    # Some models prepend a sentence before the JSON object; keep the outermost braces.
    if not text.startswith(("{", "[")):
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return text


def repair_json(text: str) -> str:
    """Best-effort repair of almost-JSON from small models."""
    candidate = _strip_fences(text)
    candidate = candidate.translate(_SMART_QUOTES)
    candidate = _TRAILING_COMMA.sub(r"\1", candidate)
    candidate = re.sub(r"\bTrue\b", "true", candidate)
    candidate = re.sub(r"\bFalse\b", "false", candidate)
    candidate = re.sub(r"\bNone\b", "null", candidate)
    # Unescaped newlines inside strings: JSON forbids them; replace with \n
    # only when we are inside quotes.
    out: list[str] = []
    in_str = False
    escape = False
    for ch in candidate:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            elif ch == "\n":
                out.append("\\n")
                continue
            elif ch == "\t":
                out.append("\\t")
                continue
        elif ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def parse_tagged(text: str, tags: list[str]) -> dict[str, str]:
    """Extract ``<tag>...</tag>`` blocks; tolerant of a missing closing tag on
    the last block and of tags written in upper case."""
    cleaned = strip_thinking(text)
    found: dict[str, str] = {}
    for tag in tags:
        m = re.search(rf"<{tag}>\s*(.*?)\s*(?:</{tag}>|$)", cleaned, re.DOTALL | re.IGNORECASE)
        if m:
            found[tag] = m.group(1).strip()
    return found


def _usage(response: Any) -> tuple[int, int]:
    meta = getattr(response, "usage_metadata", None) or {}
    if meta:
        return int(meta.get("input_tokens", 0) or 0), int(meta.get("output_tokens", 0) or 0)
    rm = getattr(response, "response_metadata", None) or {}
    usage = rm.get("token_usage") or rm.get("usage") or {}
    return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


def _content_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


class LLMProvider:
    """Thin, testable façade over a LangChain chat model."""

    name: str = "base"
    supports_structured: bool = True
    is_local: bool = False

    def __init__(
        self,
        model: str,
        *,
        cfg: Settings | None = None,
        recorder: Any = None,
        runtime: RuntimeLlm | None = None,
    ):
        self.model = model
        self.cfg = cfg or settings
        self.recorder = recorder  # async callable(CallRecord) -> None, or None
        self.runtime = runtime
        self.vision_model_name: str | None = runtime.vision_model if runtime else None
        self._chat: Any = None
        self._json_chat: Any = None
        self._vision_chat: Any = None

    # -- subclasses provide the LangChain model ------------------------------
    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        raise NotImplementedError  # pragma: no cover - abstract

    @property
    def temperature(self) -> float:
        if self.runtime and self.runtime.temperature is not None:
            return float(self.runtime.temperature)
        return self.cfg.llm_temperature

    @property
    def max_output_tokens(self) -> int:
        if self.runtime and self.runtime.max_output_tokens:
            return int(self.runtime.max_output_tokens)
        return self.cfg.llm_max_output_tokens

    @property
    def chat_model(self) -> Any:
        if self._chat is None:
            self._chat = self._build_chat_model()
        return self._chat

    @property
    def json_chat_model(self) -> Any:
        """Model variant that constrains output to JSON when the host can."""
        return self.chat_model

    @property
    def vision_chat_model(self) -> Any:
        """The model used for images: the configured vision model if any,
        else the chat model."""
        if self.vision_model_name and self.vision_model_name != self.model:
            if self._vision_chat is None:
                self._vision_chat = self._build_chat_model(model=self.vision_model_name)
            return self._vision_chat
        return self.chat_model

    def supports_vision(self) -> bool:
        return model_supports_vision(self.vision_model_name or self.model)

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "vision_model": self.vision_model_name,
            "supports_vision": self.supports_vision(),
            "is_local": self.is_local,
        }

    # -- public API -----------------------------------------------------------
    async def ainvoke_text(self, prompt: str, ctx: CallContext) -> str:
        response, record = await self._invoke(lambda m: m.ainvoke(prompt), ctx)
        await self._record(record)
        return strip_thinking(_content_text(response))

    async def ainvoke_tagged(
        self, prompt: str, tags: list[str], ctx: CallContext
    ) -> dict[str, str]:
        """Ask for ``<tag>`` blocks; the most robust format for long free text
        from small models. Raises LLMOutputError if the first tag is missing."""
        response, record = await self._invoke(lambda m: m.ainvoke(prompt), ctx)
        text = _content_text(response)
        found = parse_tagged(text, tags)
        if tags and tags[0] not in found:
            # Last resort: treat the whole answer as the primary tag's content.
            body = strip_thinking(text).strip()
            if body:
                found[tags[0]] = body
                record.extra["untagged"] = True
            else:
                record.status = "parse_error"
                await self._record(record)
                raise LLMOutputError(f"expected <{tags[0]}> in the answer; got {text[:200]!r}")
        await self._record(record)
        return found

    async def ainvoke_structured(self, prompt: str, schema: type[T], ctx: CallContext) -> T:
        record: CallRecord | None = None
        if self.supports_structured:
            try:
                structured = self.chat_model.with_structured_output(schema, include_raw=True)
                raw, record = await self._invoke(lambda _m: structured.ainvoke(prompt), ctx)
                parsed = raw.get("parsed") if isinstance(raw, dict) else None
                if isinstance(parsed, schema):
                    await self._record(record)
                    return parsed
                raw_msg = raw.get("raw") if isinstance(raw, dict) else None
                text = _content_text(raw_msg) if raw_msg is not None else ""
                result = self._parse_json(text, schema)
                await self._record(record)
                return result
            except LLMOutputError:
                if record:
                    record.status = "parse_error"
                    await self._record(record)
                raise
            except (NotImplementedError, AttributeError, TypeError, ValueError) as exc:
                logger.debug(
                    "structured output unsupported for %s (%s); using JSON mode", self.model, exc
                )
            except LLMError as exc:
                # Hosts that reject response_format/tools: fall back to JSON mode once.
                if "response_format" in str(exc) or "tool" in str(exc).lower():
                    logger.info("%s rejected structured output; using JSON mode", self.name)
                else:
                    raise
        json_prompt = (
            f"{prompt}\n\nRespond with a single JSON object matching this JSON schema and "
            f"nothing else (no markdown, no explanation):\n{json.dumps(schema.model_json_schema())}"
        )
        response, record = await self._invoke(
            lambda _m: self.json_chat_model.ainvoke(json_prompt), ctx
        )
        try:
            result = self._parse_json(_content_text(response), schema)
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
        response, record = await self._invoke(
            lambda _m: self.vision_chat_model.ainvoke([message]), ctx
        )
        record.model = self.vision_model_name or self.model
        await self._record(record)
        return strip_thinking(_content_text(response))

    async def aping(self) -> str:
        """Tiny call used by the Settings screen's 'Test connection'."""
        ctx = CallContext(node="ping")
        answer = await self.ainvoke_text("Reply with exactly the word OK.", ctx)
        return answer.strip()[:40]

    # -- internals ------------------------------------------------------------
    @staticmethod
    def _parse_json(text: str, schema: type[T]) -> T:
        candidate = _strip_fences(text or "")
        try:
            return schema.model_validate_json(candidate)
        except ValidationError:
            pass
        repaired = repair_json(text or "")
        try:
            return schema.model_validate_json(repaired)
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
        if self.is_local:
            record.cost_usd = 0.0
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
    if "generativelanguage.googleapis.com" in url and not url.endswith("/openai"):
        return url + "/openai/"
    return url


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI, GitHub Models, OpenRouter, Groq, Gemini, DeepSeek, Mistral,
    Together, NVIDIA, LM Studio, vLLM, llama.cpp server, ..."""

    def __init__(
        self,
        spec: ProviderSpec,
        api_key: str | None,
        model: str,
        base_url: str | None,
        **kw: Any,
    ):
        if spec.needs_key and not api_key:
            hint = f" Get one at {spec.key_url}." if spec.key_url else ""
            env = f" (or set {spec.key_env} in .env)" if spec.key_env else ""
            raise LLMConfigError(f"{spec.label} needs an API key. Add it in Settings{env}.{hint}")
        if not model:
            raise LLMConfigError(f"{spec.label}: choose a model in Settings.")
        super().__init__(model, **kw)
        self.name = spec.id
        self.spec = spec
        self.api_key = api_key or "not-needed"
        self.base_url = resolve_openai_compatible_base(base_url or spec.base_url or "") or None
        self.supports_structured = spec.structured_output
        self.is_local = spec.local or (
            self.base_url is not None
            and any(h in self.base_url for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        )

    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigError("langchain-openai not installed. Run: uv sync") from exc
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "timeout": self.cfg.llm_timeout_seconds,
            "max_tokens": self.max_output_tokens,
            "max_retries": 0,  # tenacity owns retries
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        kwargs.update(overrides)
        return ChatOpenAI(**kwargs)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str, **kw: Any):
        if not api_key:
            raise LLMConfigError(
                "Anthropic needs an API key. Add it in Settings (or ANTHROPIC_API_KEY in .env)."
            )
        super().__init__(model or "claude-sonnet-5-5", **kw)
        self.api_key = api_key

    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise LLMConfigError("langchain-anthropic not installed. Run: uv sync") from exc
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "model_name": model or self.model,
            "temperature": self.temperature,
            "timeout": self.cfg.llm_timeout_seconds,
            "max_tokens": self.max_output_tokens,
            "max_retries": 0,
        }
        kwargs.update(overrides)
        return ChatAnthropic(**kwargs)


class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_structured = False
    is_local = True

    def __init__(self, base_url: str | None, model: str, **kw: Any):
        if not model:
            raise LLMConfigError(
                "Ollama: choose a model in Settings (for example `ollama pull qwen3:8b`)."
            )
        super().__init__(model, **kw)
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self._capabilities: dict[str, set[str]] = {}

    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise LLMConfigError("langchain-ollama not installed. Run: uv sync") from exc
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "model": model or self.model,
            "temperature": self.temperature,
            "num_predict": self.max_output_tokens,
            # Long chunks + context + glossary need more than Ollama's 2k default.
            "num_ctx": 8192,
        }
        kwargs.update(overrides)
        return ChatOllama(**kwargs)

    @property
    def json_chat_model(self) -> Any:
        if self._json_chat is None:
            self._json_chat = self._build_chat_model(format="json")
        return self._json_chat

    def _model_capabilities(self, model: str) -> set[str]:
        """Ask Ollama what the model can do (``/api/show`` lists 'vision')."""
        if model in self._capabilities:
            return self._capabilities[model]
        caps: set[str] = set()
        try:
            import httpx

            r = httpx.post(f"{self.base_url}/api/show", json={"model": model}, timeout=5.0)
            if r.status_code == 200:
                caps = set(r.json().get("capabilities") or [])
        except Exception as exc:  # server down or old version
            logger.debug("ollama show failed: %s", exc)
        self._capabilities[model] = caps
        return caps

    def supports_vision(self) -> bool:
        model = self.vision_model_name or self.model
        caps = self._model_capabilities(model)
        if caps:
            return "vision" in caps
        return model_supports_vision(model)


class FakeProvider(LLMProvider):
    """Deterministic offline provider.

    Translation: returns the source wrapped in a marker so tests can assert it
    was "translated". Verification: scores 0.95 unless the translation contains
    the word FAIL (used to exercise the retry loop). Terminology: flags any
    source token wrapped in «guillemets», so tests can control flags precisely.
    Also used in demo mode when no API key is configured.
    """

    name = "fake"
    is_local = True

    def __init__(self, **kw: Any):
        super().__init__("fake-1", **kw)
        self.calls: list[tuple[str, str]] = []
        self.fail_next: int = 0  # raise LLMError on the next N calls (tests)
        self.fail_on_node: dict[str, int] = {}  # {"verify": 1}: fail that node's next N calls

    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        raise NotImplementedError  # pragma: no cover - never used

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
        if ctx.node == "ping":
            return "OK"
        if ctx.node == "ocr_cleanup":
            return _between(prompt, "## OCR text", "## Output") or "fake response"
        if ctx.node == "polish":
            return _between(prompt, "## Translation to polish", "## Output") or "fake response"
        return "fake response"

    async def ainvoke_tagged(
        self, prompt: str, tags: list[str], ctx: CallContext
    ) -> dict[str, str]:
        await self._fake("tagged", prompt, ctx)
        target = _between(prompt, "## TARGET CHUNK (translate exactly this)", "## Context after")
        if "[1]" in target and "sentence" in prompt.lower():
            # Sentence-aligned mode: echo the numbered sentences back, translated.
            lines = [
                f"[fake-{ctx.prompt_version}] {ln}" if not ln.startswith("[") else ln
                for ln in target.splitlines()
            ]
            body = "\n".join(lines)
        else:
            body = f"[fake-{ctx.prompt_version}] {target}"
        return {tags[0]: body, **{t: "" for t in tags[1:]}}

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


def _env_values() -> dict[str, str]:
    """Process environment layered over the .env files. pydantic-settings reads
    .env for declared fields only, so keys of catalog-only providers
    (GEMINI_API_KEY, OPENROUTER_API_KEY, ...) are looked up here."""
    import os

    from dotenv import dotenv_values

    from app.core.config import BACKEND_DIR, REPO_ROOT

    merged: dict[str, str] = {}
    for path in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
        if path.exists():
            merged.update({k: v for k, v in dotenv_values(path).items() if v})
    merged.update({k: v for k, v in os.environ.items() if v})
    return merged


def runtime_from_settings(cfg: Settings | None = None) -> RuntimeLlm:
    """The provider configuration implied by .env alone."""
    cfg = cfg or settings
    provider = (cfg.llm_provider or "fake").lower().strip()
    spec = provider_spec(provider)
    key: str | None = None
    model = ""
    base_url: str | None = None
    if provider == "github":
        key, model, base_url = cfg.github_token, cfg.github_model, cfg.github_base_url
    elif provider == "openai":
        key, model = cfg.openai_api_key, cfg.openai_model
    elif provider == "anthropic":
        key, model = cfg.anthropic_api_key, cfg.anthropic_model
    elif provider == "nvidia":
        key, model, base_url = cfg.nvidia_api_key, cfg.nvidia_model, cfg.nvidia_base_url
    elif provider == "ollama":
        model, base_url = cfg.ollama_model, cfg.ollama_base_url
    elif provider == "lmstudio":
        model, base_url = cfg.lmstudio_model, cfg.lmstudio_base_url
    elif provider == "openai_compatible":
        key, model, base_url = (
            cfg.openai_compatible_api_key,
            cfg.openai_compatible_model,
            cfg.openai_compatible_base_url,
        )
    elif spec is not None:
        env = _env_values()
        key = env.get(spec.key_env or "") if spec.key_env else None
        model = env.get(f"{spec.id.upper()}_MODEL") or spec.default_model
    return RuntimeLlm(
        provider=provider,
        model=model or (spec.default_model if spec else ""),
        api_key=key or None,
        base_url=base_url,
        vision_model=cfg.vision_model,
        source="env",
    )


def build_provider(
    runtime: RuntimeLlm, *, cfg: Settings | None = None, recorder: Any = None
) -> LLMProvider:
    """Instantiate a provider from an explicit runtime configuration. Raises
    LLMConfigError when it lacks credentials (callers decide whether to fall back)."""
    cfg = cfg or settings
    kw = {"cfg": cfg, "recorder": recorder, "runtime": runtime}
    provider = (runtime.provider or "").lower().strip()
    spec = provider_spec(provider)
    if spec is None:
        known = ", ".join(sorted(PROVIDERS))
        raise LLMConfigError(f"Unknown LLM provider {provider!r}. Known: {known}")
    if spec.kind == "fake":
        return FakeProvider(**kw)
    if spec.kind == "anthropic":
        return AnthropicProvider(runtime.api_key, runtime.model, **kw)
    if spec.kind == "ollama":
        return OllamaProvider(runtime.base_url, runtime.model, **kw)
    return OpenAICompatibleProvider(
        spec, runtime.api_key, runtime.model or spec.default_model, runtime.base_url, **kw
    )


def get_llm_provider(
    cfg: Settings | None = None, *, recorder: Any = None, name: str | None = None
) -> LLMProvider:
    """Instantiate the provider configured in .env (no UI overrides). Kept for
    the CLI, tests and backwards compatibility; the app uses
    ``app.jobs.handlers.get_provider`` which also honours UI settings."""
    cfg = cfg or settings
    runtime = runtime_from_settings(cfg)
    if name:
        runtime.provider = name.lower().strip()
        spec = provider_spec(runtime.provider)
        if spec and runtime.provider != (cfg.llm_provider or "").lower():
            runtime.model = spec.default_model
    return build_provider(runtime, cfg=cfg, recorder=recorder)
