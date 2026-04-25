"""Embedding pipeline — chunking slides and building the vector index."""

from __future__ import annotations

from pathlib import Path

from slidesmd.extractor import PresentationMeta, extract
from slidesmd import vector_store

_ST_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer

    _ST_AVAILABLE = True
except ImportError:
    pass

MODEL_NAME = "all-MiniLM-L6-v2"
MAX_CHUNK_TOKENS = 256  # approx word count threshold for sub-chunking

_model_cache: SentenceTransformer | None = None


def is_available() -> bool:
    return _ST_AVAILABLE


def _get_model() -> SentenceTransformer:
    global _model_cache
    if _model_cache is None:
        if not _ST_AVAILABLE:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            )
        _model_cache = SentenceTransformer(MODEL_NAME)
    return _model_cache


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_slide(
    presentation_title: str,
    slide_index: int,
    slide_title: str,
    body: str,
    image_texts: list[str],
) -> list[str]:
    """Build one or more text chunks for a single slide.

    Returns a list — usually one element unless the slide is unusually long.
    """
    prefix = f"[Presentation: \"{presentation_title}\"] [Slide {slide_index + 1}: \"{slide_title or 'Untitled'}\"]"
    parts = [body] if body else []
    parts.extend(image_texts)
    content = "\n".join(parts).strip()

    if not content:
        return [prefix]

    full = f"{prefix}\n{content}"

    # rough token estimate (words)
    if len(full.split()) <= MAX_CHUNK_TOKENS:
        return [full]

    # sub-chunk at sentence boundaries
    sentences = content.replace("\n", " ").split(". ")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent.split())
        if current and current_len + sent_len > MAX_CHUNK_TOKENS:
            chunks.append(f"{prefix}\n{'. '.join(current)}.")
            current = []
            current_len = 0
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(f"{prefix}\n{'. '.join(current)}")

    return chunks


def chunks_from_presentation(
    meta: PresentationMeta,
) -> list[tuple[int, str, str, int]]:
    """Convert a PresentationMeta into indexable chunks.

    Returns list of (slide_index, slide_title, chunk_text, chunk_index).
    """
    # build a map of image texts per slide title for merging
    image_map: dict[str, list[str]] = {}
    for slide_title, img in meta.image_results:
        if img.text:
            image_map.setdefault(slide_title, []).append(img.text)

    all_chunks: list[tuple[int, str, str, int]] = []

    for slide_index, (slide_title, body) in enumerate(meta.slide_summaries):
        image_texts = image_map.get(slide_title, [])
        texts = _chunk_slide(
            meta.title, slide_index, slide_title, body, image_texts
        )
        for chunk_index, text in enumerate(texts):
            all_chunks.append((slide_index, slide_title, text, chunk_index))

    return all_chunks


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using the sentence-transformers model."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return [e.tolist() for e in embeddings]


def index_folder(folder: Path) -> tuple[int, int]:
    """Build or update the embedding index for all .pptx in *folder*.

    Returns (indexed_count, skipped_count).
    """
    conn = vector_store.open_store(folder)
    indexed = 0
    skipped = 0

    for pptx in sorted(folder.rglob("*.pptx")):
        file_key = str(pptx)
        current_mtime = pptx.stat().st_mtime

        stored_mtime = vector_store.get_stored_mtime(conn, file_key)
        if stored_mtime is not None and stored_mtime >= current_mtime:
            skipped += 1
            continue

        try:
            meta = extract(pptx)
        except Exception:
            skipped += 1
            continue

        chunks = chunks_from_presentation(meta)
        if not chunks:
            skipped += 1
            continue

        texts = [c[2] for c in chunks]
        embeddings = embed_texts(texts)

        # replace old data for this file
        vector_store.delete_file_chunks(conn, file_key)
        vector_store.insert_chunks(conn, file_key, current_mtime, chunks, embeddings)
        indexed += 1

    conn.close()
    return indexed, skipped


def search(
    folder: Path,
    query: str,
    top_k: int = 5,
) -> list[vector_store.SearchResult]:
    """Semantic search across indexed presentations in *folder*."""
    conn = vector_store.open_store(folder)
    query_embedding = embed_texts([query])[0]
    results = vector_store.search(conn, query_embedding, top_k=top_k)
    conn.close()
    return results
