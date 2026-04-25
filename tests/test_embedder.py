"""Tests for the embedding pipeline (chunking + indexing)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from slidesmd.embedder import (
    MAX_CHUNK_TOKENS,
    _chunk_slide,
    chunks_from_presentation,
)
from slidesmd.extractor import PresentationMeta


# ---------------------------------------------------------------------------
# Chunking unit tests (no dependencies needed)
# ---------------------------------------------------------------------------


class TestChunkSlide:
    def test_basic_slide(self):
        chunks = _chunk_slide("Deck", 0, "Intro", "Hello world", [])
        assert len(chunks) == 1
        assert '[Presentation: "Deck"]' in chunks[0]
        assert '[Slide 1: "Intro"]' in chunks[0]
        assert "Hello world" in chunks[0]

    def test_empty_body_still_produces_chunk(self):
        chunks = _chunk_slide("Deck", 0, "Title Only", "", [])
        assert len(chunks) == 1
        assert "Title Only" in chunks[0]

    def test_image_text_included(self):
        chunks = _chunk_slide("Deck", 0, "Charts", "Some text", ["Revenue chart 2024"])
        assert len(chunks) == 1
        assert "Revenue chart 2024" in chunks[0]
        assert "Some text" in chunks[0]

    def test_untitled_slide(self):
        chunks = _chunk_slide("Deck", 2, "", "Body content", [])
        assert len(chunks) == 1
        assert "Untitled" in chunks[0]

    def test_long_slide_sub_chunked(self):
        long_body = ". ".join(["This is a moderately long sentence number " + str(i) for i in range(100)])
        chunks = _chunk_slide("Deck", 0, "Long", long_body, [])
        assert len(chunks) > 1
        for chunk in chunks:
            assert '[Presentation: "Deck"]' in chunk


class TestChunksFromPresentation:
    def test_produces_chunks_for_each_slide(self, sample_meta):
        chunks = chunks_from_presentation(sample_meta)
        # 3 slides, each short enough for 1 chunk
        assert len(chunks) == 3
        # each chunk is (slide_index, slide_title, text, chunk_index)
        assert chunks[0][0] == 0  # slide_index
        assert chunks[0][1] == "Financial Performance"
        assert chunks[0][3] == 0  # chunk_index

    def test_image_text_merged(self, sample_meta):
        chunks = chunks_from_presentation(sample_meta)
        # first slide has an image result
        assert "Revenue chart 2024" in chunks[0][2]

    def test_empty_presentation(self, tmp_path):
        meta = PresentationMeta(
            title="Empty",
            file_path=tmp_path / "empty.pptx",
            slide_count=0,
            slide_summaries=[],
        )
        chunks = chunks_from_presentation(meta)
        assert chunks == []


# ---------------------------------------------------------------------------
# Integration tests (mock sentence-transformers, real SQLite)
# ---------------------------------------------------------------------------


class TestIndexFolder:
    @patch("slidesmd.embedder._ST_AVAILABLE", True)
    @patch("slidesmd.embedder.embed_texts")
    @patch("slidesmd.embedder.extract")
    def test_index_folder_indexes_new_file(
        self, mock_extract, mock_embed, sample_meta, tmp_path
    ):
        pptx = tmp_path / "deck.pptx"
        pptx.touch()

        mock_extract.return_value = sample_meta
        mock_embed.return_value = [[0.1] * 384 for _ in range(3)]

        from slidesmd.embedder import index_folder

        indexed, skipped = index_folder(tmp_path)

        assert indexed == 1
        assert skipped == 0
        mock_embed.assert_called_once()
        mock_extract.assert_called_once()

    @patch("slidesmd.embedder._ST_AVAILABLE", True)
    @patch("slidesmd.embedder.embed_texts")
    @patch("slidesmd.embedder.extract")
    def test_skips_unchanged_file(
        self, mock_extract, mock_embed, sample_meta, tmp_path
    ):
        pptx = tmp_path / "deck.pptx"
        pptx.touch()

        # first index
        mock_extract.return_value = sample_meta
        mock_embed.return_value = [[0.1] * 384 for _ in range(3)]

        from slidesmd.embedder import index_folder

        index_folder(tmp_path)
        mock_extract.reset_mock()
        mock_embed.reset_mock()

        # second index — file unchanged
        indexed, skipped = index_folder(tmp_path)

        assert indexed == 0
        assert skipped == 1
        mock_embed.assert_not_called()
        mock_extract.assert_not_called()

    @patch("slidesmd.embedder._ST_AVAILABLE", True)
    @patch("slidesmd.embedder.embed_texts")
    @patch("slidesmd.embedder.extract")
    def test_reindexes_modified_file(
        self, mock_extract, mock_embed, sample_meta, tmp_path
    ):
        import os
        import time

        pptx = tmp_path / "deck.pptx"
        pptx.touch()

        mock_extract.return_value = sample_meta
        mock_embed.return_value = [[0.1] * 384 for _ in range(3)]

        from slidesmd.embedder import index_folder

        index_folder(tmp_path)
        mock_extract.reset_mock()
        mock_embed.reset_mock()

        # touch file to change mtime
        time.sleep(0.05)
        os.utime(pptx, None)

        mock_extract.return_value = sample_meta
        mock_embed.return_value = [[0.2] * 384 for _ in range(3)]

        indexed, skipped = index_folder(tmp_path)

        assert indexed == 1
        assert skipped == 0
        mock_embed.assert_called_once()
