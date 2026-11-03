# Golden item schema (JSON Lines, one object per line)

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | yes | Stable id, `ur-ar-0001`. Never reuse after results exist. |
| `source_lang` | `"ur"` \| `"ar"` | yes | ISO 639-1. |
| `target_lang` | `"ur"` \| `"ar"` | yes | |
| `content_type` | enum | yes | `prose` \| `heading` \| `hadith` \| `quranic_verse` \| `footnote` \| `numbered_list` \| `poetry` \| `margin_note` (matches `app.models.base.ContentType`). |
| `source` | string | yes | Exact source text of the chunk (OCR errors corrected by hand). |
| `reference` | string | yes | The human reference translation. For `quranic_verse`, the reference is the verse itself (pass-through expected). |
| `alt_references` | string[] | no | Other acceptable renderings (chrF++ takes the max over all references). |
| `context_before` | string | no | Previous chunk text, if needed for a faithful translation. |
| `context_after` | string | no | Next chunk text. |
| `terms` | object[] | yes (may be empty) | Decided terminology present in `source`: `{"source": "صلاة", "target": "نماز", "variants": ["الصلوة"], "must_match": true}`. `variants` are other surface forms in the source that count as the same term. |
| `structure` | object | no | Expected structural markers to survive: `{"heading_level": 2}`, `{"list_items": 4}`, `{"footnote_markers": ["(1)"]}`. |
| `split` | `"dev"` \| `"test"` | yes | `test` items are only run at milestone ends. |
| `page` | integer | no | Source page in the sample book. |
| `notes` | string | no | Anything the judge or a future reader should know. |
| `difficulty` | `"easy"` \| `"medium"` \| `"hard"` | no | Annotator judgement; used to slice results. |
| `adversarial` | boolean | no | Marks the 10 deliberately tricky items. |

Validation rules (`evals/validate_golden.py`):
- ids unique; `source` and `reference` non-empty; every `terms[].source` (or a variant) occurs in `source`;
- `content_type` in the enum; `split` present; `quranic_verse` items have `reference == source`;
- at least 15 `test` items and at least 5 per `content_type` represented.
