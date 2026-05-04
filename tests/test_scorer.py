"""Tests for the extraction quality scorer."""

from __future__ import annotations

from slidesmd.extractor import PresentationMeta
from slidesmd.scorer import score_extraction


class TestScoreExtraction:
    def test_good_extraction_scores_high(self, sample_meta):
        score = score_extraction(sample_meta)
        assert score > 0.7

    def test_empty_presentation_scores_zero(self, tmp_path):
        meta = PresentationMeta(
            title="Empty",
            file_path=tmp_path / "empty.pptx",
            slide_count=0,
        )
        assert score_extraction(meta) == 0.0

    def test_no_content_scores_low(self, tmp_path):
        meta = PresentationMeta(
            title="Presentation",  # generic
            file_path=tmp_path / "deck.pptx",
            slide_count=6,
            slide_summaries=[],
            topics=[],
        )
        score = score_extraction(meta)
        assert score < 0.1

    def test_partial_extraction(self, tmp_path):
        meta = PresentationMeta(
            title="Product Roadmap",
            file_path=tmp_path / "roadmap.pptx",
            slide_count=5,
            topics=["Vision", "Timeline", "Risks"],
            slide_summaries=[
                ("Vision", "Become the leading platform for analytics."),
                ("Timeline", "Launch in Q4."),
                ("Risks", "Main risk is competition."),
            ],
        )
        score = score_extraction(meta)
        assert 0.4 < score < 0.8

    def test_generic_title_penalized(self, tmp_path):
        good = PresentationMeta(
            title="Q3 Board Deck",
            file_path=tmp_path / "deck.pptx",
            slide_count=2,
            topics=["Intro", "Summary"],
            slide_summaries=[("Intro", "Welcome everyone."), ("Summary", "Done.")],
        )
        bad = PresentationMeta(
            title="PowerPoint Presentation",
            file_path=tmp_path / "deck.pptx",
            slide_count=2,
            topics=["Intro", "Summary"],
            slide_summaries=[("Intro", "Welcome everyone."), ("Summary", "Done.")],
        )
        assert score_extraction(good) > score_extraction(bad)

    def test_filename_fallback_title_penalized(self, tmp_path):
        meta = PresentationMeta(
            title="My Deck",
            file_path=tmp_path / "my_deck.pptx",
            slide_count=2,
            topics=["A", "B"],
            slide_summaries=[("A", "Content A."), ("B", "Content B.")],
        )
        score = score_extraction(meta)
        # title matches filename stem → title_quality = 0.0
        assert score < 0.7

    def test_dense_content_scores_higher(self, tmp_path):
        sparse = PresentationMeta(
            title="Deck",
            file_path=tmp_path / "a.pptx",
            slide_count=2,
            topics=["A", "B"],
            slide_summaries=[("A", "Hi."), ("B", "Bye.")],
        )
        dense = PresentationMeta(
            title="Deck",
            file_path=tmp_path / "a.pptx",
            slide_count=2,
            topics=["A", "B"],
            slide_summaries=[
                ("A", "Revenue grew 15% year-over-year to $42M. Subscription revenue increased 22%."),
                ("B", "Gross margin improved to 72%. EBITDA margin reached 22%. OpEx reduced by 5%."),
            ],
        )
        assert score_extraction(dense) > score_extraction(sparse)

    def test_score_capped_at_one(self, tmp_path):
        meta = PresentationMeta(
            title="Great Deck",
            file_path=tmp_path / "deck.pptx",
            slide_count=1,
            topics=["Topic1", "Topic2"],  # more topics than slides
            slide_summaries=[("Topic1", "x" * 200)],  # very dense
        )
        score = score_extraction(meta)
        assert score <= 1.0
