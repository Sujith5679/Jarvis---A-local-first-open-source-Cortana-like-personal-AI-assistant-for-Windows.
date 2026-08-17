"""Typed row models mirroring the schema in `storage.migrations`.

These are plain dataclasses used by repositories (`storage/repositories/`) to
hand back typed objects instead of raw `sqlite3.Row`s. They are intentionally
simple — no ORM — so the mapping between schema and code stays obvious.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Conversation:
    id: int
    title: str | None
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: int
    conversation_id: int
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    tool_calls: str | None
    citations: str | None
    created_at: str


@dataclass
class IndexedFolder:
    id: int
    path: str
    enabled: bool
    added_at: str


@dataclass
class Document:
    id: int
    folder_id: int | None
    path: str
    filename: str
    source_type: str
    content_hash: str | None
    status: str  # "pending" | "indexed" | "failed" | "unsupported"
    error_message: str | None
    modified_at: str | None
    indexed_at: str | None
    created_at: str


@dataclass
class DocumentChunk:
    id: int
    document_id: int
    chunk_index: int
    text: str
    page: int | None
    section: str | None
    vector_id: str | None
    created_at: str


@dataclass
class Note:
    id: int
    title: str | None
    content: str
    tags: list[str] = field(default_factory=list)
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Task:
    id: int
    title: str
    description: str | None
    status: str  # "open" | "in_progress" | "completed" | "cancelled"
    priority: str  # "low" | "normal" | "high"
    due_at: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass
class Reminder:
    id: int
    title: str
    description: str | None
    trigger_at: str
    recurrence: str | None
    status: str  # "pending" | "fired" | "dismissed" | "completed"
    created_at: str
    completed_at: str | None


@dataclass
class Memory:
    id: int
    memory_type: str  # "working" | "episodic" | "preference" | "knowledge"
    content: str
    metadata: str | None
    created_at: str
    deletable: bool = True


@dataclass
class AuditEntry:
    id: int
    timestamp: str
    session_id: str | None
    action: str
    tool: str | None
    status: str
    risk_level: str | None
    input_summary: str | None
    result_summary: str | None
    error_code: str | None
    duration_ms: int | None
