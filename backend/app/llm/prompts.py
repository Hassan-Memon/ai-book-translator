"""Versioned prompt loader.

Prompts live in ``<repo>/prompts/<name>.md`` as markdown with a small YAML-ish
front-matter block (``name``, ``version``, ``description``). They are loaded
once, cached, and rendered with ``str.format``-style ``{placeholders}``. The
version is recorded on every ``llm_call`` row so eval results can be compared
per prompt version (ADR-0003).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_PLACEHOLDER = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")

LANGUAGE_NAMES = {
    "ur": "Urdu",
    "ar": "Arabic",
    "en": "English",
    "fa": "Persian",
    "tr": "Turkish",
}


class PromptError(RuntimeError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    description: str
    template: str

    @property
    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER.findall(self.template))

    def render(self, **values: object) -> str:
        missing = self.placeholders - set(values)
        if missing:
            raise PromptError(f"prompt {self.name!r} v{self.version}: missing {sorted(missing)}")
        text = self.template
        for key in self.placeholders:
            text = text.replace("{" + key + "}", str(values[key]))
        return text


def _parse_front_matter(raw: str, path: Path) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise PromptError(f"{path.name}: missing front-matter block")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, raw[match.end() :]


@lru_cache(maxsize=32)
def load_prompt(name: str, prompts_dir: Path | None = None) -> Prompt:
    directory = prompts_dir or settings.prompts_dir
    path = directory / f"{name}.md"
    if not path.exists():
        raise PromptError(f"prompt file not found: {path}")
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    try:
        version = int(meta.get("version", "1"))
    except ValueError as exc:
        raise PromptError(f"{path.name}: version must be an integer") from exc
    return Prompt(
        name=meta.get("name", name),
        version=version,
        description=meta.get("description", ""),
        template=body.strip() + "\n",
    )


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.lower(), code)


def format_glossary(glossary: dict[str, str] | list[dict[str, object]]) -> str:
    """Render glossary entries as a bullet list for prompts."""
    if not glossary:
        return "(no glossary entries yet)"
    lines: list[str] = []
    if isinstance(glossary, dict):
        for src, tgt in glossary.items():
            lines.append(f"- {src} → {tgt}")
    else:
        for entry in glossary:
            src = entry.get("original_term", "")
            tgt = entry.get("translation", "")
            suffix = (
                " (with_original_in_brackets)" if entry.get("with_original_in_brackets") else ""
            )
            lines.append(f"- {src} → {tgt}{suffix}")
    return "\n".join(lines)
