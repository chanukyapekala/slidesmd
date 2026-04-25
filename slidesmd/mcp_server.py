"""MCP server exposing SlidesMD capabilities as tools."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastmcp import FastMCP

from slidesmd import embedder, querier
from slidesmd.extractor import PresentationMeta, extract
from slidesmd.indexer import build_index

mcp = FastMCP("slidesmd")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_folder(folder: Path) -> tuple[list[PresentationMeta], list[str]]:
    """Extract all .pptx in folder. Returns (presentations, error_messages)."""
    presentations: list[PresentationMeta] = []
    errors: list[str] = []
    for f in folder.rglob("*.pptx"):
        try:
            presentations.append(extract(f))
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    return presentations, errors


def _compact(meta: PresentationMeta) -> str:
    todo_part = f", {len(meta.todos)} todo{'s' if len(meta.todos) != 1 else ''}" if meta.todos else ""
    return f"{meta.title} ({meta.slide_count} slides{todo_part})"


def _detailed(meta: PresentationMeta) -> str:
    lines = [
        f"## {meta.title}",
        f"File: {meta.file_path.name}",
        f"Slides: {meta.slide_count}",
    ]
    if meta.topics:
        lines.append(f"Topics: {', '.join(meta.topics[:5])}")
    if meta.todos:
        lines.append("To-dos:")
        lines += [f"  - {t}" for t in meta.todos]
    if meta.slide_summaries:
        lines.append("Content:")
        for title, body in meta.slide_summaries:
            heading = title or "Untitled"
            lines.append(f"  [{heading}]: {body}" if body else f"  [{heading}]")
    return "\n".join(lines)


def _search_snippets(meta: PresentationMeta, q: str) -> list[str]:
    """Return matching snippets for a lowercase keyword q."""
    snippets: list[str] = []
    if q in meta.title.lower():
        snippets.append(f"Title: {meta.title}")
    for topic in meta.topics:
        if q in topic.lower():
            snippets.append(f"Topic: {topic}")
    for todo in meta.todos:
        if q in todo.lower():
            snippets.append(f"Todo: {todo}")
    for slide_title, body in meta.slide_summaries:
        if q in f"{slide_title} {body}".lower():
            heading = slide_title or "Untitled"
            excerpt = body[:120] + ("..." if len(body) > 120 else "")
            snippets.append(f"Slide [{heading}]: {excerpt}")
    return snippets


def _filter_to_relevant(
    presentations: list[PresentationMeta], question: str
) -> list[PresentationMeta]:
    """Narrow slide summaries to those containing question keywords.

    Reduces Ollama context size without discarding whole presentations.
    Falls back to all content if nothing matches.
    """
    keywords = [w for w in question.lower().split() if len(w) > 3]
    if not keywords:
        return presentations

    filtered: list[PresentationMeta] = []
    for meta in presentations:
        full_text = " ".join(
            [meta.title, *meta.topics, *meta.todos]
            + [f"{t} {b}" for t, b in meta.slide_summaries]
        ).lower()
        if not any(k in full_text for k in keywords):
            continue
        relevant_slides = [
            (t, b)
            for t, b in meta.slide_summaries
            if any(k in f"{t} {b}".lower() for k in keywords)
        ] or meta.slide_summaries
        filtered.append(dataclasses.replace(meta, slide_summaries=relevant_slides))

    return filtered or presentations


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def index_folder(folder: str, detailed: bool = False) -> str:
    """Index all PowerPoint presentations in a folder and write agents.md.

    detailed=False: compact summary (title, slide count, todo count).
    detailed=True: full slide-by-slide content per presentation.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        return f"Folder not found: {folder}"

    presentations, errors = _load_folder(folder_path)
    if not presentations:
        return "No .pptx files found."

    build_index(presentations, folder_path)

    lines = [f"{len(presentations)} presentation(s) indexed in {folder_path.name}/"]
    for meta in sorted(presentations, key=lambda m: m.title.lower()):
        if detailed:
            lines += ["", _detailed(meta)]
        else:
            lines.append(f"- {_compact(meta)}")

    if errors:
        lines.append(f"\n{len(errors)} file(s) skipped: {'; '.join(errors)}")

    return "\n".join(lines)


@mcp.tool()
def search_presentations(folder: str, query: str, detailed: bool = False) -> str:
    """Search presentations by keyword across titles, topics, todos, and slide content.

    detailed=False: first match snippet per presentation + overflow count.
    detailed=True: all matching snippets per presentation.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        return f"Folder not found: {folder}"

    presentations, _ = _load_folder(folder_path)
    if not presentations:
        return "No .pptx files found."

    q = query.lower()
    results = [
        (meta, snippets)
        for meta in presentations
        if (snippets := _search_snippets(meta, q))
    ]

    if not results:
        return f"No matches for '{query}'."

    lines = [f"{len(results)} presentation(s) match '{query}':"]
    for meta, snippets in results:
        lines.append(f"\n{meta.title} ({meta.file_path.name})")
        if detailed:
            lines += [f"  {s}" for s in snippets]
        else:
            overflow = f" (+{len(snippets) - 1} more)" if len(snippets) > 1 else ""
            lines.append(f"  {snippets[0]}{overflow}")

    return "\n".join(lines)


@mcp.tool()
def get_presentation(file_path: str, detailed: bool = False) -> str:
    """Get metadata for a single presentation file.

    detailed=False: title, slide count, topics, todo count.
    detailed=True: full slide-by-slide content.
    """
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    try:
        meta = extract(path)
    except Exception as e:
        return f"Failed to extract {path.name}: {e}"

    if detailed:
        return _detailed(meta)

    lines = [meta.title, f"File: {path.name}", f"Slides: {meta.slide_count}"]
    if meta.topics:
        lines.append(f"Topics: {', '.join(meta.topics[:5])}")
    if meta.todos:
        lines.append(f"To-dos: {len(meta.todos)}")
    return "\n".join(lines)


@mcp.tool()
def query_content(
    target: str,
    question: str,
    model: str = querier.DEFAULT_MODEL,
    detailed: bool = False,
) -> str:
    """Query presentation content using a local Ollama model.

    target: path to a single .pptx file OR a folder of presentations.
    Relevant slides are pre-filtered by keyword to keep context lean.

    detailed=False: answer only.
    detailed=True: answer + source slide excerpts used.
    """
    if not querier.is_available():
        return (
            "Ollama not available. "
            "Install: pip install ollama — then start the server: ollama serve"
        )

    target_path = Path(target)
    if not target_path.exists():
        return f"Not found: {target}"

    if target_path.is_file():
        try:
            presentations = [extract(target_path)]
        except Exception as e:
            return f"Failed to extract {target_path.name}: {e}"
    else:
        presentations, _ = _load_folder(target_path)
        if not presentations:
            return "No .pptx files found."

    relevant = _filter_to_relevant(presentations, question)

    try:
        answer = "".join(querier.query(relevant, question, model=model))
    except RuntimeError as e:
        return str(e)

    if detailed:
        context = querier.build_context(relevant)
        return f"{answer}\n\n---\nSource context:\n{context}"

    return answer


@mcp.tool()
def embed_folder(folder: str) -> str:
    """Build or update the semantic embedding index for all presentations in a folder.

    Uses sentence-transformers (all-MiniLM-L6-v2) and SQLite.
    Only re-embeds files that have changed since the last index.
    Must be called before semantic_search.
    """
    if not embedder.is_available():
        return (
            "Semantic search dependencies not installed. "
            "Run: pip install slidesmd[semantic]"
        )

    folder_path = Path(folder)
    if not folder_path.exists():
        return f"Folder not found: {folder}"

    indexed, skipped = embedder.index_folder(folder_path)
    return f"Embedding index updated: {indexed} file(s) indexed, {skipped} skipped (unchanged or failed)."


@mcp.tool()
def semantic_search(folder: str, query: str, top_k: int = 5) -> str:
    """Search slides by meaning using vector similarity.

    Returns the top_k most relevant slide chunks ranked by semantic similarity.
    Requires embed_folder to have been run first.
    """
    if not embedder.is_available():
        return (
            "Semantic search dependencies not installed. "
            "Run: pip install slidesmd[semantic]"
        )

    folder_path = Path(folder)
    if not folder_path.exists():
        return f"Folder not found: {folder}"

    results = embedder.search(folder_path, query, top_k=top_k)
    if not results:
        return f"No results for '{query}'. Have you run embed_folder first?"

    lines = [f"Top {len(results)} results for '{query}':\n"]
    for i, r in enumerate(results, 1):
        c = r.chunk
        score = max(0.0, 1.0 - r.distance)  # convert distance to similarity
        source = Path(c.file_path).name
        lines.append(f"{i}. [{source} — Slide {c.slide_index + 1}] (score: {score:.2f})")
        lines.append(f"   {c.chunk_text[:200]}{'...' if len(c.chunk_text) > 200 else ''}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()