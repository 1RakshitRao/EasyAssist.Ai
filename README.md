#  Helpdesk RAG Chatbot

Internal AI helpdesk that answers **HR**, **IT**, **Compliance**, and **Legal** questions from grounded knowledge bases. It never invents policy when the KB has no answer.

## What you get

- FastAPI REST API (`/query`, `/ingest`, `/health`)
- Four ChromaDB collections + 32 seed policy docs
- LangGraph pipeline: classify → retrieve → (reclassify loop | escalate) → answer
- Redis FAQ cache with in-memory fallback
- Haiku for classify + routine answers; Sonnet for high severity
- Anthropic prompt caching on classifier and answer system prompts
- Per-node timings, `attempted_depts`, `retry_count`, `escalated` on every response

## Setup (Windows PowerShell)

```powershell
cd C:\Users\RakshitRao\AmpcusHelpdesk

# Virtualenv
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=...

uvicorn app.main:app --reload --port 8000
```

- Health: http://localhost:8080/health  
- Interactive docs: http://localhost:8080/docs  
- **Dashboard + chatbot:** http://localhost:8080/  

First startup downloads the MiniLM embedding model and seeds Chroma under `./data/chroma`.

## Example

```powershell
Invoke-RestMethod -Method POST -Uri http://localhost:8000/query `
  -ContentType "application/json" `
  -Body '{"question":"How many PTO days do I get?"}'
```

Second identical (or trivially different) question should return `"cached": true`.

## Pipeline (LangGraph)

```
normalize → cache?
         ↓ miss
classify (Haiku, prompt-cached) → retrieve (Chroma)
         ↑_______________| empty + retry < max
                         | empty + retries done → answer (honest refusal)
                         | chunks + high + legal/hr → escalate → answer
                         | chunks otherwise → answer
```

Agents are isolated. Shared `HelpdeskState` is the only contract. Conditional edges are pure Python.

## Tests

```powershell
pytest -q
```

Most unit tests run without an API key (classifier fallback, normalize, routing, refuse-if-empty).

## LLM providers (Groq default)

Default provider is **Groq**, with tier-based routing:

| Tier | Model | Use |
|------|-------|-----|
| fast | `openai/gpt-oss-20b` | Classifier, scorer, NLP |
| balanced | `openai/gpt-oss-120b` | Answers, document summarization |
| powerful | `openai/gpt-oss-120b` | High + escalated answers |
| guardrails | `llama-prompt-guard-2-86m` | Phase 9 safety checks |

Set `GROQ_API_KEY` in `.env` (from [console.groq.com](https://console.groq.com)). Switch to Grok with `LLM_PROVIDER=grok` + `XAI_API_KEY`, or Anthropic with `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`. **Ollama is not supported.**

Smoke tests:
- `python scripts/test_groq.py`
- `python scripts/check_groq_models.py`

## Semantic cache

FAQ answers live in a dedicated Chroma collection (`helpdesk_semantic_cache`) using MiniLM embeddings. Lookups use cosine similarity (default threshold **0.70** for MiniLM paraphrases; raise toward **0.92** for stricter near-duplicate-only hits). Tune with `SEMANTIC_CACHE_THRESHOLD` in `.env`.

## Out of scope (MVP)

Ingest auth, real Slack/ticket escalation wiring, multi-turn memory, analytics dashboard.
