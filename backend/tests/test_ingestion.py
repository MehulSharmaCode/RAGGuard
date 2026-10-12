"""Upload validation, text extraction, and chunking."""

from __future__ import annotations

import itertools

import pytest

from app.core.errors import (
    DocumentExtractionError,
    EmptyDocumentError,
    FileTooLargeError,
    UnsupportedFileError,
)
from app.ingestion.chunking import chunk_pages
from app.ingestion.extraction import PageText, extract_document, extract_pdf, extract_txt
from app.ingestion.validation import sanitize_filename, validate_upload
from tests.conftest import ORBIT_PAGES, FakeEmbedder, make_pdf

MB = 1024 * 1024


# --- validation ------------------------------------------------------------------
@pytest.mark.parametrize("name", ["notes.docx", "image.png", "archive", "script.pdf.exe"])
def test_rejects_unsupported_extensions(name: str) -> None:
    with pytest.raises(UnsupportedFileError):
        validate_upload(name, b"hello", MB)


def test_accepts_pdf_and_txt_case_insensitively() -> None:
    assert validate_upload("Report.PDF", make_pdf(["x"]), MB) == "pdf"
    assert validate_upload("notes.TxT", b"hello", MB) == "txt"


def test_rejects_oversized_file() -> None:
    with pytest.raises(FileTooLargeError, match="1 MB"):
        validate_upload("big.txt", b"a" * (MB + 1), MB)


def test_accepts_file_exactly_at_limit() -> None:
    assert validate_upload("edge.txt", b"a" * MB, MB) == "txt"


def test_rejects_empty_file() -> None:
    with pytest.raises(UnsupportedFileError, match="empty"):
        validate_upload("empty.txt", b"", MB)


def test_rejects_pdf_extension_without_pdf_signature() -> None:
    with pytest.raises(UnsupportedFileError, match="not a PDF"):
        validate_upload("fake.pdf", b"just some text", MB)


def test_rejects_binary_content_in_txt() -> None:
    with pytest.raises(UnsupportedFileError, match="binary"):
        validate_upload("data.txt", b"abc\x00\x01\x02", MB)


def test_sanitize_filename_strips_client_paths() -> None:
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("C:\\Users\\me\\doc.pdf") == "doc.pdf"
    with pytest.raises(UnsupportedFileError):
        sanitize_filename("   ")


# --- extraction ------------------------------------------------------------------
def test_pdf_extraction_preserves_page_numbers_and_skips_blank_pages() -> None:
    extracted = extract_pdf(make_pdf(ORBIT_PAGES))
    assert extracted.file_type == "pdf"
    assert extracted.total_pages == 3
    assert [p.page_number for p in extracted.pages] == [1, 3]
    assert "low Earth orbit" in extracted.pages[0].text
    assert "35786" in extracted.pages[1].text


def test_image_only_pdf_is_rejected_as_empty() -> None:
    with pytest.raises(EmptyDocumentError, match="image-only"):
        extract_pdf(make_pdf(["", ""]))


def test_corrupted_pdf_raises_extraction_error() -> None:
    with pytest.raises(DocumentExtractionError):
        extract_pdf(b"%PDF-1.4\n this is not a real pdf body")


def test_txt_extraction_has_no_page_number_and_normalizes_text() -> None:
    extracted = extract_txt("\ufeffLine one  \r\nLine two\n\n\n\n\nLine three".encode())
    assert extracted.total_pages is None
    assert len(extracted.pages) == 1
    assert extracted.pages[0].page_number is None
    assert extracted.pages[0].text == "Line one\nLine two\n\nLine three"


def test_txt_must_be_utf8() -> None:
    with pytest.raises(DocumentExtractionError, match="UTF-8"):
        extract_txt("café".encode("latin-1"))


def test_whitespace_only_txt_is_empty() -> None:
    with pytest.raises(EmptyDocumentError):
        extract_document("txt", b"   \n\n\t ")


# --- chunking --------------------------------------------------------------------
def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def test_chunks_respect_size_and_overlap() -> None:
    tokenizer = FakeEmbedder()
    text = _words(100)
    chunks = chunk_pages([PageText(None, text)], tokenizer, chunk_size=30, overlap=10)

    assert [c.token_count for c in chunks] == [30, 30, 30, 30, 20]
    assert all(c.token_count <= 30 for c in chunks)
    for previous, current in itertools.pairwise(chunks):
        assert previous.text.split()[-10:] == current.text.split()[:10]
    # The final chunk reaches the end of the text; nothing is dropped.
    assert chunks[-1].text.endswith("w99")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_character_spans_point_back_into_source_text() -> None:
    text = _words(70)
    chunks = chunk_pages([PageText(None, text)], FakeEmbedder(), chunk_size=25, overlap=5)
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_chunks_never_cross_pages_and_keep_page_numbers() -> None:
    pages = [PageText(1, _words(50)), PageText(3, _words(10))]
    chunks = chunk_pages(pages, FakeEmbedder(), chunk_size=20, overlap=5)
    assert {c.page_number for c in chunks} == {1, 3}
    page3 = [c for c in chunks if c.page_number == 3]
    assert len(page3) == 1 and page3[0].text == _words(10)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_short_text_gives_single_chunk() -> None:
    chunks = chunk_pages([PageText(None, "Just a few words.")], FakeEmbedder(), 180, 30)
    assert len(chunks) == 1
    assert chunks[0].text == "Just a few words."


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (10, 10), (10, -1)])
def test_invalid_chunk_parameters(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_pages([PageText(None, "text")], FakeEmbedder(), size, overlap)
