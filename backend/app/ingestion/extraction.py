"""Text extraction from PDF and TXT files, preserving PDF page numbers.

PDF pages use layout-aware text (regions separated by blank lines, table rows kept on
one line; `pdf_layout.py`, D-063) and fall back to pypdf's plain extraction when the
layout pass is not possible or would lose text. TXT files keep the author's layout.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.errors import DocumentExtractionError, EmptyDocumentError
from app.ingestion.pdf_layout import layout_text
from app.ingestion.validation import FileType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageText:
    """Text of one source unit: a PDF page (1-based number) or a whole TXT file (None)."""

    page_number: int | None
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    file_type: FileType
    pages: list[PageText]
    total_pages: int | None


_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_ALNUM = re.compile(r"\w")
# Layout text is used only if it keeps at least this share of the plain text's characters.
_LAYOUT_MIN_COVERAGE = 0.9


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = _TRAILING_SPACE.sub("\n", text)
    return _EXCESS_BLANK_LINES.sub("\n\n", text).strip()


def extract_pdf(content: bytes) -> ExtractedDocument:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentExtractionError("Password-protected PDFs are not supported.")
        pages: list[PageText] = []
        for index, page in enumerate(reader.pages, start=1):
            text = _page_text(page)
            if text:
                pages.append(PageText(page_number=index, text=text))
        total_pages = len(reader.pages)
    except DocumentExtractionError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        logger.warning("PDF extraction failed: %s", exc)
        raise DocumentExtractionError("The PDF could not be read; it may be damaged.") from exc
    except Exception as exc:  # pypdf can raise many internal errors on malformed files
        logger.exception("Unexpected PDF extraction failure")
        raise DocumentExtractionError("The PDF could not be read; it may be damaged.") from exc

    if not pages:
        raise EmptyDocumentError(
            "No extractable text was found. Scanned or image-only PDFs are not supported."
        )
    return ExtractedDocument(file_type="pdf", pages=pages, total_pages=total_pages)


def _page_text(page: Any) -> str:
    plain = normalize_text(page.extract_text() or "")
    try:
        layout = normalize_text(layout_text(page) or "")
    except Exception:  # positions are a refinement; never fail a page because of them
        logger.warning("Layout-aware extraction failed; using plain text for this page")
        return plain
    if len(_ALNUM.findall(layout)) < _LAYOUT_MIN_COVERAGE * len(_ALNUM.findall(plain)):
        return plain
    return layout


def extract_txt(content: bytes) -> ExtractedDocument:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentExtractionError("TXT files must be UTF-8 encoded.") from exc
    text = normalize_text(decoded)
    if not text:
        raise EmptyDocumentError("The text file contains no readable text.")
    return ExtractedDocument(
        file_type="txt", pages=[PageText(page_number=None, text=text)], total_pages=None
    )


def extract_document(file_type: FileType, content: bytes) -> ExtractedDocument:
    return extract_pdf(content) if file_type == "pdf" else extract_txt(content)
