"""Extract metadata and to-dos from .pptx files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from slidesmd.image_parser import ImageResult, extract_images_from_slide, parse_image


@dataclass
class PresentationMeta:
    title: str
    file_path: Path
    slide_count: int
    topics: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    slide_summaries: list[tuple[str, str]] = field(default_factory=list)  # (title, body)
    image_results: list[tuple[str, ImageResult]] = field(default_factory=list)  # (slide_title, result)


@runtime_checkable
class SlideExtractor(Protocol):
    """Protocol for pluggable PPTX extraction backends."""

    def extract(self, path: Path) -> PresentationMeta:
        """Extract structured metadata from a presentation file."""
        ...


class PptxExtractor:
    """Default extractor backed by python-pptx."""

    def extract(self, path: Path) -> PresentationMeta:
        from pptx import Presentation  # deferred so the dep is optional

        prs = Presentation(path)
        return PresentationMeta(
            title=_extract_title(prs, path),
            file_path=path,
            slide_count=len(prs.slides),
            topics=_extract_topics(prs),
            todos=_extract_todos(prs),
            slide_summaries=_extract_slide_summaries(prs),
            image_results=_extract_images(prs),
        )


_default_extractor = PptxExtractor()


def extract(pptx_path: Path, extractor: SlideExtractor | None = None) -> PresentationMeta:
    """Extract metadata from a presentation file.

    Pass a custom *extractor* to use an alternative backend; defaults to
    PptxExtractor (python-pptx).
    """
    return (extractor or _default_extractor).extract(pptx_path)


# ---------------------------------------------------------------------------
# Internal helpers (python-pptx specific — used only by PptxExtractor)
# ---------------------------------------------------------------------------

def _placeholder_idx(shape: object) -> int | None:
    """Return placeholder index or None if shape is not a placeholder."""
    try:
        fmt = shape.placeholder_format  # type: ignore[attr-defined]
        return fmt.idx if fmt is not None else None
    except Exception:
        return None


_GENERIC_TITLES = {"powerpoint presentation", "presentation", "untitled"}


def _first_slide_title(prs: object) -> str:
    try:
        slides = prs.slides  # type: ignore[attr-defined]
    except AttributeError:
        return ""
    if slides:
        for shape in slides[0].shapes:
            if _placeholder_idx(shape) == 0 and shape.has_text_frame:
                return shape.text_frame.text.strip()
    return ""


def _extract_title(prs: object, fallback: Path) -> str:
    """Use core properties title unless it's generic, then prefer first slide title."""
    core_title = (prs.core_properties.title or "").strip()  # type: ignore[attr-defined]
    if core_title and core_title.lower() not in _GENERIC_TITLES:
        return core_title

    slide_title = _first_slide_title(prs)
    if slide_title:
        return slide_title

    if core_title:
        return core_title

    return fallback.stem.replace("-", " ").replace("_", " ").title()


def _extract_topics(prs: object) -> list[str]:
    """Extract slide titles as topic list."""
    topics: list[str] = []
    for slide in prs.slides:  # type: ignore[attr-defined]
        for shape in slide.shapes:
            if _placeholder_idx(shape) == 0 and shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    topics.append(text)
    return topics


def _extract_slide_summaries(prs: object) -> list[tuple[str, str]]:
    """Extract (slide_title, body_text) for each slide."""
    summaries = []
    for slide in prs.slides:  # type: ignore[attr-defined]
        slide_title = ""
        body_parts: list[str] = []

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            idx = _placeholder_idx(shape)
            text = shape.text_frame.text.strip()
            if not text:
                continue
            if idx == 0:
                slide_title = text
            else:
                body_parts.append(text)

        body = " · ".join(body_parts)
        if slide_title or body:
            summaries.append((slide_title, body))

    return summaries


def _extract_images(prs: object) -> list[tuple[str, ImageResult]]:
    """Extract and parse images from all slides."""
    results = []
    for slide in prs.slides:  # type: ignore[attr-defined]
        slide_title = ""
        for shape in slide.shapes:
            if _placeholder_idx(shape) == 0 and shape.has_text_frame:
                slide_title = shape.text_frame.text.strip()
                break

        for image in extract_images_from_slide(slide):
            result = parse_image(image, slide_title)
            if result.method != "skipped":
                results.append((slide_title, result))

    return results


def _extract_todos(prs: object) -> list[str]:
    """Extract lines containing TODO, Action, or follow-up keywords."""
    keywords = ("todo", "action item", "follow up", "follow-up", "next step", "to-do")
    todos: list[str] = []

    for slide in prs.slides:  # type: ignore[attr-defined]
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                text = para.text.strip()
                if any(kw in text.lower() for kw in keywords):
                    todos.append(text)

    return todos
