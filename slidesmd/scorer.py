"""Quality scorer for extraction results.

Produces a score in [0.0, 1.0] indicating how much useful content
an extractor managed to pull from a presentation file.
"""

from __future__ import annotations

from slidesmd.extractor import PresentationMeta

_GENERIC_TITLES = {"powerpoint presentation", "presentation", "untitled"}

# Weights (sum to 1.0)
_W_COMPLETENESS = 0.35
_W_DENSITY = 0.25
_W_COVERAGE = 0.20
_W_TITLE = 0.20

_DENSITY_BASELINE = 80  # expected minimum avg body chars for a "normal" slide


def score_extraction(meta: PresentationMeta) -> float:
    """Score the quality of an extraction result.

    Returns a float in [0.0, 1.0].  Higher means more content was
    successfully extracted.
    """
    if meta.slide_count == 0:
        return 0.0

    completeness = min(1.0, len(meta.slide_summaries) / meta.slide_count)

    if meta.slide_summaries:
        avg_body = sum(len(body) for _, body in meta.slide_summaries) / len(meta.slide_summaries)
    else:
        avg_body = 0.0
    density = min(1.0, avg_body / _DENSITY_BASELINE)

    coverage = min(1.0, len(meta.topics) / meta.slide_count)

    title_lower = meta.title.lower().strip()
    file_stem = meta.file_path.stem.replace("-", " ").replace("_", " ").lower().strip()
    title_quality = 0.0 if (title_lower in _GENERIC_TITLES or title_lower == file_stem) else 1.0

    return (
        _W_COMPLETENESS * completeness
        + _W_DENSITY * density
        + _W_COVERAGE * coverage
        + _W_TITLE * title_quality
    )
