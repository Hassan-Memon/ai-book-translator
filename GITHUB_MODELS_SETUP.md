# GitHub Models Setup Guide

## What is GitHub Models?

GitHub Models is a **free** inference service that lets you test LLMs without paying for API credits. It includes:
- OpenAI's GPT-4.1
- Anthropic's Claude
- Meta's Llama
- And more

## Get Started (2 minutes)

### Step 1: Create GitHub Token
1. Go to: https://github.com/settings/personal-access-tokens
2. Click **"Generate new token (fine-grained)"**
3. Name it: `translatebook-ai`
4. You can select any scope or leave default
5. Click **"Generate token"** at the bottom
6. **Copy the token** (you'll only see it once)

### Step 2: Add to .env
Edit `.env` in the project root:

```env
GITHUB_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_PROVIDER=github
GITHUB_MODEL=openai/gpt-4.1
```

### Step 3: Test It
```bash
cd backend
python app/test_llm.py
```

You should see:
```
✓ GITHUB_TOKEN found
Provider: GitHubModelsProvider
Model: openai/gpt-4.1

Sending prompt to provider...
✓ Response received (XXX chars)

Translation:
...
```

## Available Models

On GitHub Models, you can use:

| Model | ID |
|-------|-----|
| GPT-4.1 | `openai/gpt-4.1` |
| GPT-4-turbo | `openai/gpt-4-turbo` |
| Claude 3.5 Sonnet | `anthropic/claude-opus` |
| Llama 3.1 | `meta/llama-3.1-405b-instruct` |

Change `GITHUB_MODEL` in `.env` to try different models.

## Troubleshooting

**"Invalid or expired token"**
- Regenerate your token at https://github.com/settings/personal-access-tokens
- Make sure it's copied correctly in `.env`

**"Rate limit exceeded"**
- GitHub Models has generous limits (~1,000 requests/month free)
- Wait an hour and try again

**Want real LLM providers?**
- **Anthropic Claude**: Set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=xxx`
- **OpenAI**: Set `LLM_PROVIDER=openai` + `OPENAI_API_KEY=xxx`
- **Ollama (local, free)**: Set `LLM_PROVIDER=ollama` (requires Ollama installed)

## Next: Running the App

Once GitHub Models is configured:

```bash
# Backend server
cd backend
uvicorn app.main:app --reload

# Then in another terminal, test the API:
curl http://localhost:8000/health
```
