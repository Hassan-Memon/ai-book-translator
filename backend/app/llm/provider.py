"""LLM provider factory and implementations.

Supported providers (set LLM_PROVIDER in .env):
  github     — GitHub Models (free tier, default)
  anthropic  — Anthropic Claude  (needs: uv sync --extra anthropic)
  openai     — OpenAI             (needs: OPENAI_API_KEY)
  ollama     — Local Ollama       (needs: uv sync --extra ollama + ollama running)
  fake       — Offline mock, used by tests / no-API dev
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------

class LLMProvider:
    """All providers expose a single async `ainvoke(prompt) -> response` method."""

    async def ainvoke(self, prompt: str) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# GitHub Models  (OpenAI-compatible endpoint, free tier)
# ---------------------------------------------------------------------------

class GitHubModelsProvider(LLMProvider):
    """GitHub Models provider — fine-grained PAT with 'Models' permission."""

    def __init__(self, token: str | None, model: str = "openai/gpt-4.1",
                 base_url: str = "https://models.github.ai/inference"):
        if not token:
            raise ValueError(
                "GITHUB_TOKEN is not set. "
                "Create a fine-grained PAT at https://github.com/settings/personal-access-tokens "
                "with the 'Models' permission, then add it to .env as GITHUB_TOKEN=<token>. "
                "Alternatively, set LLM_PROVIDER=fake to use a mock provider with no API key."
            )
        self.token = token
        self.model = model
        self.base_url = base_url

    async def ainvoke(self, prompt: str) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai not installed. Run: uv sync")

        client = ChatOpenAI(
            model=self.model,
            api_key=self.token,
            base_url=f"{self.base_url}/openai/",
            temperature=0.3,
        )
        return await client.ainvoke(prompt)


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """Anthropic Claude.  Requires: uv sync --extra anthropic"""

    def __init__(self, api_key: str | None, model: str = "claude-sonnet-5"):
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or switch LLM_PROVIDER."
            )
        self.api_key = api_key
        self.model = model

    async def ainvoke(self, prompt: str) -> Any:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain-anthropic not installed. Run: uv sync --extra anthropic"
            )

        client = ChatAnthropic(
            api_key=self.api_key,
            model_name=self.model,
            temperature=0.3,
        )
        return await client.ainvoke(prompt)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """OpenAI via langchain-openai."""

    def __init__(self, api_key: str | None, model: str = "gpt-4.1"):
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to .env or switch LLM_PROVIDER."
            )
        self.api_key = api_key
        self.model = model

    async def ainvoke(self, prompt: str) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai not installed. Run: uv sync")

        client = ChatOpenAI(api_key=self.api_key, model=self.model, temperature=0.3)
        return await client.ainvoke(prompt)


# ---------------------------------------------------------------------------
# Ollama  (fully local, zero API cost)
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    """Local Ollama. Requires: uv sync --extra ollama  +  ollama pull <model>"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b"):
        self.base_url = base_url
        self.model = model

    async def ainvoke(self, prompt: str) -> Any:
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama not installed. Run: uv sync --extra ollama"
            )

        client = ChatOllama(base_url=self.base_url, model=self.model, temperature=0.3)
        return await client.ainvoke(prompt)


# ---------------------------------------------------------------------------
# Mock / fake  (deterministic offline, no keys needed)
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Offline mock. Returns a placeholder so the pipeline can run without any API key."""

    async def ainvoke(self, prompt: str) -> Any:
        class _Resp:
            # Return a realistic-looking placeholder in Arabic so RTL rendering
            # tests in the UI can be exercised without real API calls.
            content = (
                "[ترجمة تجريبية] هذا نص تجريبي يُستخدم في بيئة التطوير. "
                "في الإنتاج سيتم استبداله بالترجمة الفعلية من نموذج اللغة."
            )

        logger.debug("MockProvider: returning placeholder translation")
        return _Resp()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_provider(provider: str, **kwargs) -> LLMProvider:
    """Instantiate the right provider from the name stored in settings.

    All keyword arguments come from Settings; unused ones are silently ignored
    so callers don't need to filter.
    """
    provider = provider.lower().strip()

    if provider == "github":
        return GitHubModelsProvider(
            token=kwargs.get("github_token"),
            model=kwargs.get("github_model", "openai/gpt-4.1"),
            base_url=kwargs.get("github_base_url", "https://models.github.ai/inference"),
        )
    if provider == "anthropic":
        return AnthropicProvider(
            api_key=kwargs.get("anthropic_api_key"),
            model=kwargs.get("anthropic_model", "claude-sonnet-5"),
        )
    if provider == "openai":
        return OpenAIProvider(
            api_key=kwargs.get("openai_api_key"),
            model=kwargs.get("openai_model", "gpt-4.1"),
        )
    if provider == "ollama":
        return OllamaProvider(
            base_url=kwargs.get("ollama_base_url", "http://localhost:11434"),
            model=kwargs.get("ollama_model", "qwen2.5:7b"),
        )
    if provider in ("fake", "mock"):
        return MockProvider()

    logger.warning(f"Unknown LLM_PROVIDER '{provider}', falling back to mock.")
    return MockProvider()


class NvidiaModelsProvider(LLMProvider):
    """NVIDIA NIM / integrate.api.nvidia.com provider — API key based."""

    def __init__(self, token: str | None, model: str = "meta/muse-glimmer-30b",
                 base_url: str = "https://integrate.api.nvidia.com/v1",
                 temperature: float = 1.0, top_p: float = 0.95,
                 max_tokens: int = 8192):
        if not token:
            raise ValueError(
                "NVIDIA_API_KEY is not set. "
                "Create an API key at https://build.nvidia.com and add it to .env as "
                "NVIDIA_API_KEY=<token>. "
                "Alternatively, set LLM_PROVIDER=fake to use a mock provider with no API key."
            )
        self.token = token
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

    async def ainvoke(self, prompt: str) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai not installed. Run: uv sync")

        client = ChatOpenAI(
            model=self.model,
            api_key=self.token,
            base_url=self.base_url,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
        )
        return await client.ainvoke(prompt)