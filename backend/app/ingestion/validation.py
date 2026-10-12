"""Upload validation: file name, extension, size, and content signature."""

from __future__ import annotations

from typing import Literal

from app.core.errors import FileTooLargeError, UnsupportedFileError

FileType = Literal["pdf", "txt"]

_EXTENSIONS: dict[str, FileType] = {".pdf": "pdf", ".txt": "txt"}
_MAX_FILENAME_LENGTH = 255


def sanitize_filename(filename: str | None) -> str:
    """Return the base name of an uploaded file, without any client-side path."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        raise UnsupportedFileError("The uploaded file has no file name.")
    return name[:_MAX_FILENAME_LENGTH]


def detect_file_type(filename: str) -> FileType:
    dot = filename.rfind(".")
    extension = filename[dot:].lower() if dot != -1 else ""
    if extension not in _EXTENSIONS:
        raise UnsupportedFileError("Only .pdf and .txt files are supported.")
    return _EXTENSIONS[extension]


def validate_upload(filename: str, content: bytes, max_bytes: int) -> FileType:
    """Validate an upload and return its file type.

    Raises UnsupportedFileError or FileTooLargeError. Text decoding and PDF
    parsing problems are reported later, by extraction.
    """
    file_type = detect_file_type(filename)
    if len(content) > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise FileTooLargeError(f"The file exceeds the {limit_mb:g} MB upload limit.")
    if not content:
        raise UnsupportedFileError("The uploaded file is empty.")
    if file_type == "pdf" and b"%PDF-" not in content[:1024]:
        raise UnsupportedFileError("The file has a .pdf extension but is not a PDF document.")
    if file_type == "txt" and b"\x00" in content:
        raise UnsupportedFileError("The file has a .txt extension but contains binary data.")
    return file_type
