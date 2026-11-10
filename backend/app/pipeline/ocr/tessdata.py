"""Find and fetch Tesseract language packs (``*.traineddata``).

Resolution order for a *read-only* system directory:
``TESSDATA_PREFIX`` → common install paths (Windows, Debian, Homebrew).
Packs missing from the system are downloaded into a managed, writable
directory (``settings.tessdata_dir``, default ``backend/data/tessdata``) from
the official ``tesseract-ocr/tessdata_best`` repository, so a book in any
registry language can be OCRed without the user installing anything.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

REPOS = {
    "best": "https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata",
    "fast": "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata",
}

_SYSTEM_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tessdata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    "/usr/local/share/tessdata",
    "/opt/homebrew/share/tessdata",
)

# Downloads smaller than this are GitHub error pages, not models.
_MIN_PACK_BYTES = 100_000


def system_tessdata_dirs() -> list[Path]:
    """Existing directories that hold traineddata files, best first."""
    found: list[Path] = []
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        found.append(Path(prefix))
    found.extend(Path(p) for p in _SYSTEM_CANDIDATES)
    seen: list[Path] = []
    for directory in found:
        try:
            if directory.is_dir() and any(directory.glob("*.traineddata")):
                if directory not in seen:
                    seen.append(directory)
        except OSError:
            continue
    return seen


def installed_langs(directory: Path) -> set[str]:
    try:
        return {p.stem for p in directory.glob("*.traineddata")}
    except OSError:
        return set()


def all_installed_langs(managed_dir: Path) -> set[str]:
    langs: set[str] = set()
    for directory in [managed_dir, *system_tessdata_dirs()]:
        langs |= installed_langs(directory)
    return langs - {"osd"}


def download_pack(lang: str, dest_dir: Path, repo: str = "best", timeout: float = 120.0) -> Path:
    """Fetch one language pack. Raises on network failure or a bad payload."""
    url = REPOS.get(repo, REPOS["best"]).format(lang=lang)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{lang}.traineddata"
    tmp = target.with_suffix(".part")
    logger.info("downloading Tesseract pack %s from %s", lang, url)
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    if tmp.stat().st_size < _MIN_PACK_BYTES:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{lang}.traineddata download was too small to be a model")
    tmp.replace(target)
    return target


def ensure_packs(
    langs: list[str],
    managed_dir: Path,
    *,
    allow_download: bool = True,
    repo: str = "best",
) -> tuple[Path | None, list[str]]:
    """Return ``(tessdata_dir, usable_langs)`` for the requested packs.

    If a single system directory already has every pack, use it directly.
    Otherwise assemble the managed directory: copy packs the system has,
    download the rest. Languages that cannot be obtained are dropped (and
    reported) rather than failing the whole page; the caller decides whether
    the remainder is good enough.
    """
    wanted = [lang for lang in dict.fromkeys(langs) if lang]
    if not wanted:
        return None, []

    for directory in system_tessdata_dirs():
        if set(wanted) <= installed_langs(directory):
            return directory, wanted

    managed_dir.mkdir(parents=True, exist_ok=True)
    have = installed_langs(managed_dir)
    usable: list[str] = []
    for lang in wanted:
        if lang in have:
            usable.append(lang)
            continue
        copied = False
        for directory in system_tessdata_dirs():
            src = directory / f"{lang}.traineddata"
            if src.exists():
                shutil.copy2(src, managed_dir / src.name)
                copied = True
                break
        if copied:
            usable.append(lang)
            continue
        if not allow_download:
            logger.warning("Tesseract pack %s missing and downloads disabled", lang)
            continue
        try:
            download_pack(lang, managed_dir, repo=repo)
            usable.append(lang)
        except Exception as exc:  # network down, GitHub rate limit, ...
            logger.warning("could not fetch Tesseract pack %s: %s", lang, exc)

    # The OSD pack enables orientation/script detection; harmless if absent.
    if "osd" not in installed_langs(managed_dir):
        for directory in system_tessdata_dirs():
            src = directory / "osd.traineddata"
            if src.exists():
                shutil.copy2(src, managed_dir / src.name)
                break
    return (managed_dir if usable else None), usable
