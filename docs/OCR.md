# OCR: reading scanned books without a model

Many of the books people most need translated exist only as scans. TranslateBook AI reads them with free, open-source engines first. A paid or GPU-hungry vision model is used only for the pages those engines read badly, and only if you configured one. The code is in [`backend/app/pipeline/ocr/`](../backend/app/pipeline/ocr/). The decision record is [ADR-0011](adr/0011-free-ocr-ladder.md).

## The ladder

For every page:

1. **Text layer first.** If the PDF has a real text layer, it is used directly. "Real" means at least 40 letters, or any text on a page that is not covered by a large image. That rule ignores the junk invisible layers many scanners add.
2. **Render.** The page is rendered at 300 dpi in greyscale with auto-contrast. Blank pages (under 0.2% ink) are skipped without an OCR call.
3. **Recognise.** Free engines are tried in order, and the first good read wins:

   | Engine | Needs | Word confidences | Notes |
   |---|---|:-:|---|
   | Tesseract (system binary) | Tesseract 5 installed | ✓ | Preferred, because confidences make the quality score sharp |
   | Tesseract bundled in PyMuPDF | nothing extra | | Always available. Language packs download on first use |
   | EasyOCR | `uv sync --extra ocr-neural` (~2.5 GB) | ✓ | An optional neural fallback |

4. **Rebuild the layout.** This step is pure geometry and needs no model:
   - Words are grouped into lines. A line that spans a wide horizontal gap is split, which separates the two pages of a scanned spread and the two columns of a page that the engine had stitched together.
   - Columns are detected from empty vertical bands. Lines wider than 65% of the page, such as headings, split the page into bands.
   - Reading order is set: columns run right-to-left for RTL scripts and left-to-right otherwise, each read top to bottom.
   - Page numbers and running heads in the top and bottom 10% of the page are tagged and dropped.
5. **Score the page** without any reference text. See below.
6. **Escalate** when the score falls below `OCR_ESCALATION_THRESHOLD` (default 0.7). First the next free engine is tried. Then, if a vision-capable model is configured and `OCR_VISION=auto`, the page goes to that model with a strict transcription prompt. The vision result replaces the free one only if it scores at least as well.

### Language packs

Packs come from the language registry. Urdu uses `urd` and `ara`, and Hindi uses `hin`. The target language's packs are added too, because books quote the other language constantly, and `eng` is always included for citations and numbers. Packs are found in `TESSDATA_PREFIX`, in the usual install folders, or in the managed directory `backend/data/tessdata`. Missing packs are downloaded from `tesseract-ocr/tessdata_best` on first use. Set `OCR_PACK_REPO=fast` for smaller packs, or `OCR_DOWNLOAD_PACKS=false` for offline installs.

## The quality score

Each page gets a score from 0 to 1, built from four signals:

| Signal | What it catches |
|---|---|
| Mean word confidence, and the share of words below 45 | Tesseract's own doubt |
| **Script validity**: share of letters in the expected script | Arabic that came back as Latin mojibake |
| **Garbage**: letterless tokens, words too long for the script, stray Latin capitals inside a non-Latin book, scripts glued together | Lost spaces (a classic Arabic failure), noise read as letters |
| **Word shape**: mean letters per word far outside the script's normal range | Pages where spacing collapsed |

An engine without confidences is capped at 0.82. A page that cannot be verified should never look better than one that can.

Scores travel with the text. Every chunk stores `ocr_quality` and `ocr_engine`, so the review screen marks chunks to double-check with a warning icon and a quality pill.

## OCR repair before translation

When a chunk's OCR quality is below `OCR_CLEANUP_THRESHOLD` (default 0.85), the text model first repairs the source using [`prompts/ocr_cleanup.md`](../prompts/ocr_cleanup.md). It fixes misread letters, split and merged words, and stray symbols, and it is told never to paraphrase. The repair is accepted only if the length stays within ±40% and the script stays the same. The reviewer can switch between **OCR-repaired** (what the translator read) and **as scanned**.

## Measured on real pages

| Page | Engine | Score | Notes |
|---|---|---|---|
| Clean printed Arabic (synthetic, Arial, 300 dpi) | Tesseract | 0.96 (mean confidence 92) | Near-perfect text |
| Scanned Urdu/Arabic spread, *Ghair Soodi Bankari* p. 11–14 | Tesseract / PyMuPDF | 0.70 mean, 0.47–0.87 per chunk | The Arabic quotations read well. The Nastaliq Urdu commentary is poor |

**Honest limits.** Tesseract reads printed Naskh Arabic, Latin, Cyrillic, Greek and most Indic scripts well. It is weak on **Urdu Nastaliq**, handwriting, very faint prints and decorative headings. For those, configure a small vision model. `qwen2.5vl:7b` and `gemma3:4b` both run on a 16 GB laptop. Only the poor pages are sent to it, so a mostly clean book still costs almost nothing.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `OCR_ENGINE` | `auto` | `auto`, `tesseract`, `mupdf`, `easyocr`, `vision` or `none` |
| `OCR_DPI` | `300` | Render resolution |
| `OCR_DOWNLOAD_PACKS` | `true` | Fetch missing traineddata on first use |
| `OCR_PACK_REPO` | `best` | `best` (accurate) or `fast` (small) |
| `OCR_ESCALATION_THRESHOLD` | `0.7` | Pages below this try the next engine or the vision model |
| `OCR_VISION` | `auto` | `auto` (poor pages only), `always` or `off` |
| `OCR_EXTRA_LANGUAGES` | | Extra language codes to recognise, comma separated |
| `OCR_LLM_CLEANUP` | `auto` | Repair noisy chunks with the text model: `auto`, `always` or `off` |
| `OCR_CLEANUP_THRESHOLD` | `0.85` | Chunks below this are repaired when the setting is `auto` |
| `TESSERACT_CMD` | | Path to `tesseract` if it is not on PATH |
| `TESSDATA_DIR` | `./data/tessdata` | Managed pack directory |

**Settings → OCR** shows which engines are available and which packs are installed.
