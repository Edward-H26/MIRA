import io
import re
from dataclasses import dataclass, field
from typing import Any

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

RECEIPT_PATTERNS = {
    "total": re.compile(r"(?:total|amount|sum|grand\s*total)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    "subtotal": re.compile(r"(?:subtotal|sub\s*total)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    "tax": re.compile(r"(?:tax|vat|gst)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    "date": re.compile(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"),
    "phone": re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
}

_PDF_MAGIC = b"%PDF-"


@dataclass
class OcrResult:
    raw_text: str = ""
    parsed_fields: dict = field(default_factory=dict)
    line_count: int = 0
    word_count: int = 0
    status: str = "pending"
    error: str = ""


def validate_uploaded_image(uploadedFile) -> tuple[bool, str]:
    if not uploadedFile:
        return False, "No file uploaded."

    contentType = getattr(uploadedFile, "content_type", "")
    if contentType not in ALLOWED_CONTENT_TYPES:
        return False, f"Unsupported file type: {contentType}. Allowed: JPEG, PNG, TIFF, BMP, WebP, PDF."

    fileSize = getattr(uploadedFile, "size", 0)
    if fileSize > MAX_FILE_SIZE_BYTES:
        mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return False, f"File too large. Maximum size: {mb:.0f} MB."

    if fileSize == 0:
        return False, "File is empty."

    try:
        uploadedFile.seek(0)
        head = uploadedFile.read()
        uploadedFile.seek(0)
        if contentType == "application/pdf":
            if not head.startswith(_PDF_MAGIC):
                return False, "File does not appear to be a valid PDF."
        else:
            Image.open(io.BytesIO(head)).verify()
    except Exception:
        return False, "File content does not match declared type."

    return True, ""


def validate_image_dimensions(image: Image.Image) -> tuple[bool, str]:
    width, height = image.size
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        return False, f"Image too small ({width}x{height}). Minimum: {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION}."
    return True, ""


def _extract_with_gemini(fileBytes: bytes, mimeType: str) -> str:
    try:
        from app.services.gemini import extract_text_multimodal
    except Exception:
        return ""
    try:
        text = extract_text_multimodal(fileBytes, mime_type=mimeType) or ""
        return text.strip()
    except Exception:
        return ""


def extract_text_from_image(imageFile) -> OcrResult:
    result = OcrResult()

    try:
        imageFile.seek(0)
        fileBytes = imageFile.read()
        imageFile.seek(0)
        image = Image.open(io.BytesIO(fileBytes))
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

    mime = getattr(imageFile, "content_type", "") or "image/png"
    if mime not in IMAGE_CONTENT_TYPES:
        mime = "image/png"

    rawText = _extract_with_gemini(fileBytes, mime)

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
    result = OcrResult()

    try:
        pdfFile.seek(0)
        fileBytes = pdfFile.read()
        pdfFile.seek(0)
    except Exception as exc:
        result.status = "failed"
        result.error = f"Could not read PDF: {exc}"
        return result

    if not fileBytes.startswith(_PDF_MAGIC):
        result.status = "failed"
        result.error = "File does not appear to be a valid PDF."
        return result

    rawText = _extract_with_gemini(fileBytes, "application/pdf")

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
