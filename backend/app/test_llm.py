"""Test GitHub Models integration."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.llm.provider import GitHubModelsProvider, MockProvider
from app.core.config import settings


async def test_github_models():
    """Test GitHub Models provider."""
    print("=" * 60)
    print("TranslateBook AI — GitHub Models Integration Test")
    print("=" * 60)

    if not settings.github_token:
        print("\n⚠️  GITHUB_TOKEN not set in .env")
        print("\nTo use GitHub Models:")
        print("1. Go to: https://github.com/settings/personal-access-tokens")
        print("2. Click 'Generate new token (fine-grained)'")
        print("3. Select any scope (the token just needs to exist)")
        print("4. Copy the token and add to .env: GITHUB_TOKEN=github_pat_...")
        print("\nFor now, testing with Mock provider...")
        provider = MockProvider()
    else:
        print("\n✓ GITHUB_TOKEN found")
        provider = GitHubModelsProvider(settings.github_token)

    print(f"Provider: {provider.__class__.__name__}")
    print(f"Model: {getattr(provider, 'model', 'N/A')}")

    # Test translation
    print("\n" + "=" * 60)
    print("Testing Translation")
    print("=" * 60)

    prompt = """Translate this Urdu text to Arabic:

سلام علیکم
(Note: Only translate the Urdu text, not this instruction)

Return ONLY the Arabic translation."""

    try:
        print("\nSending prompt to provider...")
        result = await provider.ainvoke(prompt)
        translation = result.content if hasattr(result, 'content') else str(result)
        print(f"\n✓ Response received ({len(translation)} chars)")
        print(f"\nTranslation:\n{translation}")
        return True
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_github_models())
    sys.exit(0 if success else 1)
