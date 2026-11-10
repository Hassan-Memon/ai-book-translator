"""Provider and model catalog: what the Settings screen offers and what the
agent strategy needs to know about a model (size tier, vision).

Two kinds of entries:

* ``PROVIDERS``: how to talk to each service. Most are OpenAI-compatible and
  differ only in base URL and key name; Anthropic and Ollama have their own
  clients. ``local`` providers run on the user's machine and cost nothing.
* ``LOCAL_RECOMMENDATIONS``: small models that run on a laptop and what they
  are good for, surfaced in the UI and in docs/LOCAL_MODELS.md.

Model *tiers* are inferred from the name (parameter count or known family),
so a user typing ``qwen3:4b`` automatically gets the small-model strategy
(sentence alignment, deterministic checks, tagged output) that makes a 4B
model behave.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    kind: str  # openai | anthropic | ollama | fake
    base_url: str | None = None
    key_env: str | None = None  # environment variable that holds the key
    needs_key: bool = True
    local: bool = False
    default_model: str = ""
    models: tuple[str, ...] = ()  # suggestions; any model id is accepted
    docs_url: str = ""
    key_url: str = ""
    note: str = ""
    # Some OpenAI-compatible hosts reject OpenAI's structured-output API.
    structured_output: bool = True
    custom_base_url: bool = False


PROVIDERS: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        ProviderSpec(
            id="ollama",
            label="Ollama (local)",
            kind="ollama",
            base_url="http://localhost:11434",
            needs_key=False,
            local=True,
            default_model="qwen3:8b",
            models=(
                "qwen3:8b",
                "qwen3:4b",
                "gemma3:12b",
                "gemma3:4b",
                "aya-expanse:8b",
                "llama3.1:8b",
            ),
            docs_url="https://ollama.com/download",
            note="Free, private, runs on your laptop. Install Ollama, then `ollama pull qwen3:8b`.",
            structured_output=False,
        ),
        ProviderSpec(
            id="lmstudio",
            label="LM Studio (local)",
            kind="openai",
            base_url="http://localhost:1234/v1",
            needs_key=False,
            local=True,
            default_model="",
            docs_url="https://lmstudio.ai/docs/app/api",
            note="Start the local server in LM Studio (Developer tab); models load from there.",
            structured_output=False,
        ),
        ProviderSpec(
            id="openai_compatible",
            label="Any OpenAI-compatible server",
            kind="openai",
            base_url="http://localhost:8080/v1",
            needs_key=False,
            local=True,
            default_model="",
            note="vLLM, llama.cpp server, LocalAI, Jan, text-generation-webui, a company gateway.",
            structured_output=False,
            custom_base_url=True,
        ),
        ProviderSpec(
            id="github",
            label="GitHub Models",
            kind="openai",
            base_url="https://models.github.ai/inference",
            key_env="GITHUB_TOKEN",
            default_model="openai/gpt-4.1",
            models=(
                "openai/gpt-4.1",
                "openai/gpt-4.1-mini",
                "openai/gpt-4o",
                "meta/Llama-4-Scout-17B-16E-Instruct",
            ),
            docs_url="https://docs.github.com/en/github-models",
            key_url="https://github.com/settings/personal-access-tokens",
            note="Free tier with rate limits. Fine-grained PAT with the 'Models' permission.",
        ),
        ProviderSpec(
            id="openai",
            label="OpenAI",
            kind="openai",
            key_env="OPENAI_API_KEY",
            default_model="gpt-4.1",
            models=("gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o", "gpt-4o-mini"),
            docs_url="https://platform.openai.com/docs",
            key_url="https://platform.openai.com/api-keys",
        ),
        ProviderSpec(
            id="anthropic",
            label="Anthropic",
            kind="anthropic",
            key_env="ANTHROPIC_API_KEY",
            default_model="claude-sonnet-5-5",
            models=("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
            docs_url="https://docs.anthropic.com",
            key_url="https://console.anthropic.com/settings/keys",
        ),
        ProviderSpec(
            id="gemini",
            label="Google Gemini",
            kind="openai",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            key_env="GEMINI_API_KEY",
            default_model="gemini-2.5-flash",
            models=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"),
            docs_url="https://ai.google.dev/gemini-api/docs/openai",
            key_url="https://aistudio.google.com/apikey",
            note="Free tier available via AI Studio.",
            structured_output=False,
        ),
        ProviderSpec(
            id="openrouter",
            label="OpenRouter",
            kind="openai",
            base_url="https://openrouter.ai/api/v1",
            key_env="OPENROUTER_API_KEY",
            default_model="google/gemini-2.5-flash",
            models=(
                "google/gemini-2.5-flash",
                "anthropic/claude-sonnet-4",
                "openai/gpt-4.1-mini",
                "qwen/qwen3-235b-a22b",
                "deepseek/deepseek-chat-v3-0324",
            ),
            docs_url="https://openrouter.ai/docs",
            key_url="https://openrouter.ai/keys",
            note="One key, hundreds of models, several free ones.",
            structured_output=False,
        ),
        ProviderSpec(
            id="groq",
            label="Groq",
            kind="openai",
            base_url="https://api.groq.com/openai/v1",
            key_env="GROQ_API_KEY",
            default_model="llama-3.3-70b-versatile",
            models=(
                "llama-3.3-70b-versatile",
                "qwen/qwen3-32b",
                "meta-llama/llama-4-scout-17b-16e-instruct",
            ),
            docs_url="https://console.groq.com/docs",
            key_url="https://console.groq.com/keys",
            note="Very fast inference, generous free tier.",
            structured_output=False,
        ),
        ProviderSpec(
            id="deepseek",
            label="DeepSeek",
            kind="openai",
            base_url="https://api.deepseek.com/v1",
            key_env="DEEPSEEK_API_KEY",
            default_model="deepseek-chat",
            models=("deepseek-chat", "deepseek-reasoner"),
            docs_url="https://api-docs.deepseek.com",
            key_url="https://platform.deepseek.com/api_keys",
            structured_output=False,
        ),
        ProviderSpec(
            id="mistral",
            label="Mistral",
            kind="openai",
            base_url="https://api.mistral.ai/v1",
            key_env="MISTRAL_API_KEY",
            default_model="mistral-large-latest",
            models=("mistral-large-latest", "mistral-small-latest", "pixtral-large-latest"),
            docs_url="https://docs.mistral.ai",
            key_url="https://console.mistral.ai/api-keys",
            structured_output=False,
        ),
        ProviderSpec(
            id="together",
            label="Together AI",
            kind="openai",
            base_url="https://api.together.xyz/v1",
            key_env="TOGETHER_API_KEY",
            default_model="Qwen/Qwen2.5-72B-Instruct-Turbo",
            models=("Qwen/Qwen2.5-72B-Instruct-Turbo", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
            docs_url="https://docs.together.ai",
            key_url="https://api.together.xyz/settings/api-keys",
            structured_output=False,
        ),
        ProviderSpec(
            id="nvidia",
            label="NVIDIA NIM",
            kind="openai",
            base_url="https://integrate.api.nvidia.com/v1",
            key_env="NVIDIA_API_KEY",
            default_model="meta/llama-3.3-70b-instruct",
            models=("meta/llama-3.3-70b-instruct", "qwen/qwen3-235b-a22b"),
            docs_url="https://build.nvidia.com",
            key_url="https://build.nvidia.com/settings/api-keys",
            structured_output=False,
        ),
        ProviderSpec(
            id="fake",
            label="Demo (no model)",
            kind="fake",
            needs_key=False,
            local=True,
            default_model="fake-1",
            note="Deterministic placeholder output so you can click through the product.",
        ),
    )
}


@dataclass(frozen=True)
class LocalModel:
    name: str  # Ollama tag
    params_b: float
    ram_gb: float  # approximate RAM to run comfortably on CPU
    vision: bool
    languages: str
    best_for: str
    tags: tuple[str, ...] = field(default_factory=tuple)


LOCAL_RECOMMENDATIONS: tuple[LocalModel, ...] = (
    LocalModel(
        "qwen3:8b",
        8,
        8,
        False,
        "119 languages incl. Arabic, Urdu, Persian, Hindi, Turkish",
        "Best all-round translator for a 16 GB laptop",
        ("recommended",),
    ),
    LocalModel(
        "qwen3:4b",
        4,
        5,
        False,
        "119 languages",
        "8 GB laptops; surprisingly strong with sentence alignment on",
        ("small",),
    ),
    LocalModel(
        "gemma3:12b",
        12,
        10,
        True,
        "140+ languages",
        "Highest quality that still fits 16 GB; also reads scanned pages (vision)",
        (),
    ),
    LocalModel(
        "gemma3:4b",
        4,
        5,
        True,
        "140+ languages",
        "Translation and vision OCR in one 3 GB download",
        ("small", "vision"),
    ),
    LocalModel(
        "aya-expanse:8b",
        8,
        8,
        False,
        "23 languages incl. Arabic, Persian, Hindi, Urdu-adjacent",
        "Cohere's multilingual model; excellent Arabic register",
        (),
    ),
    LocalModel(
        "llama3.1:8b",
        8,
        8,
        False,
        "8 official languages, decent on more",
        "Solid English-centric baseline",
        (),
    ),
    LocalModel(
        "phi4-mini",
        3.8,
        4,
        False,
        "Multilingual",
        "Fastest usable option on weak hardware",
        ("small",),
    ),
    LocalModel(
        "qwen2.5vl:7b",
        7,
        8,
        True,
        "Vision: Arabic, Urdu Nastaliq, CJK, Latin",
        "Best free OCR for scripts Tesseract struggles with (Nastaliq!)",
        ("vision",),
    ),
    LocalModel(
        "qwen2.5vl:3b",
        3,
        4,
        True,
        "Vision, multilingual",
        "Vision OCR on 8 GB machines",
        ("vision", "small"),
    ),
    LocalModel(
        "minicpm-v", 8, 8, True, "Vision, 30+ languages", "Strong document OCR", ("vision",)
    ),
    LocalModel(
        "llama3.2-vision:11b",
        11,
        10,
        True,
        "Vision",
        "Good page understanding, heavier",
        ("vision",),
    ),
)


_PARAMS = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)
_LARGE_FAMILIES = (
    "gpt-4.1",
    "gpt-4o",
    "gpt-5",
    "o3",
    "o4",
    "claude",
    "gemini-2.5-pro",
    "gemini-1.5-pro",
    "deepseek-chat",
    "deepseek-reasoner",
    "mistral-large",
    "pixtral-large",
    "command-a",
    "llama-3.3-70b",
    "llama-4",
    "qwen3-235b",
    "qwen2.5-72b",
    "qwen3-32b",
)
_MEDIUM_HINTS = ("mini", "flash", "lite", "haiku", "small", "nano", "scout", "turbo")
_VISION_HINTS = (
    "vl",
    "vision",
    "llava",
    "minicpm-v",
    "gemma3",
    "gemma-3",
    "pixtral",
    "gpt-4.1",
    "gpt-4o",
    "gpt-5",
    "claude",
    "gemini",
    "mistral-small-3",
    "mistral-small3",
    "granite3.2-vision",
    "moondream",
    "bakllava",
    "llama-4",
    "llama4",
    "qwen3-vl",
    "qwen2.5vl",
    "qwen2-vl",
)


def model_tier(model: str) -> str:
    """small (<= 4B) | medium (<= 14B or 'mini'-class API models) | large."""
    name = (model or "").lower()
    if not name or name.startswith("fake"):
        return "large"
    m = _PARAMS.search(name)
    if m:
        params = float(m.group(1))
        if params <= 4.5:
            return "small"
        if params <= 14.5:
            return "medium"
        return "large"
    if any(f in name for f in _LARGE_FAMILIES):
        if any(h in name for h in ("mini", "nano", "haiku", "flash-lite")):
            return "medium"
        return "large"
    if any(h in name for h in _MEDIUM_HINTS):
        return "medium"
    if any(h in name for h in ("phi", "tinyllama", "smollm", "qwen2.5:1", "gemma:2")):
        return "small"
    return "medium"


def model_supports_vision(model: str) -> bool:
    name = (model or "").lower()
    if "haiku-3" in name or name.startswith("o1"):
        return False
    return any(h in name for h in _VISION_HINTS)


def provider_spec(provider_id: str) -> ProviderSpec | None:
    return PROVIDERS.get((provider_id or "").lower().strip())


def serialize_providers() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for spec in PROVIDERS.values():
        out.append(
            {
                "id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "base_url": spec.base_url,
                "needs_key": spec.needs_key,
                "local": spec.local,
                "default_model": spec.default_model,
                "models": list(spec.models),
                "docs_url": spec.docs_url,
                "key_url": spec.key_url,
                "note": spec.note,
                "custom_base_url": spec.custom_base_url,
            }
        )
    return out


def serialize_local_recommendations() -> list[dict[str, object]]:
    return [
        {
            "name": m.name,
            "params_b": m.params_b,
            "ram_gb": m.ram_gb,
            "vision": m.vision,
            "languages": m.languages,
            "best_for": m.best_for,
            "tags": list(m.tags),
        }
        for m in LOCAL_RECOMMENDATIONS
    ]
