# JARVIS

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![UI PySide6](https://img.shields.io/badge/UI-PySide6%20(Qt6)-41CD52.svg)](https://pypi.org/project/PySide6/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> A local-first, open-source, Cortana-like personal AI assistant for Windows.

Personal files, notes, conversational memory, indexes, and metadata stay strictly on your local machine. Only the minimum context needed to answer a given request is ever sent to a cloud LLM (Groq primary, Ollama Cloud fallback) — never your whole database or document library.

Full technical specification: [spec.md](spec.md).

---

## ✨ Features

- 💬 **Modern Desktop Chat UI**: Native PySide6 interface with Light & Dark themes, rendered markdown (tables, code blocks, syntax highlighting, bulleted lists), and clickable source citation chips.
- 🔍 **Hybrid Local Document RAG**: Combines BM25 keyword search + FAISS vector embeddings (`all-MiniLM-L6-v2`) with a cross-encoder precision reranker (`ms-marco-MiniLM-L-6-v2`) over personal documents (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.txt`, `.md`, `.json`, code).
- 🎙️ **Push-to-Talk Voice Chain**: Dual-tier speech-to-text (Groq Whisper → Deepgram → local `faster-whisper`) and text-to-speech (Groq Orpheus → Deepgram Aura → local Piper ONNX) that degrades gracefully without crashing.
- 🌐 **Private Web Search**: Zero-tracking web queries via an integrated, local [SearXNG](https://docs.searxng.org/) metasearch process.
- 🪟 **Native Windows Integration**: Lightweight background supervisor with a global hotkey (`Ctrl+Space`), system tray icon, Task Scheduler startup integration, and an allowlisted application launcher.
- 🛡️ **Privacy & Security Guardrails**: Explicit user confirmation required for destructive actions (deleting files, locking system, external tools), zero arbitrary shell execution, local SQLite storage, and automatic secret scrubbing in logs.

---

## 📋 Requirements

- **Operating System**: Windows 10 or 11 (64-bit)
- **Python**: Python 3.11+
- **Primary LLM**: A free [Groq API key](https://console.groq.com/keys)
- *(Optional)* **Fallback LLM**: An [Ollama Cloud](https://ollama.com) API key (automatic fallback if Groq is rate-limited)
- *(Optional)* **Cloud Voice**: A [Deepgram API key](https://console.deepgram.com) (for cloud STT/TTS)
- *(Optional)* **Web Search**: A running local [SearXNG](https://docs.searxng.org/) instance

---

## 🚀 Quick Start & Setup

### 1. Clone & Set Up Environment

Open Command Prompt or PowerShell:

```bat
:: 1. Clone the repository
git clone https://github.com/Sujith5679/jarvis---Local-Personal-AI-Assistant-for-Windows.git
cd "jarvis---Local-Personal-AI-Assistant-for-Windows"

:: 2. Create and activate a Python virtual environment
python -m venv .venv
.venv\Scripts\activate

:: 3. Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure your API credentials:

```bat
copy .env.example .env
```

Open `.env` in your text editor and set your `GROQ_API_KEY`:

```env
GROQ_API_KEY="gsk_your_actual_groq_api_key_here"
```

*(All other settings in `.env` have sensible offline/local defaults or are optional).*

### 3. Launch JARVIS

You can launch JARVIS in either of two ways:

- **Full Application Direct Launch**:
  ```bat
  start_jarvis.bat
  ```
- **Lightweight Supervisor (Recommended)**:
  ```bat
  start_jarvis_supervisor.bat
  ```
  Runs a minimal background process (~15MB RAM) with the global `Ctrl+Space` hotkey and system tray icon. The full assistant (~100MB+ RAM) loads on demand when summoned and releases memory when closed.

---

## 📂 Project Structure

```text
├── agent/            # LangGraph orchestration, state graph, confirmation guardrails
├── app/              # Bootstrap, lifecycle, Windows startup, and background supervisor
├── config/           # Pydantic Settings, defaults, and policy presets
├── documents/        # Ingestion extractors for PDF, DOCX, PPTX, XLSX, TXT, MD, HTML
├── llm/              # Multi-provider LLM abstraction (Groq, Ollama Cloud, token pricing)
├── rag/              # BM25 + FAISS hybrid retriever, ingestion pipeline, cross-encoder reranker
├── scheduler/        # APScheduler background tasks and persistent reminders
├── security/         # Secret scrubbing, audit logging, input validation
├── storage/          # SQLite database connection, migrations, and repositories
├── tools/            # Safe built-in tools (file search, web search, app launcher, timers)
├── ui/               # PySide6 desktop interface (chat window, theme engine, history drawer)
├── voice/            # Push-to-talk STT & TTS dispatchers (Groq, Deepgram, local Whisper/Piper)
├── web/              # SearXNG process management and article text scraper
└── tests/            # Hermetic unit, integration, and UI test suite (450+ tests)
```

---

## 🌐 Web Search (SearXNG)

`web_search` and `open_webpage` use a local SearXNG instance. No Docker container is required — SearXNG runs as a plain Python/Flask app:

```bat
:: Outside the jarvis repo (e.g. in C:\Users\you\searxng):
git clone --no-checkout https://github.com/searxng/searxng.git
cd searxng

:: Windows sparse-checkout (avoids illegal Windows path character in template):
git sparse-checkout init --no-cone
echo /* > .git\info\sparse-checkout
echo !/utils/templates/etc/httpd/sites-available/searxng.conf:socket >> .git\info\sparse-checkout
git sparse-checkout reapply

python -m venv .venv
.venv\Scripts\pip install -r requirements.txt tzdata
```

### SearXNG Configuration
1. In `searx/settings.yml`, under `search:`, add `- json` to the `formats:` list (SearXNG disables the JSON API by default; JARVIS requires it).
2. In the same file, replace the default `secret_key: "ultrasecretkey"` with a random value:
   ```bat
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. *(Windows-only fix)* In `searx/valkeydb.py`, move `import pwd` inside the `except ImportError` block so Unix-only imports are avoided on Windows.

Run it with:
```bat
.venv\Scripts\python.exe -m searx.webapp
```
It serves on `http://127.0.0.1:8888`. Without SearXNG running, JARVIS degrades gracefully (local features continue working, while web search reports itself temporarily unavailable).

### Auto-starting SearXNG with JARVIS

To let JARVIS manage SearXNG automatically, set in `.env`:
```env
SEARXNG_AUTOSTART=true
SEARXNG_DIR=C:\Users\you\searxng
```
JARVIS will verify if port 8888 is already active; if not, it spawns SearXNG as a child process and terminates it when JARVIS exits.

---

## 🎙️ Voice (Push-to-Talk)

Voice uses a multi-tier fallback chain for both speech-to-text (STT) and text-to-speech (TTS):

1. **`groq`** (Primary cloud) — Groq's hosted Whisper (STT) and Orpheus (TTS) models using your existing `GROQ_API_KEY`.
   - *Note for TTS*: Accept the one-time Orpheus model terms at [Groq Console](https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english). Until accepted, TTS automatically falls back to the next backend.
2. **`deepgram`** (Secondary cloud) — Deepgram Listen (STT) and Aura (TTS). Set `DEEPGRAM_API_KEY` in `.env`.
3. **`local`** (Offline safety net) — Local `faster-whisper` (STT, auto-downloads base model on first run) and `piper` (TTS, local ONNX voice):

   ```bat
   mkdir data\voices
   .venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir data\voices
   ```

- Configure the chain order in `.env` via `JARVIS_STT_PROVIDERS` and `JARVIS_TTS_PROVIDERS` (default: `groq,deepgram,local`).
- In the chat window, hold the **🎤 button** to talk and release to submit.
- To disable voice completely, set `JARVIS_ENABLE_VOICE=false` in `.env`.

---

## 🪟 Windows Integration

JARVIS is designed to stay out of the way until needed:

- **Global Hotkey (`Ctrl+Space`)**: Configurable via `JARVIS_HOTKEY` in `.env` (e.g. `ctrl+alt+j`). Pressing the hotkey summons JARVIS to the foreground or launches it if idle.
- **Background Supervisor (`app/supervisor.py`)**: Runs in the system tray and monitors the hotkey without loading ML models or databases into memory.
- **Start with Windows**: Toggle *"Start JARVIS with Windows"* in Settings to register a Windows Task Scheduler entry that boots the supervisor at user login (never forces auto-start by default).
- **Safe Application Launching**: The `launch_application` tool can only launch apps from an explicit allowlist (`notepad`, `calc`, `paint`, `wordpad`, `explorer`, `snipping tool`, `task manager`, `control panel`). Arbitrary shell execution is strictly disallowed.

---

## 🧪 Development & Testing

Run code quality checks and tests:

```bat
:: Activate virtual environment
.venv\Scripts\activate

:: Run fast unit and integration tests (recommended for daily dev)
pytest -m "not slow"

:: Run complete test suite (includes slower offline ML model checks)
pytest

:: Linting and style verification
ruff check .

:: Type checking
mypy .
```

---

## 🔒 Security & Privacy Model

- **No Secret Leaks**: `.env` and `.env.*` are gitignored. Secrets are masked (`mask(...)`) and scrubbed from LLM prompts and audit logs.
- **Destructive Action Confirmation**: High-risk tool calls (file modifications, system locks, external actions) trigger an interactive confirmation dialog requiring your approval before execution.
- **Zero Raw Shell Access**: The LLM interacts only through typed, constrained tools with input validation and timeouts.
- **Local Data Guarantee**: SQLite database, vector indexes, and chat history are stored under `./data` (or your custom `JARVIS_DATA_DIR`) and never leave your PC.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
