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

## Web search (SearXNG)

`web_search`/`open_webpage` need a running SearXNG instance. No Docker required —
it runs as a plain Python/Flask app:

```bat
:: Outside the jarvis repo, e.g. in your user folder:
git clone --no-checkout https://github.com/searxng/searxng.git
cd searxng
:: Windows can't check out one file with a ':' in its name (a Linux systemd
:: template) — sparse-checkout everything except it:
git sparse-checkout init --no-cone
echo /* > .git\info\sparse-checkout
echo !/utils/templates/etc/httpd/sites-available/searxng.conf:socket >> .git\info\sparse-checkout
git sparse-checkout reapply

python -m venv .venv
.venv\Scripts\pip install -r requirements.txt tzdata
```

Then two small edits before first run:
1. In `searx/settings.yml`, under `search:`, add `- json` to the `formats:` list
   (SearXNG disables the JSON API by default — our tools need it).
2. In the same file, replace the default `secret_key: "ultrasecretkey"` with a random
   value (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).

One more Windows-only fix: `searx/valkeydb.py` unconditionally imports the Unix-only
`pwd` module (only actually used in an optional Redis/Valkey error-logging path we
don't use). Move `import pwd` from the top of the file into the `except ImportError`-
guarded block right before its one use site, so it only gets touched on Linux.

Run it with `.venv\Scripts\python.exe -m searx.webapp` (serves on
`http://127.0.0.1:8888` by default), then set `SEARXNG_URL` in `.env` to match. It
needs to be running whenever you want `web_search`/`open_webpage` to work — without
it, JARVIS degrades gracefully (local features keep working, web search reports
itself as temporarily unavailable) rather than failing.

## Voice (push-to-talk)

Two backends for both speech-to-text and text-to-speech, selected per `.env`:

- **`groq`** (default) — Groq's hosted Whisper (STT) and Orpheus (TTS) models, using
  the same `GROQ_API_KEY` you already have. Fast, no local RAM/CPU cost, needs
  internet + API quota. **TTS needs a one-time step**: accept the Orpheus model's
  terms at
  https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english — until
  then, TTS transparently falls back to local (see below), no config change needed.
- **`local`** — faster-whisper (STT, downloads its model automatically on first use)
  and Piper (TTS, needs a voice model downloaded once):

  ```bat
  mkdir data\voices
  .venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir data\voices
  ```

Set `JARVIS_STT_PROVIDER=local` / `JARVIS_TTS_PROVIDER=local` in `.env` for fully
offline voice (spec.md §33/§34's privacy/offline modes). Whichever provider you
pick, a failure there always falls back to local automatically — voice degrades to
text-only rather than failing outright if neither is available.

Hold the 🎤 button in the chat window to talk, release to send. Set
`JARVIS_ENABLE_VOICE=false` in `.env` to hide the mic button entirely.

To use a different local voice, browse [available voices](https://github.com/rhasspy/piper/blob/master/VOICES.md)
and set `JARVIS_PIPER_VOICE_PATH` in `.env` to the downloaded `.onnx` file's path.

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
