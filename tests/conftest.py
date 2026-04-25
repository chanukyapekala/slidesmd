"""Shared fixtures for slidesmd tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesmd.extractor import PresentationMeta
from slidesmd.image_parser import ImageResult


@pytest.fixture()
def sample_meta(tmp_path: Path) -> PresentationMeta:
    """A minimal PresentationMeta for testing."""
    return PresentationMeta(
        title="Q3 Board Deck",
        file_path=tmp_path / "deck.pptx",
        slide_count=3,
        topics=["Financial Performance", "Roadmap", "Team Updates"],
        todos=["Action item: finalize forecast by Friday"],
        slide_summaries=[
            ("Financial Performance", "Revenue grew 15% YoY. EBITDA margins improved to 22%."),
            ("Roadmap", "Launch mobile app in Q4. Expand to EMEA market."),
            ("Team Updates", "Hired 5 new engineers. Attrition down to 8%."),
        ],
        image_results=[
            ("Financial Performance", ImageResult(method="ocr", text="Revenue chart 2024", confidence=85.0)),
        ],
    )


@pytest.fixture()
def second_meta(tmp_path: Path) -> PresentationMeta:
    """A second PresentationMeta for multi-file tests."""
    return PresentationMeta(
        title="Product Strategy",
        file_path=tmp_path / "strategy.pptx",
        slide_count=2,
        topics=["Vision", "Competitive Landscape"],
        todos=[],
        slide_summaries=[
            ("Vision", "Become the leading platform for AI-powered analytics."),
            ("Competitive Landscape", "Main competitors: Acme Corp, Beta Inc."),
        ],
        image_results=[],
    )
