from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.casefold())
    if not normalized:
        return set()
    chars = set(normalized)
    bigrams = {normalized[i : i + 2] for i in range(len(normalized) - 1)}
    words = set(re.findall(r"[a-z0-9_]{2,}", text.casefold()))
    return chars | bigrams | words


@dataclass(frozen=True, slots=True)
class Memory:
    id: int
    content: str
    importance: float
    created_at: str
    tags: tuple[str, ...]


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                summarized INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                tags TEXT NOT NULL DEFAULT '[]',
                source_session_id TEXT,
                created_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def add_message(self, session_id: str, role: str, content: str) -> int:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        cursor = self.connection.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content.strip(), _now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def recent_messages(self, session_id: str, limit: int = 16) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def add_memory(
        self,
        content: str,
        *,
        importance: float = 0.5,
        tags: Iterable[str] = (),
        source_session_id: str | None = None,
    ) -> int:
        content = content.strip()
        if not content:
            raise ValueError("memory content must not be empty")
        timestamp = _now()
        cursor = self.connection.execute(
            """INSERT INTO memories
               (content, importance, tags, source_session_id, created_at, last_accessed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                content,
                max(0.0, min(1.0, importance)),
                json.dumps(sorted(set(tags)), ensure_ascii=False),
                source_session_id,
                timestamp,
                timestamp,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def recall(self, query: str, limit: int = 5) -> list[Memory]:
        query_terms = _terms(query)
        if not query_terms:
            return []
        rows = self.connection.execute(
            "SELECT * FROM memories ORDER BY id DESC LIMIT 500"
        ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            memory_terms = _terms(row["content"] + " " + row["tags"])
            overlap = len(query_terms & memory_terms)
            if not overlap:
                continue
            similarity = overlap / math.sqrt(len(query_terms) * len(memory_terms))
            score = similarity * 0.8 + float(row["importance"]) * 0.2
            scored.append((score, row))
        chosen = sorted(scored, key=lambda item: (item[0], item[1]["id"]), reverse=True)[:limit]
        if chosen:
            ids = [row["id"] for _, row in chosen]
            placeholders = ",".join("?" for _ in ids)
            self.connection.execute(
                f"UPDATE memories SET last_accessed_at = ? WHERE id IN ({placeholders})",
                (_now(), *ids),
            )
            self.connection.commit()
        return [self._to_memory(row) for _, row in chosen]

    def list_memories(self, limit: int = 10) -> list[Memory]:
        rows = self.connection.execute(
            "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._to_memory(row) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        cursor = self.connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    def unsummarized_messages(self, session_id: str, limit: int) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT id, role, content FROM messages
               WHERE session_id = ? AND summarized = 0 ORDER BY id LIMIT ?""",
            (session_id, limit),
        ).fetchall()

    def mark_summarized(self, message_ids: Iterable[int]) -> None:
        ids = list(message_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.connection.execute(
            f"UPDATE messages SET summarized = 1 WHERE id IN ({placeholders})", ids
        )
        self.connection.commit()

    @staticmethod
    def _to_memory(row: sqlite3.Row) -> Memory:
        return Memory(
            id=int(row["id"]),
            content=str(row["content"]),
            importance=float(row["importance"]),
            created_at=str(row["created_at"]),
            tags=tuple(json.loads(row["tags"])),
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

