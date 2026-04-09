import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp",
    "application/pdf",
}
IMAGE_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp",
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_DIMENSION = 50

_easyocr_reader = None


def _get_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False)
    return _easyocr_reader

RECEIPT_PATTERNS = {
    "total": re.compile(r"(?:total|amount|sum|grand\s*total)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    "subtotal": re.compile(r"(?:subtotal|sub\s*total)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    "tax": re.compile(r"(?:tax|vat|gst)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    "date": re.compile(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"),
    "phone": re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
}


@dataclass
class OcrResult:
    raw_text: str = ""
    parsed_fields: dict = field(default_factory=dict)
    line_count: int = 0
    word_count: int = 0
    status: str = "pending"
    error: str = ""


def validate_uploaded_image(uploadedFile) -> tuple[bool, str]:
    """Validate image file type and size."""
    if not uploadedFile:
        return False, "No file uploaded."

    contentType = getattr(uploadedFile, "content_type", "")
    if contentType not in ALLOWED_CONTENT_TYPES:
        return False, f"Unsupported file type: {contentType}. Allowed: JPEG, PNG, TIFF, BMP, WebP."

    fileSize = getattr(uploadedFile, "size", 0)
    if fileSize > MAX_FILE_SIZE_BYTES:
        mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return False, f"File too large. Maximum size: {mb:.0f} MB."

    if fileSize == 0:
        return False, "File is empty."

    return True, ""


def validate_image_dimensions(image: Image.Image) -> tuple[bool, str]:
    """Check that image meets minimum dimension requirements."""
    width, height = image.size
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        return False, f"Image too small ({width}x{height}). Minimum: {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION}."
    return True, ""


def extract_text_from_image(imageFile) -> OcrResult:
    result = OcrResult()

    try:
        imageFile.seek(0)
        image = Image.open(imageFile)
        if image.mode != "RGB":
            image = image.convert("RGB")
    except Exception as exc:
        result.status = "failed"
        result.error = f"Could not open image: {exc}"
        return result

    isValid, dimError = validate_image_dimensions(image)
    if not isValid:
        result.status = "failed"
        result.error = dimError
        return result

    try:
        reader = _get_reader()
        imageArray = np.array(image)
        detections = reader.readtext(imageArray)
        rawText = "\n".join(text for _, text, _ in detections).strip()
    except Exception as exc:
        result.status = "failed"
        result.error = f"OCR extraction failed: {exc}"
        return result

    if not rawText:
        result.status = "failed"
        result.error = "No text could be extracted from the image."
        return result

    result.raw_text = rawText
    result.line_count = len(rawText.splitlines())
    result.word_count = len(rawText.split())
    result.status = "success"
    return result


def extract_text_from_pdf(pdfFile) -> OcrResult:
    import pdfplumber

    result = OcrResult()
    try:
        pdfFile.seek(0)
        with pdfplumber.open(pdfFile) as pdf:
            pagesText = [page.extract_text() or "" for page in pdf.pages]
            rawText = "\n\n".join(pagesText).strip()
    except Exception as exc:
        result.status = "failed"
        result.error = f"PDF extraction failed: {exc}"
        return result

    if not rawText:
        result.status = "failed"
        result.error = "No text could be extracted from the PDF."
        return result

    result.raw_text = rawText
    result.line_count = len(rawText.splitlines())
    result.word_count = len(rawText.split())
    result.status = "success"
    return result


def extract_text_from_file(uploadedFile) -> OcrResult:
    contentType = getattr(uploadedFile, "content_type", "")
    if contentType == "application/pdf":
        return extract_text_from_pdf(uploadedFile)
    return extract_text_from_image(uploadedFile)


def parse_document_fields(rawText: str) -> dict:
    """Extract structured fields from raw OCR text using regex patterns."""
    fields: dict[str, Any] = {}

    for fieldName, pattern in RECEIPT_PATTERNS.items():
        matches = pattern.findall(rawText)
        if matches:
            if fieldName in {"total", "subtotal", "tax"}:
                cleaned = matches[0].replace(",", "") if isinstance(matches[0], str) else str(matches[0])
                try:
                    fields[fieldName] = float(cleaned)
                except ValueError:
                    fields[fieldName] = cleaned
            elif fieldName == "date":
                fields[fieldName] = matches[0]
            else:
                fields[fieldName] = matches[0]

    fields["line_count"] = len(rawText.splitlines())
    fields["word_count"] = len(rawText.split())

    return fields


