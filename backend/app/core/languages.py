"""The language registry: one table that every layer reads.

Each entry says how a language is written (script, direction), which
Tesseract pack reads it, which font renders it well, and how its sentences end.
The API exposes it at ``GET /api/v1/languages`` so the UI never hard-codes a
language list, the DOCX exporter picks fonts from it, the OCR ladder picks
``traineddata`` packs from it, and the prompts use its display names.

Adding a language is one line here. Nothing else needs to change.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Language:
    code: str  # ISO 639-1 (or 639-3 when no 2-letter code exists)
    name: str  # English name
    native: str  # name in the language itself
    script: str  # Unicode script name used for font + validity checks
    rtl: bool = False
    tesseract: tuple[str, ...] = ()  # traineddata pack(s), in priority order
    font: str = "Noto Serif"  # UI + DOCX font family (Google Fonts name)
    font_scale: float = 1.0  # relative size boost for dense scripts
    line_height: float = 1.7
    # Sentence terminators specific to the script (added to the universal set).
    terminators: tuple[str, ...] = field(default_factory=tuple)
    # Characters that appear in this language but not in sibling languages of
    # the same script (used to tell Urdu from Arabic, Persian from Arabic, ...).
    markers: str = ""
    # Does the language use spaces between words? (affects length-ratio checks)
    spaced: bool = True


# Universal sentence terminators across scripts.
UNIVERSAL_TERMINATORS = (".", "!", "?", "…", "۔", "؟", "।", "॥", "。", "！", "？", "።")

_ARABIC = dict(
    script="Arabic", rtl=True, font="Noto Naskh Arabic", font_scale=1.15, line_height=2.0
)
_DEVANAGARI = dict(
    script="Devanagari", font="Noto Sans Devanagari", font_scale=1.05, line_height=1.9
)

LANGUAGES: tuple[Language, ...] = (
    # --- Arabic script -------------------------------------------------------
    Language("ar", "Arabic", "العربية", tesseract=("ara",), terminators=("؟", "۔"), **_ARABIC),
    Language(
        "ur",
        "Urdu",
        "اردو",
        script="Arabic",
        rtl=True,
        tesseract=("urd", "ara"),
        font="Noto Nastaliq Urdu",
        font_scale=1.1,
        line_height=2.4,
        terminators=("۔", "؟"),
        markers="ٹڈڑںےہھۃۓکگچپژ",
    ),
    Language(
        "fa",
        "Persian",
        "فارسی",
        tesseract=("fas", "ara"),
        terminators=("؟", "۔"),
        markers="گچپژکی",
        **_ARABIC,
    ),
    Language("ps", "Pashto", "پښتو", tesseract=("pus", "fas"), markers="ښځڼټډړۀې", **_ARABIC),
    Language("sd", "Sindhi", "سنڌي", tesseract=("snd", "urd"), markers="ڄڃڇڏڙڻڳ", **_ARABIC),
    Language("ug", "Uyghur", "ئۇيغۇرچە", tesseract=("uig", "ara"), markers="ۇۈۆېھ", **_ARABIC),
    Language("ku", "Kurdish (Sorani)", "کوردی", tesseract=("kur_ara", "ara"), **_ARABIC),
    # --- other RTL -----------------------------------------------------------
    Language(
        "he",
        "Hebrew",
        "עברית",
        script="Hebrew",
        rtl=True,
        tesseract=("heb",),
        font="Noto Serif Hebrew",
        line_height=1.8,
    ),
    # --- Latin ---------------------------------------------------------------
    Language("en", "English", "English", script="Latin", tesseract=("eng",)),
    Language("fr", "French", "Français", script="Latin", tesseract=("fra",)),
    Language("de", "German", "Deutsch", script="Latin", tesseract=("deu",)),
    Language("es", "Spanish", "Español", script="Latin", tesseract=("spa",)),
    Language("pt", "Portuguese", "Português", script="Latin", tesseract=("por",)),
    Language("it", "Italian", "Italiano", script="Latin", tesseract=("ita",)),
    Language("nl", "Dutch", "Nederlands", script="Latin", tesseract=("nld",)),
    Language("tr", "Turkish", "Türkçe", script="Latin", tesseract=("tur",)),
    Language("id", "Indonesian", "Bahasa Indonesia", script="Latin", tesseract=("ind",)),
    Language("ms", "Malay", "Bahasa Melayu", script="Latin", tesseract=("msa",)),
    Language("sw", "Swahili", "Kiswahili", script="Latin", tesseract=("swa",)),
    Language("pl", "Polish", "Polski", script="Latin", tesseract=("pol",)),
    Language("vi", "Vietnamese", "Tiếng Việt", script="Latin", tesseract=("vie",)),
    Language("so", "Somali", "Soomaali", script="Latin", tesseract=("eng",)),
    Language("ha", "Hausa", "Hausa", script="Latin", tesseract=("eng",)),
    Language("uz", "Uzbek", "Oʻzbekcha", script="Latin", tesseract=("uzb",)),
    Language("az", "Azerbaijani", "Azərbaycanca", script="Latin", tesseract=("aze",)),
    # --- Cyrillic / Greek ----------------------------------------------------
    Language("ru", "Russian", "Русский", script="Cyrillic", tesseract=("rus",)),
    Language("uk", "Ukrainian", "Українська", script="Cyrillic", tesseract=("ukr",)),
    Language("kk", "Kazakh", "Қазақша", script="Cyrillic", tesseract=("kaz",)),
    Language("el", "Greek", "Ελληνικά", script="Greek", tesseract=("ell",)),
    # --- South Asian ---------------------------------------------------------
    Language("hi", "Hindi", "हिन्दी", tesseract=("hin",), terminators=("।",), **_DEVANAGARI),
    Language("mr", "Marathi", "मराठी", tesseract=("mar",), terminators=("।",), **_DEVANAGARI),
    Language("ne", "Nepali", "नेपाली", tesseract=("nep",), terminators=("।",), **_DEVANAGARI),
    Language("sa", "Sanskrit", "संस्कृतम्", tesseract=("san",), terminators=("।", "॥"), **_DEVANAGARI),
    Language(
        "bn",
        "Bengali",
        "বাংলা",
        script="Bengali",
        tesseract=("ben",),
        font="Noto Sans Bengali",
        font_scale=1.05,
        line_height=1.9,
        terminators=("।",),
    ),
    Language(
        "pa",
        "Punjabi (Gurmukhi)",
        "ਪੰਜਾਬੀ",
        script="Gurmukhi",
        tesseract=("pan",),
        font="Noto Sans Gurmukhi",
        line_height=1.9,
        terminators=("।",),
    ),
    Language(
        "gu",
        "Gujarati",
        "ગુજરાતી",
        script="Gujarati",
        tesseract=("guj",),
        font="Noto Sans Gujarati",
        line_height=1.9,
    ),
    Language(
        "ta",
        "Tamil",
        "தமிழ்",
        script="Tamil",
        tesseract=("tam",),
        font="Noto Sans Tamil",
        line_height=1.9,
    ),
    Language(
        "te",
        "Telugu",
        "తెలుగు",
        script="Telugu",
        tesseract=("tel",),
        font="Noto Sans Telugu",
        line_height=1.9,
    ),
    Language(
        "kn",
        "Kannada",
        "ಕನ್ನಡ",
        script="Kannada",
        tesseract=("kan",),
        font="Noto Sans Kannada",
        line_height=1.9,
    ),
    Language(
        "ml",
        "Malayalam",
        "മലയാളം",
        script="Malayalam",
        tesseract=("mal",),
        font="Noto Sans Malayalam",
        line_height=1.9,
    ),
    Language(
        "si",
        "Sinhala",
        "සිංහල",
        script="Sinhala",
        tesseract=("sin",),
        font="Noto Sans Sinhala",
        line_height=1.9,
    ),
    # --- East / Southeast Asian ---------------------------------------------
    Language(
        "zh",
        "Chinese (Simplified)",
        "简体中文",
        script="Han",
        tesseract=("chi_sim",),
        font="Noto Sans SC",
        terminators=("。", "！", "？"),
        spaced=False,
    ),
    Language(
        "zh-TW",
        "Chinese (Traditional)",
        "繁體中文",
        script="Han",
        tesseract=("chi_tra",),
        font="Noto Sans TC",
        terminators=("。", "！", "？"),
        spaced=False,
    ),
    Language(
        "ja",
        "Japanese",
        "日本語",
        script="Japanese",
        tesseract=("jpn",),
        font="Noto Sans JP",
        terminators=("。", "！", "？"),
        spaced=False,
    ),
    Language("ko", "Korean", "한국어", script="Hangul", tesseract=("kor",), font="Noto Sans KR"),
    Language(
        "th", "Thai", "ไทย", script="Thai", tesseract=("tha",), font="Noto Sans Thai", spaced=False
    ),
    Language(
        "my",
        "Burmese",
        "မြန်မာ",
        script="Myanmar",
        tesseract=("mya",),
        font="Noto Sans Myanmar",
        spaced=False,
    ),
    Language(
        "km",
        "Khmer",
        "ខ្មែរ",
        script="Khmer",
        tesseract=("khm",),
        font="Noto Sans Khmer",
        spaced=False,
    ),
    # --- African / other -----------------------------------------------------
    Language(
        "am",
        "Amharic",
        "አማርኛ",
        script="Ethiopic",
        tesseract=("amh",),
        font="Noto Sans Ethiopic",
        terminators=("።",),
    ),
    Language(
        "hy",
        "Armenian",
        "Հայերեն",
        script="Armenian",
        tesseract=("hye",),
        font="Noto Sans Armenian",
    ),
    Language(
        "ka",
        "Georgian",
        "ქართული",
        script="Georgian",
        tesseract=("kat",),
        font="Noto Sans Georgian",
    ),
)

_BY_CODE: dict[str, Language] = {lang.code.lower(): lang for lang in LANGUAGES}

# Unicode block ranges per script (letters only; punctuation and digits are
# script-neutral and never count against validity).
SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "Arabic": (
        (0x0600, 0x06FF),
        (0x0750, 0x077F),
        (0x08A0, 0x08FF),
        (0xFB50, 0xFDFF),
        (0xFE70, 0xFEFF),
    ),
    "Hebrew": ((0x0590, 0x05FF),),
    "Latin": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF)),
    "Cyrillic": ((0x0400, 0x04FF), (0x0500, 0x052F)),
    "Greek": ((0x0370, 0x03FF), (0x1F00, 0x1FFF)),
    "Devanagari": ((0x0900, 0x097F),),
    "Bengali": ((0x0980, 0x09FF),),
    "Gurmukhi": ((0x0A00, 0x0A7F),),
    "Gujarati": ((0x0A80, 0x0AFF),),
    "Tamil": ((0x0B80, 0x0BFF),),
    "Telugu": ((0x0C00, 0x0C7F),),
    "Kannada": ((0x0C80, 0x0CFF),),
    "Malayalam": ((0x0D00, 0x0D7F),),
    "Sinhala": ((0x0D80, 0x0DFF),),
    "Thai": ((0x0E00, 0x0E7F),),
    "Myanmar": ((0x1000, 0x109F),),
    "Khmer": ((0x1780, 0x17FF),),
    "Han": ((0x4E00, 0x9FFF), (0x3400, 0x4DBF)),
    "Japanese": ((0x3040, 0x30FF),),
    "Hangul": ((0xAC00, 0xD7AF), (0x1100, 0x11FF)),
    "Ethiopic": ((0x1200, 0x137F),),
    "Armenian": ((0x0530, 0x058F),),
    "Georgian": ((0x10A0, 0x10FF),),
}


def get_language(code: str) -> Language | None:
    """Look a language up by code; tolerant of case and region suffixes."""
    if not code:
        return None
    key = code.strip()
    lang = _BY_CODE.get(key.lower())
    if lang is None and "-" in key:
        lang = _BY_CODE.get(key.split("-", 1)[0].lower())
    if lang is None and "_" in key:
        lang = _BY_CODE.get(key.split("_", 1)[0].lower())
    return lang


def language_name(code: str) -> str:
    lang = get_language(code)
    return lang.name if lang else code


def is_rtl(code: str) -> bool:
    lang = get_language(code)
    return bool(lang and lang.rtl)


def font_for(code: str) -> str:
    lang = get_language(code)
    return lang.font if lang else "Noto Serif"


def tesseract_langs(code: str) -> list[str]:
    """Tesseract packs for a language, most specific first. Unknown -> eng."""
    lang = get_language(code)
    return list(lang.tesseract) if lang and lang.tesseract else ["eng"]


def terminators_for(code: str) -> tuple[str, ...]:
    lang = get_language(code)
    extra = lang.terminators if lang else ()
    return tuple(dict.fromkeys(UNIVERSAL_TERMINATORS + tuple(extra)))


def script_of_char(ch: str) -> str | None:
    cp = ord(ch)
    for script, ranges in SCRIPT_RANGES.items():
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return script
    return None


def script_profile(text: str) -> dict[str, float]:
    """Fraction of *letters* in each script. Digits/punctuation are ignored."""
    counts: dict[str, int] = {}
    total = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total += 1
        script = script_of_char(ch) or "Other"
        counts[script] = counts.get(script, 0) + 1
    if not total:
        return {}
    return {k: v / total for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}


def script_ratio(text: str, code: str) -> float:
    """Share of letters in ``text`` that belong to ``code``'s script (0..1).

    1.0 means every letter is in the expected script; a translation into Arabic
    that comes back in Latin letters scores near 0.
    """
    lang = get_language(code)
    if lang is None:
        return 1.0
    profile = script_profile(text)
    if not profile:
        return 1.0
    want = lang.script
    if want == "Japanese":
        return profile.get("Japanese", 0.0) + profile.get("Han", 0.0)
    return profile.get(want, 0.0)


@lru_cache(maxsize=256)
def _marker_set(code: str) -> frozenset[str]:
    lang = get_language(code)
    return frozenset(lang.markers) if lang else frozenset()


def guess_language(text: str, candidates: tuple[str, ...] | None = None) -> str | None:
    """Cheap script-based language guess, no model involved.

    Picks the script with the most letters, then disambiguates sibling
    languages (Urdu vs Arabic vs Persian, Hindi vs Marathi, ...) using the
    marker characters declared in the registry. ``candidates`` narrows the
    search (e.g. to the book's source/target pair).
    """
    profile = script_profile(text)
    if not profile:
        return None
    script = next(iter(profile))
    pool = [get_language(c) for c in candidates] if candidates else list(LANGUAGES)
    pool = [
        lang
        for lang in pool
        if lang
        and (lang.script == script or (script == "Han" and lang.script in ("Han", "Japanese")))
    ]
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0].code
    letters = [ch for ch in text if ch.isalpha()]
    best, best_score = None, -1.0
    for lang in pool:
        markers = _marker_set(lang.code)
        hits = sum(1 for ch in letters if ch in markers)
        score = hits / max(1, len(letters))
        if score > best_score + 1e-9:
            best, best_score = lang, score
    if best is not None and best_score <= 0.0:
        # No marker seen: fall back to the canonical (marker-less) language of
        # the script, e.g. Arabic for Arabic script, Hindi for Devanagari.
        canonical = [lang for lang in pool if not lang.markers]
        best = canonical[0] if canonical else pool[0]
    return best.code if best else None


_WS = re.compile(r"[ \t ​‌‍﻿]+")


def normalize_text(text: str) -> str:
    """Unicode NFC + collapse exotic whitespace so length and glossary checks
    compare like with like."""
    text = unicodedata.normalize("NFC", text)
    return _WS.sub(" ", text)


def serialize(lang: Language) -> dict[str, object]:
    data = asdict(lang)
    data["tesseract"] = list(lang.tesseract)
    data["terminators"] = list(lang.terminators)
    return data


def all_languages() -> list[dict[str, object]]:
    return [serialize(lang) for lang in LANGUAGES]
