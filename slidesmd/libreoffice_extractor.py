"""LibreOffice headless extractor.

Converts presentations to PDF via ``libreoffice --headless``, then
extracts text with ``pdftotext`` (poppler-utils).  Handles .pptx,
.ppt, and .odp files — useful as a last-resort fallback when
python-pptx and the OOXML extractor produce low-quality results.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from slidesmd.extractor import PresentationMeta

_TODO_KEYWORDS = ("todo", "action item", "follow up", "follow-up", "next step", "to-do")


class LibreOfficeExtractor:
    """Extractor using LibreOffice headless conversion + pdftotext."""

    def __init__(self, timeout: int = 120) -> None:
        self.timeout = timeout

    def extract(self, path: Path) -> PresentationMeta:
        lo = self._find_libreoffice()
        if lo is None:
            raise RuntimeError(
                "LibreOffice not found. Install it or ensure 'libreoffice'/'soffice' is on PATH."
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = self._convert_to_pdf(lo, path, Path(tmpdir))
            pages = self._extract_pages(pdf_path)

        title = self._detect_title(pages, path)
        topics: list[str] = []
        slide_summaries: list[tuple[str, str]] = []
        all_lines: list[str] = []

        for page_text in pages:
            lines = [ln.strip() for ln in page_text.strip().split("\n") if ln.strip()]
            if not lines:
                slide_summaries.append(("", ""))
                continue

            slide_title = lines[0]
            body = " ".join(lines[1:])
            topics.append(slide_title)
            slide_summaries.append((slide_title, body))
            all_lines.extend(lines)

        todos = [ln for ln in all_lines if any(kw in ln.lower() for kw in _TODO_KEYWORDS)]

        return PresentationMeta(
            title=title,
            file_path=path,
            slide_count=len(pages),
            topics=topics,
            todos=todos,
            slide_summaries=slide_summaries,
            image_results=[],
        )

    @staticmethod
    def is_available() -> bool:
        return shutil.which("libreoffice") is not None or shutil.which("soffice") is not None

    @staticmethod
    def _find_libreoffice() -> str | None:
        return shutil.which("libreoffice") or shutil.which("soffice")

    def _convert_to_pdf(self, lo_bin: str, src: Path, outdir: Path) -> Path:
        try:
            subprocess.run(
                [lo_bin, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
                capture_output=True,
                timeout=self.timeout,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"LibreOffice conversion failed for {src.name}: {e.stderr.decode(errors='replace')}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"LibreOffice conversion timed out after {self.timeout}s for {src.name}"
            ) from e

        pdf = outdir / f"{src.stem}.pdf"
        if not pdf.exists():
            raise RuntimeError(f"LibreOffice did not produce expected PDF: {pdf.name}")
        return pdf

    def _extract_pages(self, pdf_path: Path) -> list[str]:
        """Extract text from each page of a PDF."""
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            return self._extract_via_pdftotext(pdftotext, pdf_path)
        return self._extract_via_raw_pdf(pdf_path)

    def _extract_via_pdftotext(self, pdftotext_bin: str, pdf_path: Path) -> list[str]:
        """Use poppler's pdftotext for high-quality text extraction."""
        # Get page count via pdfinfo if available
        page_count = self._get_page_count(pdf_path)

        pages: list[str] = []
        for i in range(1, page_count + 1):
            result = subprocess.run(
                [pdftotext_bin, "-f", str(i), "-l", str(i), "-layout", str(pdf_path), "-"],
                capture_output=True,
                timeout=30,
            )
            pages.append(result.stdout.decode(errors="replace"))
        return pages

    def _get_page_count(self, pdf_path: Path) -> int:
        """Get PDF page count via pdfinfo or fallback to regex."""
        pdfinfo = shutil.which("pdfinfo")
        if pdfinfo:
            try:
                result = subprocess.run(
                    [pdfinfo, str(pdf_path)],
                    capture_output=True,
                    timeout=10,
                )
                for line in result.stdout.decode(errors="replace").split("\n"):
                    if line.startswith("Pages:"):
                        return int(line.split(":")[1].strip())
            except (subprocess.TimeoutExpired, ValueError):
                pass

        # Fallback: count page markers in raw PDF
        raw = pdf_path.read_bytes()
        return max(1, len(re.findall(rb"/Type\s*/Page[^s]", raw)))

    def _extract_via_raw_pdf(self, pdf_path: Path) -> list[str]:
        """Naive fallback: extract readable text from PDF binary.

        This is lossy but works when pdftotext is not installed.
        Returns all text as a single "page" since we can't reliably
        detect page boundaries without a proper PDF parser.
        """
        raw = pdf_path.read_bytes()
        # Extract text between BT/ET markers (PDF text objects)
        text_parts: list[str] = []
        for match in re.finditer(rb"\((.*?)\)", raw):
            try:
                decoded = match.group(1).decode("utf-8", errors="replace")
                if decoded.strip() and len(decoded) > 1:
                    text_parts.append(decoded.strip())
            except Exception:
                continue

        full_text = " ".join(text_parts)
        return [full_text] if full_text.strip() else []

    def _detect_title(self, pages: list[str], fallback: Path) -> str:
        """Use the first non-empty line of the first page as title."""
        if pages:
            for line in pages[0].strip().split("\n"):
                stripped = line.strip()
                if stripped:
                    return stripped
        return fallback.stem.replace("-", " ").replace("_", " ").title()
