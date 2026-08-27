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

### Auto-starting SearXNG with JARVIS

Instead of starting it yourself every time, let JARVIS manage it: set
`SEARXNG_AUTOSTART=true` and `SEARXNG_DIR` (the path to the checkout above, e.g.
`C:\Users\you\searxng`) in `.env`. On startup, JARVIS checks whether `SEARXNG_URL`
is already reachable (so it never spawns a redundant second instance if you — or a
previous JARVIS session — already have one running) and, if not, launches
`<SEARXNG_DIR>\.venv\Scripts\python.exe -m searx.webapp` itself, stopping it again
on exit. If `SEARXNG_DIR` isn't set or doesn't look like a real checkout, this is
silently skipped — the manual `web/searxng_process.py` requires no configuration
changes elsewhere and won't break anything if you'd rather keep starting it
yourself.

Note the startup health check may still briefly report "web_search: offline"
right after launch — SearXNG's own Flask server takes a few seconds to finish
booting, and JARVIS doesn't block its own startup waiting for it.

## Voice (push-to-talk)

Three backends for both speech-to-text and text-to-speech, tried in order (an
ordered chain per `.env`, same idea as the Groq→Ollama Cloud LLM fallback):

- **`groq`** (tried first) — Groq's hosted Whisper (STT) and Orpheus (TTS) models,
  using the same `GROQ_API_KEY` you already have. Fast, no local RAM/CPU cost, needs
  internet + API quota. **TTS needs a one-time step**: accept the Orpheus model's
  terms at
  https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english — until
  then, TTS transparently skips to the next backend, no config change needed.
- **`deepgram`** (tried second) — Deepgram's Listen (STT) and Aura (TTS) APIs. A
  separate service from Groq/Ollama — sign up at https://deepgram.com and set
  `DEEPGRAM_API_KEY` in `.env`. New accounts get a $200 one-time credit (not a
  recurring free tier); after that it's pay-per-use (~$0.006/min).
- **`local`** (final safety net, always available) — faster-whisper (STT, downloads
  its model automatically on first use) and Piper (TTS, needs a voice model
  downloaded once):

  ```bat
  mkdir data\voices
  .venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir data\voices
  ```

Order/membership configured via `JARVIS_STT_PROVIDERS` / `JARVIS_TTS_PROVIDERS`
(comma-separated, default `groq,deepgram,local`). A backend without its key
configured is skipped automatically; `local` is always attempted as a last resort
even if every configured cloud backend fails, so voice degrades to text-only rather
than failing outright. Set either to just `local` for fully offline voice (spec.md
§33/§34's privacy/offline modes).

Hold the 🎤 button in the chat window to talk, release to send. Set
`JARVIS_ENABLE_VOICE=false` in `.env` to hide the mic button entirely.

To use a different local voice, browse [available voices](https://github.com/rhasspy/piper/blob/master/VOICES.md)
and set `JARVIS_PIPER_VOICE_PATH` in `.env` to the downloaded `.onnx` file's path.

## Windows integration

JARVIS runs **on demand**, not as a permanently-resident background process: the
full app (agent, RAG, voice — everything, ~100MB+ once warmed up) only runs while
you're actually using it, and closing its window fully exits it, freeing that
memory. A separate, much lighter always-on **supervisor** process
(`app/supervisor.py` — just a tray icon and the global hotkey, no agent/RAG/voice
imports at all) is what stays running in the background so Ctrl+Space keeps
working even when JARVIS itself isn't open.

- **Global hotkey**: default `Ctrl+Space`, configurable via `JARVIS_HOTKEY` in
  `.env` (e.g. `ctrl+alt+j`), using the
  [`keyboard`](https://github.com/boppreh/keyboard) library's combo syntax. If
  JARVIS isn't running, pressing it launches a fresh instance (~1-3s); if it's
  already running (even minimized), it's brought to the foreground instead. If
  hotkey registration fails for any reason (another app already owns the combo, a
  restrictive permission context, ...) it's logged as a warning and everything else
  keeps working — the hotkey is a convenience, not a requirement.
- **Running it**: `start_jarvis_supervisor.bat` starts just the lightweight
  supervisor (tray icon + hotkey) — nothing else runs until you actually open
  JARVIS. `start_jarvis.bat` (what the supervisor itself launches) starts the full
  app directly, same as always, if you'd rather skip the supervisor.
- **Closing it**: the titlebar X (or JARVIS's own tray icon → Quit, which is a
  per-session convenience menu — Pause indexing, Start/Stop voice, Reindex files,
  View logs — separate from the supervisor's tray icon) fully exits the full app.
  The supervisor keeps running afterward so Ctrl+Space still works next time.
- **Start with Windows**: toggle "Start JARVIS with Windows" in Settings. This
  registers/removes a per-user Windows Task Scheduler entry (`schtasks`) that runs
  `start_jarvis_supervisor.bat` (not the full app) at logon — off by default, and
  only ever changed by that checkbox (never automatically, per spec.md §27: "Do not
  force automatic startup").
- **Application launching**: the `launch_application` tool can only run apps from a
  fixed allowlist (notepad, calculator, paint, wordpad, explorer, snipping tool,
  task manager, control panel — see `config/defaults.py`'s
  `DEFAULT_APP_ALLOWLIST`) — never an arbitrary command. `open_file` can only open a
  file already inside one of your indexed folders. `lock_system` locks the Windows
  session. All three always require your explicit confirmation before running.

## MCP servers

JARVIS can use tools from any [MCP](https://modelcontextprotocol.io) server you
configure — the same protocol Claude Desktop/Claude Code use, so a config you
already have for those can mostly be reused here.

Copy `mcp_servers.example.json` to `mcp_servers.json` (gitignored, same as `.env` —
a server's `env` block often carries a real API token) and list your servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\you\\Documents"],
      "env": {},
      "enabled": true
    }
  }
}
```

JARVIS connects to every enabled server in the background on startup (never
blocking the UI — the first connection to a fresh `npx`-based server can take a
while since `npx` has to download it first; it's fast on every launch after that)
and makes its tools available to the agent, namespaced `mcp__<server>__<tool>` so
they can never collide with a built-in tool name.

**Every MCP tool always requires your explicit confirmation before it runs, no
matter what it claims to do.** Unlike JARVIS's own built-in tools (each reviewed and
assigned a risk level by hand), an MCP server is external, user-configured code —
JARVIS has no way to verify what it actually does, so it's never trusted by
default. The confirmation prompt always shows which server a proposed action came
from.

Local (stdio) servers only for now — filesystem, git, sqlite, and similar. Remote/
HTTP MCP servers aren't supported yet.

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
