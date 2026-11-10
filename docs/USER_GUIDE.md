# User guide

This guide walks through translating a book from start to finish. Installation is in the [README](../README.md#run-it-in-3-minutes).

## 1. Connect a model (once)

Open **Settings → Model**.

- **On your own machine (free):** install [Ollama](https://ollama.com/download) and run `ollama pull qwen3:8b`. The Settings page detects it and shows a **Use it** button. See [LOCAL_MODELS.md](LOCAL_MODELS.md) for which model fits your laptop.
- **With your own API key:** pick a cloud provider, paste the key (there is a **Get a key** link next to the field), choose a model, then press **Test connection** and **Save**.
- **Optional vision model:** if you translate scanned books in scripts that OCR reads poorly, such as Urdu Nastaliq, set a vision model like `qwen2.5vl:7b`. Only pages the free OCR reads badly are sent to it.

The panel **What this model will get** shows the checks the agent will run for the model you chose. The model pill in the top bar always shows what is active.

You can skip this step to explore: without a model, the app runs in demo mode with placeholder translations, and OCR still works.

## 2. Upload a book

Click **Upload book**, then drop a PDF.

- The first pages are inspected right away: the page count, whether the PDF is a scan, the detected language and a text sample. Check the source language it picked.
- Choose the **target language**. There are 51 languages, grouped by script.
- **What is this book about?** Pick a preset such as *Islamic scholarship*, *novel* or *medical textbook*, or type your own. This steers register and terminology in every prompt.
- **Instructions for the translator** are a short style guide in plain words: formality, how to render names, what to keep untranslated.

Press **Upload & extract**. Extraction runs in the background, and the book page shows live progress.

## 3. Check extraction

On the book page:

- **Progress** shows how many chunks are in each state.
- **OCR** (scanned books only) shows pages read, mean quality, which engines were used and how many pages escalated to the vision model. A mean below 70% means the scan is hard. Read the advice in that panel.
- **Book settings** let you change the domain and instructions, and override the **quality profile** (fast, balanced or thorough) and **sentence alignment** for this book.

## 4. Translate

In **Actions**, press **Start translation**. You can limit the run to a **page range** (for example `10-13`) to try settings on a sample first, or retry **only failed chunks**.

The **Agent strategy** card shows what will run. **LLM usage & cost** fills as calls are made; local models cost $0.

## 5. Review

Press **Open review**.

- **Left:** chunks with their status. A warning icon marks low OCR quality, and an amber number counts terms waiting for a decision.
- **Middle:** the source in its script's font and the translation in an editor. For OCRed chunks that were repaired, switch between **OCR-repaired** (what the translator read) and **as scanned**.
- **Verification:** the reviewer's score and span-level suggestions. **Accept** replaces the span in the translation; **Reject** dismisses it.
- **Right, terminology:** terms a human should decide once. **Accept**, **Edit** or **Reject**. With **Apply to whole book** checked, the decision goes into the glossary and every later chunk uses it.
- **Approve** a chunk when it is right. **Retranslate** runs the agent again on one chunk, for example after you have decided several terms.

| Key | Action |
|---|---|
| `j` / `k` | Next / previous chunk |
| `a` | Approve |
| `e` | Edit the translation |

## 6. Glossary

At the bottom of the book page you can add terms by hand, **Import** a glossary (a JSON array, or CSV with an `original_term,translation` header) or **Export** it to reuse in another book.

## 7. Export

**Export DOCX** writes the book with headings, right-to-left paragraphs where needed and the right font for the target script. Untranslated chunks are included as source text with an `[untranslated]` marker, so nothing is lost. Open the file in Word or LibreOffice to typeset or save it as a PDF.

## FAQ

**Is my book sent anywhere?** Only to the model you configured. With Ollama or LM Studio nothing leaves your machine. Books, glossaries and keys are stored in your local database and folders.

**How long does a book take?** With a cloud model, seconds per chunk. With an 8B model on a CPU-only laptop, a few minutes per chunk, so plan an overnight run for a full book or choose the *fast* profile. A GPU makes local models 10–30× faster.

**Which profile should I use?** Leave it on *auto*. Use *fast* for a quick first draft, and *thorough* when quality matters more than time.

**The OCR text looks wrong.** Check the OCR panel. For Urdu Nastaliq and faint scans, configure a vision model and re-upload. See [OCR.md](OCR.md).

**A chunk failed.** Its error is shown in review. Typical causes are a model server that is not running or a timeout on slow hardware (raise `LLM_TIMEOUT_SECONDS`). Fix the cause, then use **Only failed chunks**.

**Can I change the model halfway through?** Yes. Save new settings; the next chunks use the new model. The cost table shows calls per model.
