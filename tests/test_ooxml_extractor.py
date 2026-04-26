"""Tests for the pure-stdlib OOXML extractor.

Tests build synthetic .pptx files (ZIP of XML) to verify parsing
without needing real presentation files.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from slidesmd.ooxml_extractor import OoxmlExtractor


# ---------------------------------------------------------------------------
# Helpers — build minimal OOXML .pptx archives
# ---------------------------------------------------------------------------

_CORE_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
    xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>{title}</dc:title>
</cp:coreProperties>
"""

_SLIDE_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      {shapes}
    </p:spTree>
  </p:cSld>
</p:sld>
"""

_NOTES_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
         xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:notes>
"""


def _title_shape(text: str) -> str:
    return f"""\
      <p:sp>
        <p:nvSpPr><p:cNvPr id="1" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
        <p:txBody>
          <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>"""


def _body_shape(text: str) -> str:
    return f"""\
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Content"/><p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr>
        <p:txBody>
          <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>"""


def _make_synthetic_pptx(
    path: Path,
    title: str,
    slides: list[tuple[str, str]],
    notes: dict[int, str] | None = None,
) -> Path:
    """Build a minimal .pptx ZIP with given content."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("docProps/core.xml", _CORE_XML_TEMPLATE.format(title=title))
        for i, (slide_title, body) in enumerate(slides, 1):
            shapes = ""
            if slide_title:
                shapes += _title_shape(slide_title)
            if body:
                shapes += _body_shape(body)
            zf.writestr(f"ppt/slides/slide{i}.xml", _SLIDE_XML_TEMPLATE.format(shapes=shapes))

        if notes:
            for slide_num, note_text in notes.items():
                zf.writestr(
                    f"ppt/notesSlides/notesSlide{slide_num}.xml",
                    _NOTES_XML_TEMPLATE.format(text=note_text),
                )
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def extractor():
    return OoxmlExtractor()


class TestBasicExtraction:
    def test_extracts_title(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Q3 Review",
            [("Intro", "Welcome to the review.")],
        )
        meta = extractor.extract(pptx)
        assert meta.title == "Q3 Review"

    def test_extracts_slide_count(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("A", "Body A"), ("B", "Body B"), ("C", "Body C")],
        )
        meta = extractor.extract(pptx)
        assert meta.slide_count == 3

    def test_extracts_topics(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("Revenue", "15% growth"), ("Margins", "72% gross")],
        )
        meta = extractor.extract(pptx)
        assert meta.topics == ["Revenue", "Margins"]

    def test_extracts_slide_summaries(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("Revenue", "Revenue grew 15% YoY.")],
        )
        meta = extractor.extract(pptx)
        assert len(meta.slide_summaries) == 1
        assert meta.slide_summaries[0][0] == "Revenue"
        assert "15%" in meta.slide_summaries[0][1]

    def test_slide_ordering(self, extractor, tmp_path):
        """Slides should be sorted numerically, not lexically."""
        pptx = tmp_path / "deck.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            zf.writestr("docProps/core.xml", _CORE_XML_TEMPLATE.format(title="Deck"))
            # Write slides out of order
            for i in [10, 1, 2]:
                shapes = _title_shape(f"Slide {i}") + _body_shape(f"Body {i}")
                zf.writestr(f"ppt/slides/slide{i}.xml", _SLIDE_XML_TEMPLATE.format(shapes=shapes))

        meta = extractor.extract(pptx)
        assert meta.topics == ["Slide 1", "Slide 2", "Slide 10"]


class TestFallbacks:
    def test_missing_core_xml_uses_filename(self, extractor, tmp_path):
        pptx = tmp_path / "my_deck.pptx"
        with zipfile.ZipFile(pptx, "w") as zf:
            shapes = _title_shape("Intro") + _body_shape("Hello")
            zf.writestr("ppt/slides/slide1.xml", _SLIDE_XML_TEMPLATE.format(shapes=shapes))

        meta = extractor.extract(pptx)
        assert meta.title == "My Deck"  # from filename

    def test_empty_title_in_core_xml(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "quarterly_review.pptx",
            "",
            [("Intro", "Hello")],
        )
        meta = extractor.extract(pptx)
        assert meta.title == "Quarterly Review"  # from filename

    def test_slide_with_no_title_placeholder(self, extractor, tmp_path):
        """A slide with only body content should still be extracted."""
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("", "Body content only")],
        )
        meta = extractor.extract(pptx)
        assert len(meta.slide_summaries) == 1
        assert meta.slide_summaries[0][1] == "Body content only"
        assert meta.topics == []  # no title detected


class TestNotes:
    def test_notes_text_extracted(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("Intro", "Hello")],
            notes={1: "TODO: follow up with team on next steps"},
        )
        meta = extractor.extract(pptx)
        assert len(meta.todos) >= 1
        assert any("follow up" in t.lower() for t in meta.todos)


class TestTodos:
    def test_extracts_todos_from_body(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("Actions", "Action item: finalize the budget by Friday")],
        )
        meta = extractor.extract(pptx)
        assert len(meta.todos) >= 1
        assert any("finalize" in t for t in meta.todos)

    def test_no_todos_when_none_present(self, extractor, tmp_path):
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("Revenue", "Revenue grew 15%.")],
        )
        meta = extractor.extract(pptx)
        assert meta.todos == []


# ---------------------------------------------------------------------------
# SmartArt diagram data XML template
# ---------------------------------------------------------------------------

_DIAGRAM_DATA_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram"
               xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <dgm:ptLst>
    {points}
  </dgm:ptLst>
</dgm:dataModel>
"""

_DIAGRAM_POINT_TEMPLATE = """\
    <dgm:pt modelId="{id}">
      <dgm:prSet/>
      <dgm:spPr/>
      <dgm:t>
        <a:bodyPr/>
        <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
      </dgm:t>
    </dgm:pt>
"""

_SLIDE_RELS_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {rels}
</Relationships>
"""


def _make_smartart_pptx(
    path: Path,
    title: str,
    slide_title: str,
    body: str,
    smartart_texts: list[str],
) -> Path:
    """Build a .pptx with a slide that has both regular text and SmartArt."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("docProps/core.xml", _CORE_XML_TEMPLATE.format(title=title))

        # Slide with regular shapes
        shapes = ""
        if slide_title:
            shapes += _title_shape(slide_title)
        if body:
            shapes += _body_shape(body)
        zf.writestr("ppt/slides/slide1.xml", _SLIDE_XML_TEMPLATE.format(shapes=shapes))

        # Diagram data file with SmartArt text
        points = "".join(
            _DIAGRAM_POINT_TEMPLATE.format(id=i, text=text)
            for i, text in enumerate(smartart_texts)
        )
        zf.writestr("ppt/diagrams/data1.xml", _DIAGRAM_DATA_XML_TEMPLATE.format(points=points))

        # Slide rels pointing to the diagram
        rel = (
            '<Relationship Id="rId10" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData" '
            'Target="../diagrams/data1.xml"/>'
        )
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", _SLIDE_RELS_TEMPLATE.format(rels=rel))

    return path


class TestSmartArt:
    def test_extracts_smartart_text(self, extractor, tmp_path):
        pptx = _make_smartart_pptx(
            tmp_path / "smartart.pptx",
            "Strategy Deck",
            "Our Process",
            "Overview of our workflow.",
            ["Plan", "Design", "Build", "Ship"],
        )
        meta = extractor.extract(pptx)
        assert meta.slide_count == 1
        body = meta.slide_summaries[0][1]
        assert "Plan" in body
        assert "Design" in body
        assert "Build" in body
        assert "Ship" in body

    def test_smartart_combined_with_regular_text(self, extractor, tmp_path):
        pptx = _make_smartart_pptx(
            tmp_path / "mixed.pptx",
            "Deck",
            "Process Overview",
            "Here is our 4-step process.",
            ["Discover", "Define", "Develop", "Deliver"],
        )
        meta = extractor.extract(pptx)
        body = meta.slide_summaries[0][1]
        # Both regular body and SmartArt should be present
        assert "4-step process" in body
        assert "Discover" in body
        assert "Deliver" in body

    def test_smartart_only_slide(self, extractor, tmp_path):
        """Slide with SmartArt but no regular body text."""
        pptx = _make_smartart_pptx(
            tmp_path / "smartonly.pptx",
            "Deck",
            "Values",
            "",
            ["Integrity", "Innovation", "Impact"],
        )
        meta = extractor.extract(pptx)
        body = meta.slide_summaries[0][1]
        assert "Integrity" in body
        assert "Innovation" in body
        assert "Impact" in body

    def test_smartart_todos_detected(self, extractor, tmp_path):
        """TODO keywords in SmartArt should be picked up."""
        pptx = _make_smartart_pptx(
            tmp_path / "todos.pptx",
            "Deck",
            "Actions",
            "",
            ["Action item: review the design", "Follow up with stakeholders"],
        )
        meta = extractor.extract(pptx)
        assert len(meta.todos) >= 1

    def test_no_smartart_no_crash(self, extractor, tmp_path):
        """Slides without SmartArt should work fine (no rels file)."""
        pptx = _make_synthetic_pptx(
            tmp_path / "plain.pptx",
            "Deck",
            [("Title", "Just regular text.")],
        )
        meta = extractor.extract(pptx)
        assert meta.slide_summaries[0][1] == "Just regular text."


class TestImageResults:
    def test_image_results_always_empty(self, extractor, tmp_path):
        """OoxmlExtractor does not extract images (no PIL dependency)."""
        pptx = _make_synthetic_pptx(
            tmp_path / "deck.pptx",
            "Deck",
            [("Intro", "Hello")],
        )
        meta = extractor.extract(pptx)
        assert meta.image_results == []
