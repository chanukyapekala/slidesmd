"""Tests for the SQLite + numpy vector store."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from slidesmd import vector_store


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestSerializeVec:
    def test_roundtrip(self):
        vec = [1.0, 2.0, 3.0]
        raw = vector_store._serialize_vec(vec)
        result = vector_store._deserialize_vec(raw)
        np.testing.assert_array_almost_equal(result, vec)

    def test_correct_byte_length(self):
        vec = [0.0] * 384
        raw = vector_store._serialize_vec(vec)
        assert len(raw) == 384 * 4  # 4 bytes per float32


class TestChunkRecord:
    def test_fields(self):
        rec = vector_store.ChunkRecord(
            id=1,
            file_path="/tmp/deck.pptx",
            slide_index=0,
            slide_title="Intro",
            chunk_text="Hello",
            chunk_index=0,
            file_mtime=1000.0,
        )
        assert rec.file_path == "/tmp/deck.pptx"
        assert rec.slide_index == 0


class TestSearchResult:
    def test_fields(self):
        chunk = vector_store.ChunkRecord(
            id=1,
            file_path="/tmp/deck.pptx",
            slide_index=0,
            slide_title="Intro",
            chunk_text="Hello",
            chunk_index=0,
            file_mtime=1000.0,
        )
        result = vector_store.SearchResult(distance=0.25, chunk=chunk)
        assert result.distance == 0.25
        assert result.chunk.chunk_text == "Hello"


# ---------------------------------------------------------------------------
# Integration tests (plain SQLite — no extensions needed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path):
    """Open a vector store in a temp directory."""
    conn = vector_store.open_store(tmp_path)
    yield conn
    conn.close()


class TestSchema:
    def test_creates_table(self, store):
        tables = {
            row[0]
            for row in store.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "chunks" in tables

    def test_idempotent(self, store):
        vector_store.ensure_schema(store)


class TestInsertAndSearch:
    def test_insert_and_retrieve(self, store):
        dim = vector_store.EMBEDDING_DIM
        chunks = [(0, "Intro", "Hello world", 0)]
        embeddings = [[1.0] + [0.0] * (dim - 1)]

        vector_store.insert_chunks(store, "/tmp/a.pptx", 1000.0, chunks, embeddings)

        results = vector_store.search(store, [1.0] + [0.0] * (dim - 1), top_k=1)
        assert len(results) == 1
        assert results[0].chunk.chunk_text == "Hello world"
        assert results[0].chunk.file_path == "/tmp/a.pptx"
        assert results[0].distance == pytest.approx(0.0, abs=1e-6)

    def test_cosine_ranking(self, store):
        dim = vector_store.EMBEDDING_DIM
        chunks = [
            (0, "A", "close match", 0),
            (1, "B", "far match", 0),
        ]
        # first chunk is very similar to query, second is orthogonal
        embeddings = [
            [1.0, 0.1] + [0.0] * (dim - 2),
            [0.0, 1.0] + [0.0] * (dim - 2),
        ]
        vector_store.insert_chunks(store, "/tmp/a.pptx", 1000.0, chunks, embeddings)

        query = [1.0, 0.0] + [0.0] * (dim - 2)
        results = vector_store.search(store, query, top_k=2)
        assert len(results) == 2
        assert results[0].chunk.chunk_text == "close match"
        assert results[1].chunk.chunk_text == "far match"
        assert results[0].distance < results[1].distance

    def test_delete_file_chunks(self, store):
        dim = vector_store.EMBEDDING_DIM
        chunks = [(0, "A", "text a", 0), (1, "B", "text b", 0)]
        embeddings = [[1.0] + [0.0] * (dim - 1), [0.0, 1.0] + [0.0] * (dim - 2)]

        vector_store.insert_chunks(store, "/tmp/a.pptx", 1000.0, chunks, embeddings)
        count = store.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 2

        vector_store.delete_file_chunks(store, "/tmp/a.pptx")
        count = store.execute("SELECT count(*) FROM chunks").fetchone()[0]
        assert count == 0

    def test_search_empty_store(self, store):
        dim = vector_store.EMBEDDING_DIM
        results = vector_store.search(store, [1.0] + [0.0] * (dim - 1), top_k=5)
        assert results == []


class TestStoredMtime:
    def test_returns_none_when_not_indexed(self, store):
        assert vector_store.get_stored_mtime(store, "/tmp/missing.pptx") is None

    def test_returns_mtime_after_insert(self, store):
        dim = vector_store.EMBEDDING_DIM
        vector_store.insert_chunks(
            store, "/tmp/a.pptx", 1234.5,
            [(0, "A", "text", 0)],
            [[0.1] * dim],
        )
        assert vector_store.get_stored_mtime(store, "/tmp/a.pptx") == 1234.5
