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

# --- Global hotkey (spec.md §26) ---
DEFAULT_HOTKEY = "ctrl+space"

# --- Voice (spec.md §24, fully offline) ---
# faster-whisper "base": good speed/accuracy tradeoff on CPU for short
# personal-assistant commands; int8 compute keeps it light.
DEFAULT_WHISPER_MODEL_SIZE = "base"
DEFAULT_WHISPER_COMPUTE_TYPE = "int8"
DEFAULT_AUDIO_SAMPLE_RATE = 16000  # what we record at; matches Whisper's native rate
DEFAULT_PIPER_VOICE_NAME = "en_US-lessac-medium"
