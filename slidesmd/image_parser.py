"""Extract and interpret images from .pptx slides.

Pipeline per image:
  1. OCR via pytesseract (required)
  2. If OCR confidence is low → AI description via Ollama LLaVA (optional)
  3. Slide title is passed as context to enrich AI descriptions.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image

_TESSERACT_AVAILABLE = False
_OLLAMA_AVAILABLE = False

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    pass

try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    pass

OCR_CONFIDENCE_THRESHOLD = 70  # 0–100; below this → try AI
OCR_MIN_WORDS = 3               # fewer words than this → try AI
OLLAMA_MODEL = "llava"


@dataclass
class ImageResult:
    method: str          # "ocr", "ai", or "skipped"
    text: str
    confidence: float    # avg OCR confidence, 0 if AI/skipped


def parse_image(image: Image.Image, slide_title: str = "") -> ImageResult:
    """Run OCR first; fall back to Ollama LLaVA if OCR is unreliable."""
    if _TESSERACT_AVAILABLE:
        text, confidence = _run_ocr(image)
        words = [w for w in text.split() if len(w) > 1]
        if confidence >= OCR_CONFIDENCE_THRESHOLD and len(words) >= OCR_MIN_WORDS:
            return ImageResult(method="ocr", text=text.strip(), confidence=confidence)

    if _OLLAMA_AVAILABLE:
        description = _describe_with_ollama(image, slide_title)
        if description:
            return ImageResult(method="ai", text=description, confidence=0.0)

    if _TESSERACT_AVAILABLE:
        # OCR ran but was low confidence — return it anyway rather than nothing
        text, confidence = _run_ocr(image)
        if text.strip():
            return ImageResult(method="ocr", text=text.strip(), confidence=confidence)

    return ImageResult(method="skipped", text="", confidence=0.0)


def _run_ocr(image: Image.Image) -> tuple[str, float]:
    """Return (text, avg_confidence). Confidence is 0–100."""
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
        text = " ".join(
            word for word, conf in zip(data["text"], data["conf"])
            if str(conf).lstrip("-").isdigit() and int(conf) >= 0 and word.strip()
        )
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return text, avg_conf
    except Exception:
        return "", 0.0


def _describe_with_ollama(image: Image.Image, slide_title: str = "") -> str:
    """Ask Ollama LLaVA to describe the image, using slide title as context."""
    try:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        context = f'This image is from a slide titled "{slide_title}". ' if slide_title else ""
        prompt = f"{context}Describe what this image shows in 1-2 concise sentences, focusing on data, charts, diagrams, or key visual information."

        response = _ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }],
        )
        return response["message"]["content"].strip()
    except Exception:
        return ""


def extract_images_from_slide(slide: object) -> list[Image.Image]:
    """Return all images found in a slide as PIL Image objects."""
    images = []
    try:
        for shape in slide.shapes:  # type: ignore[attr-defined]
            if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                try:
                    img_bytes = shape.image.blob
                    images.append(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
                except Exception:
                    pass
    except Exception:
        pass
    return images
