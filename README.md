# JARVIS

A local-first, open-source, Cortana-like personal AI assistant for Windows.
Full design spec: [spec.md](spec.md). Build plan: see project history / `spec.md` §57 & §62.

Personal files, notes, memory, indexes, and metadata stay on your machine. Only the minimum
context needed to answer a request is ever sent to a cloud LLM (Groq primary, Ollama Cloud
fallback) — never a whole folder, database, or document set.

## Status

Early development (V1 foundation). See `spec.md` for the full specification and
`CHANGELOG.md` (once created) for progress.

## Requirements

- Windows 10/11
- Python 3.11+
- A [Groq API key](https://console.groq.com) (primary LLM)
- An Ollama Cloud API key (fallback LLM)
- (Optional, for web search) A running [SearXNG](https://docs.searxng.org/) instance

## Setup

```bat
:: 1. Clone/download this repository, then from the project root:
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 2. Configure credentials
copy .env.example .env
:: edit .env and fill in GROQ_API_KEY, OLLAMA_CLOUD_API_KEY, etc.

:: 3. Start JARVIS
start_jarvis.bat
```

On first run, JARVIS will:

1. Create its local SQLite database and run migrations (`data/jarvis.db`).
2. Let you select folders to index (Desktop/Documents/Downloads by default — never a whole drive).
3. Build the initial local search index in the background.
4. Let you configure startup-with-Windows preference in Settings.

## Development

```bat
pip install -r requirements.txt
pytest
ruff check .
mypy .
```

## Security notes

- `.env` is never committed; secrets are never logged, never sent to the LLM, and never stored
  in SQLite.
- Destructive or externally-consequential actions (deleting files, sending messages, etc.)
  always require explicit confirmation.
- The LLM never gets raw shell/OS access — only an explicit, permissioned set of tools.

See `spec.md` §28, §29, §53–§55 for the full security/permission model.
