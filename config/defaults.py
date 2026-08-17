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

# --- Agent loop guardrails (spec.md §12) ---
DEFAULT_MAX_TOOL_STEPS = 8
DEFAULT_MAX_REASONING_ITERATIONS = 6
DEFAULT_TOOL_TIMEOUT_SECONDS = 20
DEFAULT_GLOBAL_REQUEST_TIMEOUT_SECONDS = 90

# --- Chunking (spec.md §15) ---
DEFAULT_CHUNK_SIZE_TOKENS = 650
DEFAULT_CHUNK_OVERLAP_TOKENS = 75

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

# --- Reminders / scheduler ---
DEFAULT_REMINDER_POLL_INTERVAL_SECONDS = 30

# --- Global hotkey (spec.md §26) ---
DEFAULT_HOTKEY = "ctrl+space"
