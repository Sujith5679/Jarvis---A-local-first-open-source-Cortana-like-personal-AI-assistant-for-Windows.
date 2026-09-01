"""Tunable defaults for JARVIS.

Nothing that later needs tuning should be hard-coded elsewhere in the codebase
(spec.md §16: "No hard-coded values should be impossible to tune."). Add new
tunables here, not inline at their call site, and read them through
`config.settings.get_settings()` so every value stays overridable via `.env`
or a future settings UI.
"""

from __future__ import annotations

# --- LLM ---
DEFAULT_LLM_TIMEOUT_SECONDS = 30
DEFAULT_LLM_MAX_RETRIES = 2
DEFAULT_LLM_RETRY_BACKOFF_SECONDS = 1.5
# On a 429, wait the provider's real reported reset time (never a guess) —
# but only up to this cap. Groq's token-bucket resets are typically a few
# seconds (observed 1-4s live), worth waiting for; its request-bucket reset
# can be many minutes, not worth blocking the user for — past this cap we
# give up on this provider immediately so LLMManager falls back faster.
DEFAULT_LLM_RATE_LIMIT_MAX_WAIT_SECONDS = 8.0

# --- Agent loop guardrails (spec.md §12) ---
DEFAULT_MAX_TOOL_STEPS = 8
DEFAULT_MAX_REASONING_ITERATIONS = 6
DEFAULT_TOOL_TIMEOUT_SECONDS = 20
DEFAULT_GLOBAL_REQUEST_TIMEOUT_SECONDS = 90

# --- Chunking (spec.md §15) ---
DEFAULT_CHUNK_SIZE_TOKENS = 650
DEFAULT_CHUNK_OVERLAP_TOKENS = 75

# --- Embeddings (spec.md §33: must work fully offline) ---
# all-MiniLM-L6-v2: small (~80MB), fast on CPU, 384-dim, well-established
# default for local semantic search over personal documents/notes.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# --- Hybrid retrieval (spec.md §16) ---
DEFAULT_KEYWORD_WEIGHT = 0.5
DEFAULT_SEMANTIC_WEIGHT = 0.5
DEFAULT_TOP_K_KEYWORD = 20
DEFAULT_TOP_K_VECTOR = 20
DEFAULT_FINAL_TOP_K = 8
DEFAULT_MINIMUM_SCORE = 0.0

# --- Indexing (spec.md §14) ---
# Never index an entire drive by default.
DEFAULT_INDEXED_FOLDER_CANDIDATES = ("Desktop", "Documents", "Downloads")
DEFAULT_SUPPORTED_EXTENSIONS = (
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".json",
    ".html", ".py", ".java", ".js", ".ts", ".c", ".cpp", ".h", ".hpp",
)

# --- Web (spec.md §23, §44) ---
DEFAULT_WEB_FETCH_TIMEOUT_SECONDS = 15
DEFAULT_WEB_CACHE_TTL_SECONDS = 3600
DEFAULT_WEB_SEARCH_MAX_RESULTS = 8
DEFAULT_WEB_MAX_RESPONSE_BYTES = 5_000_000  # guard against pathologically large pages
DEFAULT_WEB_EXTRACTED_TEXT_MAX_CHARS = 20_000  # never hand a whole raw page to the LLM

# --- Reminders / scheduler ---
DEFAULT_REMINDER_POLL_INTERVAL_SECONDS = 30

# --- Persistent memory (spec.md §30) ---
# Injected into every turn's system prompt (agent/prompts.py) so a fact
# remembered in one conversation carries into later, unrelated ones. Capped
# rather than injecting everything ever remembered - keeps prompt size (and
# LLM cost - see llm/pricing.py) bounded as memories accumulate over time.
DEFAULT_MAX_INJECTED_MEMORIES = 30

# --- Conversation history ---
# How much of the first user message becomes a conversation's auto-title
# (storage/repositories/conversations.py), shown in ui/history.py's list.
DEFAULT_CONVERSATION_TITLE_MAX_CHARS = 60

# --- Global hotkey (spec.md §26) ---
DEFAULT_HOTKEY = "ctrl+space"

# --- Windows integration (spec.md §29, §57 Phase 6) ---
# Explicit allowlist for tools/windows.py's launch_application - the ONLY
# applications JARVIS can ever launch. Deliberately excludes shells/
# interpreters (cmd, powershell, wscript, ...) and anything that could be
# used as a stepping stone to arbitrary command execution - spec.md §29 is
# explicit that a general `os.system(user_string)`-style tool must never
# exist, and an allowlisted "shell" entry would just be that in disguise.
# Keys are what the LLM/user says; values are the exact executable resolved
# via PATH (subprocess.Popen([exe]), never a shell, never string-formatted
# from user input).
DEFAULT_APP_ALLOWLIST: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "wordpad": "wordpad.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "snipping tool": "SnippingTool.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
}

# --- Web (SearXNG auto-start, web/searxng_process.py) ---
# How long to wait, once SearXNG's process has been spawned, for it to
# actually become reachable before giving up and letting the search request
# that triggered the lazy start fail with the normal "unavailable" error.
# Live-measured real boot time was ~2s; this leaves generous headroom for a
# slower/cold-cache first start without making a stalled instance hang the
# triggering search indefinitely.
DEFAULT_SEARXNG_STARTUP_WAIT_SECONDS = 15.0

# --- Startup validation (spec.md §50) ---
# Keep this well under the perf budget for app startup (spec.md §42) - no
# live network calls here, just fast local checks. The one exception
# (SearXNG reachability) gets its own short timeout for exactly that reason.
DEFAULT_HEALTH_CHECK_WEB_TIMEOUT_SECONDS = 2.0

# --- Voice (spec.md §24, fully offline) ---
# faster-whisper "base": good speed/accuracy tradeoff on CPU for short
# personal-assistant commands; int8 compute keeps it light.
DEFAULT_WHISPER_MODEL_SIZE = "base"
DEFAULT_WHISPER_COMPUTE_TYPE = "int8"
DEFAULT_AUDIO_SAMPLE_RATE = 16000  # what we record at; matches Whisper's native rate
DEFAULT_PIPER_VOICE_NAME = "en_US-lessac-medium"

# Whisper-family models (local and Groq's hosted whisper-large-v3-turbo alike)
# were trained on huge amounts of YouTube caption data, where silent/near-
# silent clips are very often captioned "Thank you." or "Thanks for
# watching!". Fed near-silent audio, Whisper doesn't say "I don't know" - it
# confidently hallucinates one of those stock phrases. A push-to-talk tap
# that's too short, a quiet/wrong mic, or PortAudio's brief startup latency
# eating the first moment of speech all produce audio that's technically
# non-empty but has no real speech energy in it. Gate on that *before*
# calling any STT backend (voice/stt.py) rather than trusting the model to
# say so.
DEFAULT_MIN_SPEECH_RMS = 0.01  # float32 [-1,1] samples; typical room noise sits well below this
DEFAULT_MIN_SPEECH_DURATION_SECONDS = 0.3
