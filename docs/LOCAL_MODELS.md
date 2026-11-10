# Running TranslateBook AI on your own machine

Everything in TranslateBook AI works with a model that runs on your laptop. Nothing leaves the machine, and every call costs $0. This guide covers which model to pick, how to connect it, and what to expect.

## 1. Pick a model for your hardware

| Your machine | Translator | Vision OCR for hard scans (optional) |
|---|---|---|
| 8 GB RAM, no GPU | `qwen3:4b` or `phi4-mini` | `qwen2.5vl:3b` |
| 16 GB RAM, no GPU | **`qwen3:8b`** (recommended) or `aya-expanse:8b` | `qwen2.5vl:7b` or `gemma3:4b` |
| 16 GB RAM or a 8–12 GB GPU | `gemma3:12b` | `gemma3:12b` (same model) |
| 24 GB+ GPU or Apple Silicon with 32 GB | `qwen3:14b`, `gemma3:27b` | `qwen2.5vl:7b` |

The same list appears in the app under **Settings → Small models that run on a laptop**. Each row has a **Use** button.

| Model | Params | RAM | Vision | Notes |
|---|---|---|:-:|---|
| `qwen3:8b` | 8B | ~8 GB | | 119 languages including Arabic, Urdu, Persian, Hindi and Turkish. The best all-rounder |
| `qwen3:4b` | 4B | ~5 GB | | Strong once sentence alignment is on, which happens automatically for small models |
| `gemma3:12b` | 12B | ~10 GB | ✓ | 140+ languages. Translator and OCR in one model |
| `gemma3:4b` | 4B | ~5 GB | ✓ | A 3 GB download that handles both jobs |
| `aya-expanse:8b` | 8B | ~8 GB | | Cohere's multilingual model, with an excellent Arabic register |
| `llama3.1:8b` | 8B | ~8 GB | | English-centric baseline |
| `phi4-mini` | 3.8B | ~4 GB | | The fastest usable option on weak hardware |
| `qwen2.5vl:7b` | 7B | ~8 GB | ✓ | The best free OCR for Nastaliq Urdu and other scripts Tesseract struggles with |
| `qwen2.5vl:3b` | 3B | ~4 GB | ✓ | Vision OCR on 8 GB machines |
| `minicpm-v` | 8B | ~8 GB | ✓ | Strong document OCR |

Reasoning models such as `qwen3` and `deepseek-r1` emit `<think>…</think>` blocks. The provider layer strips them automatically.

## 2. Connect it

### Ollama

```bash
# install from https://ollama.com/download, then:
ollama pull qwen3:8b
ollama pull qwen2.5vl:7b    # optional, for scanned books
```

Open **Settings** in TranslateBook AI. A running Ollama is detected and shown in a green banner with its models. Click **Use it**, pick the model, optionally set the vision model, then press **Test connection** and **Save**.

The app gives Ollama an 8,192-token context, because the default 2,048 is too small for a chunk plus context plus glossary. It also uses Ollama's JSON mode for the reviewer and terminology steps.

### LM Studio

1. Download a model in LM Studio. A GGUF build of Qwen3 8B or Gemma 3 12B is a good choice.
2. Open the **Developer** tab and start the server, which listens on port 1234 by default.
3. In TranslateBook AI choose **LM Studio (local)**. The model list comes live from the server.

### Any OpenAI-compatible server

vLLM, llama.cpp `server`, LocalAI, Jan, text-generation-webui and company gateways all speak the same API. Choose **Any OpenAI-compatible server** and enter the base URL, usually ending in `/v1`. Add a key only if your server requires one.

### Without the UI

The same settings work from `.env`. Values saved in the UI take precedence.

```ini
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
VISION_MODEL=qwen2.5vl:7b
TRANSLATION_CONCURRENCY=1
```

## 3. What the agent does differently for a small model

The model name sets a size tier. `qwen3:4b` is small, `qwen3:8b` is medium, and `gpt-4.1` is large. The tier picks the scaffolding:

| | Small (≤ 4B) | Medium (≤ 14B) | Large |
|---|---|---|---|
| Profile | thorough | balanced | balanced |
| Sentence alignment | on | on | off |
| Tagged output instead of JSON | on | on | off |
| Chunk size | ≤ 700 chars | ≤ 1,000 chars | 1,200 chars |
| Candidates per chunk (local) | 2 | 1 | 1 |
| Polish pass | on | off | off |
| Retries | ≥ 2 | 1 | 1 |

You can see exactly what the current model gets in **Settings → What this model will get**, and override it per book. [AGENT_STRATEGY.md](AGENT_STRATEGY.md) explains each step.

## 4. What to expect

The numbers below were measured on the development laptop, which has 16 GB of RAM and no GPU (CPU inference only):

| Model | One Urdu → Arabic chunk (~400 chars), full agent | Result |
|---|---|---|
| `aya-expanse:8b` | ~8.5 minutes (translate + gate + review + terminology + OCR repair) | Gate passed and the reviewer scored it 0.95. The Arabic was understandable but still needed a scholar's edit |

What this means in practice:

- **CPU-only laptops are slow.** Plan for a few minutes per chunk, so a 300-page book is an overnight job. Choose the *fast* profile to skip the review step and roughly halve the time, or use `qwen3:4b`.
- **A GPU changes everything.** The same models run 10–30× faster on an 8 GB+ GPU or on Apple Silicon.
- **Self-review by a small model is lenient.** An 8B reviewer tends to approve its own family's output. The deterministic gate is what reliably catches omissions and wrong-language answers. For important books, translate with a local model and review in the UI, or point the reviewer at a stronger cloud model later.
- **Keep `TRANSLATION_CONCURRENCY=1`** for a local model. Parallel requests just queue inside Ollama and add memory pressure.

## 5. Mixing local and cloud

A common setup uses a local translator, which is free and private, together with free OCR. For the hardest scans, set a cloud vision model such as `gpt-4.1-mini` as the vision model. Only the pages the free OCR reads badly are sent to it.
