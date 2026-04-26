"""Pure-stdlib OOXML extractor using zipfile + xml.etree.

Parses .pptx files (which are ZIP archives of XML) without python-pptx.
Handles cases where python-pptx fails on malformed or unusual OOXML.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from slidesmd.extractor import PresentationMeta

# OOXML namespaces
_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
}

_DIAGRAM_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData"

_TODO_KEYWORDS = ("todo", "action item", "follow up", "follow-up", "next step", "to-do")

_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_NOTES_RE = re.compile(r"^ppt/notesSlides/notesSlide(\d+)\.xml$")


class OoxmlExtractor:
    """Extractor that parses OOXML directly via stdlib."""

    def extract(self, path: Path) -> PresentationMeta:
        with zipfile.ZipFile(path, "r") as zf:
            title = self._parse_title(zf, path)
            slide_entries = self._enumerate_slides(zf)
            notes_map = self._enumerate_notes(zf)

            topics: list[str] = []
            slide_summaries: list[tuple[str, str]] = []
            all_text_lines: list[str] = []

            for slide_num, slide_path in slide_entries:
                slide_title, body = self._extract_slide_text(zf, slide_path)
                if slide_title:
                    topics.append(slide_title)
                if slide_title or body:
                    slide_summaries.append((slide_title, body))

                # collect notes text
                notes_path = notes_map.get(slide_num)
                if notes_path:
                    notes_text = self._extract_text_from_xml(zf, notes_path)
                    if notes_text:
                        all_text_lines.extend(notes_text.split("\n"))

                # collect slide text for todo scanning
                if body:
                    all_text_lines.extend(body.split("\n"))

            todos = self._extract_todos(all_text_lines)

            return PresentationMeta(
                title=title,
                file_path=path,
                slide_count=len(slide_entries),
                topics=topics,
                todos=todos,
                slide_summaries=slide_summaries,
                image_results=[],
            )

    def _parse_title(self, zf: zipfile.ZipFile, fallback: Path) -> str:
        try:
            with zf.open("docProps/core.xml") as f:
                tree = ET.parse(f)
            root = tree.getroot()
            title_el = root.find("dc:title", _NS)
            if title_el is not None and title_el.text and title_el.text.strip():
                return title_el.text.strip()
        except (KeyError, ET.ParseError):
            pass
        return fallback.stem.replace("-", " ").replace("_", " ").title()

    def _enumerate_slides(self, zf: zipfile.ZipFile) -> list[tuple[int, str]]:
        entries: list[tuple[int, str]] = []
        for name in zf.namelist():
            m = _SLIDE_RE.match(name)
            if m:
                entries.append((int(m.group(1)), name))
        entries.sort(key=lambda x: x[0])
        return entries

    def _enumerate_notes(self, zf: zipfile.ZipFile) -> dict[int, str]:
        notes: dict[int, str] = {}
        for name in zf.namelist():
            m = _NOTES_RE.match(name)
            if m:
                notes[int(m.group(1))] = name
        return notes

    def _extract_slide_text(self, zf: zipfile.ZipFile, slide_path: str) -> tuple[str, str]:
        try:
            with zf.open(slide_path) as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return ("", "")

        root = tree.getroot()
        slide_title = ""
        body_parts: list[str] = []

        # Regular shape text
        for sp in root.iter(f"{{{_NS['p']}}}sp"):
            is_title = self._is_title_shape(sp)
            text = self._collect_text(sp)
            if not text:
                continue
            if is_title and not slide_title:
                slide_title = text
            else:
                body_parts.append(text)

        # SmartArt / diagram text
        smartart_texts = self._extract_smartart_text(zf, slide_path)
        body_parts.extend(smartart_texts)

        return (slide_title, " · ".join(body_parts))

    def _is_title_shape(self, sp: ET.Element) -> bool:
        for ph in sp.iter(f"{{{_NS['p']}}}ph"):
            ph_type = ph.get("type", "")
            if ph_type in ("title", "ctrTitle"):
                return True
            # idx=0 without explicit type is also a title
            if ph.get("idx") == "0" and not ph_type:
                return True
        return False

    def _collect_text(self, element: ET.Element) -> str:
        texts: list[str] = []
        for t in element.iter(f"{{{_NS['a']}}}t"):
            if t.text:
                texts.append(t.text)
        return " ".join(texts).strip()

    def _extract_text_from_xml(self, zf: zipfile.ZipFile, xml_path: str) -> str:
        try:
            with zf.open(xml_path) as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return ""

        texts: list[str] = []
        for t in tree.getroot().iter(f"{{{_NS['a']}}}t"):
            if t.text:
                texts.append(t.text)
        return " ".join(texts).strip()

    def _extract_smartart_text(self, zf: zipfile.ZipFile, slide_path: str) -> list[str]:
        """Extract text from SmartArt diagrams referenced by a slide.

        SmartArt in OOXML:
        1. Slide rels file maps relationship IDs to diagram data files
        2. Diagram data XML (ppt/diagrams/data*.xml) contains text in a:t elements
           within dgm:pt (data point) nodes
        """
        rels_path = self._slide_rels_path(slide_path)
        diagram_paths = self._find_diagram_data_paths(zf, rels_path)

        texts: list[str] = []
        for dgm_path in diagram_paths:
            text = self._extract_diagram_text(zf, dgm_path)
            if text:
                texts.append(text)
        return texts

    @staticmethod
    def _slide_rels_path(slide_path: str) -> str:
        """Convert 'ppt/slides/slide1.xml' → 'ppt/slides/_rels/slide1.xml.rels'."""
        parts = slide_path.rsplit("/", 1)
        return f"{parts[0]}/_rels/{parts[1]}.rels"

    def _find_diagram_data_paths(self, zf: zipfile.ZipFile, rels_path: str) -> list[str]:
        """Parse slide .rels to find diagram data file paths."""
        try:
            with zf.open(rels_path) as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return []

        paths: list[str] = []
        for rel in tree.getroot():
            if rel.get("Type") == _DIAGRAM_REL_TYPE:
                target = rel.get("Target", "")
                if target.startswith("../"):
                    # relative path: ../diagrams/data1.xml → ppt/diagrams/data1.xml
                    paths.append("ppt/" + target[3:])
                elif not target.startswith("ppt/"):
                    paths.append("ppt/diagrams/" + target)
                else:
                    paths.append(target)
        return paths

    def _extract_diagram_text(self, zf: zipfile.ZipFile, dgm_path: str) -> str:
        """Extract all text from a diagram data XML file.

        Diagram data files contain <dgm:pt> elements (data points),
        each with <dgm:t> or nested <a:t> text elements.
        """
        try:
            with zf.open(dgm_path) as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return ""

        texts: list[str] = []
        for t_el in tree.getroot().iter(f"{{{_NS['a']}}}t"):
            if t_el.text and t_el.text.strip():
                texts.append(t_el.text.strip())
        return " · ".join(texts)

    def _extract_todos(self, lines: list[str]) -> list[str]:
        todos: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and any(kw in stripped.lower() for kw in _TODO_KEYWORDS):
                todos.append(stripped)
        return todos
