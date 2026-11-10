# Languages

Every language is one entry in [`backend/app/core/languages.py`](../backend/app/core/languages.py). That entry drives the whole product:

| Field | Used by |
|---|---|
| `code`, `name`, `native` | Language pickers, prompts ("translate from Urdu to Arabic") |
| `script` | Gate: script ratio, source leak. OCR quality: script validity. Language guessing |
| `rtl` | UI direction, DOCX paragraph direction, OCR column order |
| `tesseract` | Which traineddata packs OCR loads, most specific first |
| `font`, `font_scale`, `line_height` | UI text and DOCX font. Fonts load on demand from Google Fonts |
| `terminators` | The sentence segmenter |
| `markers` | Characters that tell sibling languages apart (Urdu vs Arabic vs Persian) |
| `spaced` | Length-ratio bands and garbage detection for unspaced scripts (Chinese, Japanese, Thai) |

The API serves the registry at `GET /api/v1/languages`. The UI never hard-codes a language list.

## Supported languages (51)

| Script | Languages | Font |
|---|---|---|
| Arabic | Arabic, Persian, Pashto, Sindhi, Uyghur, Kurdish (Sorani) | Noto Naskh Arabic |
| Arabic (Nastaliq) | Urdu | Noto Nastaliq Urdu |
| Hebrew | Hebrew | Noto Serif Hebrew |
| Latin | English, French, German, Spanish, Portuguese, Italian, Dutch, Turkish, Indonesian, Malay, Swahili, Polish, Vietnamese, Somali, Hausa, Uzbek, Azerbaijani | Noto Serif |
| Cyrillic | Russian, Ukrainian, Kazakh | Noto Serif |
| Greek | Greek | Noto Serif |
| Devanagari | Hindi, Marathi, Nepali, Sanskrit | Noto Sans Devanagari |
| Other Indic | Bengali, Punjabi (Gurmukhi), Gujarati, Tamil, Telugu, Kannada, Malayalam, Sinhala | Noto Sans (per script) |
| CJK | Chinese (Simplified), Chinese (Traditional), Japanese, Korean | Noto Sans SC / TC / JP / KR |
| Southeast Asian | Thai, Burmese, Khmer | Noto Sans (per script) |
| Other | Amharic, Armenian, Georgian | Noto Sans (per script) |

Any pair works: Urdu → Arabic, Persian → English, English → Hindi, Chinese → Spanish, and so on. Translation quality depends on the model. Qwen3 and Gemma 3 cover all of these. Very small models are noticeably weaker on low-resource languages.

## Language detection

When you pick a PDF, the upload wizard inspects the first pages (`POST /api/v1/books/sniff`). With a text layer, it reads the text. Without one, Tesseract's orientation-and-script detection picks the packs and page 2 is OCRed. `guess_language()` then takes the dominant script and separates sibling languages by marker letters: ٹ ڈ ڑ ں ے for Urdu, گ چ پ ژ for Persian. No model is involved.

## Adding a language

Add one line to `LANGUAGES`:

```python
Language("yo", "Yoruba", "Yorùbá", script="Latin", tesseract=("yor",)),
```

If the script is new, also add its Unicode ranges to `SCRIPT_RANGES`. That is all: the picker, fonts, OCR packs, the gate and DOCX export pick it up automatically. Packs are downloaded from `tessdata_best` on first use.
