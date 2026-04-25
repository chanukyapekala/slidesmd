"""SQLite + numpy vector store for slide embeddings.

Uses plain SQLite for storage (no extensions required) and numpy for
cosine similarity search. This keeps the dependency footprint small
and avoids the macOS/pyenv sqlite3 extension-loading issues.
"""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


@dataclass
class ChunkRecord:
    """A stored chunk with its metadata."""

    id: int
    file_path: str
    slide_index: int
    slide_title: str
    chunk_text: str
    chunk_index: int
    file_mtime: float


@dataclass
class SearchResult:
    """A chunk matched by vector similarity."""

    distance: float
    chunk: ChunkRecord


def _db_path(folder: Path) -> Path:
    return folder / ".slidesmd" / "embeddings.db"


def _connect(folder: Path) -> sqlite3.Connection:
    db = _db_path(folder)
    db.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path   TEXT NOT NULL,
            slide_index INTEGER NOT NULL,
            slide_title TEXT,
            chunk_text  TEXT NOT NULL,
            chunk_index INTEGER DEFAULT 0,
            file_mtime  REAL NOT NULL,
            embedding   BLOB NOT NULL,
            UNIQUE(file_path, slide_index, chunk_index)
        );
        """
    )
    conn.commit()


def open_store(folder: Path) -> sqlite3.Connection:
    """Open (or create) the vector store for *folder* and return a connection."""
    conn = _connect(folder)
    ensure_schema(conn)
    return conn


def delete_file_chunks(conn: sqlite3.Connection, file_path: str) -> None:
    """Remove all chunks for a given file."""
    conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
    conn.commit()


def insert_chunks(
    conn: sqlite3.Connection,
    file_path: str,
    file_mtime: float,
    chunks: list[tuple[int, str, str, int]],  # (slide_index, slide_title, text, chunk_index)
    embeddings: list[list[float]],
) -> None:
    """Insert chunks and their embeddings into the store."""
    for (slide_index, slide_title, text, chunk_index), embedding in zip(
        chunks, embeddings
    ):
        conn.execute(
            """
            INSERT INTO chunks (file_path, slide_index, slide_title, chunk_text, chunk_index, file_mtime, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (file_path, slide_index, slide_title, text, chunk_index, file_mtime, _serialize_vec(embedding)),
        )
    conn.commit()


def search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[SearchResult]:
    """Return the *top_k* closest chunks to *query_embedding* by cosine distance."""
    rows = conn.execute(
        "SELECT id, file_path, slide_index, slide_title, chunk_text, chunk_index, file_mtime, embedding FROM chunks"
    ).fetchall()

    if not rows:
        return []

    query_vec = np.array(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []
    query_vec = query_vec / query_norm

    scored: list[tuple[float, ChunkRecord]] = []
    for row in rows:
        chunk = ChunkRecord(
            id=row[0],
            file_path=row[1],
            slide_index=row[2],
            slide_title=row[3],
            chunk_text=row[4],
            chunk_index=row[5],
            file_mtime=row[6],
        )
        vec = _deserialize_vec(row[7])
        vec_norm = np.linalg.norm(vec)
        if vec_norm == 0:
            continue
        similarity = float(np.dot(query_vec, vec / vec_norm))
        distance = 1.0 - similarity  # cosine distance
        scored.append((distance, chunk))

    scored.sort(key=lambda x: x[0])
    return [
        SearchResult(distance=d, chunk=c)
        for d, c in scored[:top_k]
    ]


def get_stored_mtime(conn: sqlite3.Connection, file_path: str) -> float | None:
    """Return the stored mtime for a file, or None if not indexed."""
    row = conn.execute(
        "SELECT file_mtime FROM chunks WHERE file_path = ? LIMIT 1",
        (file_path,),
    ).fetchone()
    return row[0] if row else None


def _serialize_vec(vec: list[float]) -> bytes:
    """Serialize a float list to bytes."""
    return struct.pack(f"{len(vec)}f", *vec)


def _deserialize_vec(data: bytes) -> np.ndarray:
    """Deserialize bytes back to a numpy array."""
    count = len(data) // 4
    return np.array(struct.unpack(f"{count}f", data), dtype=np.float32)
