"""Query slide content using a local Ollama model."""

from __future__ import annotations

from typing import Iterator

from slidesmd.extractor import PresentationMeta

_OLLAMA_AVAILABLE = False

try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    pass

DEFAULT_MODEL = "llama3"

_SYSTEM_PROMPT = (
    "You are an expert analyst for PowerPoint presentations. "
    "Answer questions using only the slide content provided. "
    "Cite slide titles when relevant. Be concise and accurate."
)


def is_available() -> bool:
    return _OLLAMA_AVAILABLE


def build_context(presentations: list[PresentationMeta]) -> str:
    """Format extracted presentation data into an LLM-readable context block."""
    parts: list[str] = []

    for meta in presentations:
        parts.append(f"## Presentation: {meta.title} ({meta.slide_count} slides)")
        parts.append(f"File: {meta.file_path.name}")
        parts.append("")

        for slide_title, body in meta.slide_summaries:
            heading = slide_title or "Untitled Slide"
            parts.append(f"### Slide: {heading}")
            if body:
                parts.append(body)

        for slide_title, img in meta.image_results:
            context = f"[Image on '{slide_title}'" if slide_title else "[Image"
            parts.append(f"{context}: {img.text}]")

        if meta.todos:
            parts.append("")
            parts.append("**Action items / To-dos:**")
            for todo in meta.todos:
                parts.append(f"- {todo}")

        parts.append("")

    return "\n".join(parts)


def query(
    presentations: list[PresentationMeta],
    question: str,
    model: str = DEFAULT_MODEL,
) -> Iterator[str]:
    """Stream answer tokens for *question* against the slide content.

    Raises RuntimeError if Ollama is not installed or not reachable.
    """
    if not _OLLAMA_AVAILABLE:
        raise RuntimeError(
            "ollama package is not installed. Run: pip install ollama"
        )

    context = build_context(presentations)
    user_message = f"{context}\n\n---\n\nQuestion: {question}"

    try:
        stream = _ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            stream=True,
        )
        for chunk in stream:
            token = chunk["message"]["content"]
            if token:
                yield token
    except Exception as exc:
        raise RuntimeError(
            f"Ollama error: {exc}\n"
            "Make sure Ollama is running (`ollama serve`) and the model is pulled "
            f"(`ollama pull {model}`)."
        ) from exc
