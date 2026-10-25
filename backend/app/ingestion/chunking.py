"""Structure-aware, token-aware chunking with retrieval sub-units (D-063).

Regions are the blocks of a page separated by blank lines: paragraphs in TXT files,
layout regions in PDFs (a table, a list with its heading, a text box). Whole regions
are packed into chunks of at most `chunk_size` tokens, measured with the embedding
model's own tokenizer; only a region longer than `chunk_size` is split, into windows
of `chunk_size` tokens advancing by `chunk_size - overlap`. A short heading-like region
is attached to the region after it, another short region (a label, a number) to the
region before it. Chunks never cross a PDF page boundary and are exact slices of the
page text, so page citations and character spans stay exact.

Each chunk also lists its sub-units: lines, table rows, list items, and sentences of
long paragraphs, prefixed with their region heading and at least
`SUBUNIT_MIN_TOKENS` long. They are embedded in addition to the whole chunk so a
question can match one row or item without the rest of the chunk diluting it; the
whole chunk is still what is returned as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.ingestion.extraction import PageText

SUBUNIT_MIN_TOKENS = 6  # shorter units (headings, labels) matched unrelated questions
SUBUNIT_MAX_TOKENS = 64  # longer lines are split at sentence boundaries
MAX_SUBUNITS = 32  # bound on vectors per chunk
SHORT_REGION_TOKENS = 24  # regions below this are attached to a neighbour

_REGION_BREAK = re.compile(r"\n[ \t]*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")


class Tokenizer(Protocol):
    def token_spans(self, text: str) -> list[tuple[int, int]]:
        """Return (start, end) character offsets of each token, without special tokens."""
        ...


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    page_number: int | None
    text: str
    char_start: int
    char_end: int
    token_count: int
    units: tuple[str, ...] = ()  # retrieval sub-units, embedded besides `text`


def is_heading(text: str) -> bool:
    """A short single line without closing punctuation, mostly letters."""
    line = text.strip()
    letters = sum(ch.isalpha() for ch in line)
    return (
        bool(line)
        and "\n" not in line
        and len(line.split()) <= 10
        and not line.endswith((".", ":", ";", ","))
        and letters >= 0.5 * len(line)
    )


def _regions(text: str) -> list[tuple[int, int]]:
    """Character ranges of the blank-line separated regions of `text`."""
    ranges: list[tuple[int, int]] = []
    start = 0
    for match in _REGION_BREAK.finditer(text):
        ranges.append((start, match.start()))
        start = match.end()
    ranges.append((start, len(text)))
    return [(s, e) for s, e in ranges if text[s:e].strip()]


def _group_regions(
    text: str, regions: list[tuple[int, int]], counts: list[int], chunk_size: int
) -> list[tuple[int, int]]:
    """Attach short regions to a neighbour, then pack whole regions up to `chunk_size`."""
    groups: list[list[int]] = []  # [start, end, tokens, attach_forward]
    for (start, end), count in zip(regions, counts, strict=True):
        if groups and groups[-1][3]:
            groups[-1][1], groups[-1][2], groups[-1][3] = end, groups[-1][2] + count, 0
            continue
        short = count < SHORT_REGION_TOKENS
        if short and groups and not is_heading(text[start:end]):
            groups[-1][1], groups[-1][2] = end, groups[-1][2] + count
            continue
        groups.append([start, end, count, int(short and is_heading(text[start:end]))])
    packed: list[list[int]] = []
    for start, end, count, _ in groups:
        if packed and packed[-1][2] + count <= chunk_size:
            packed[-1][1], packed[-1][2] = end, packed[-1][2] + count
        else:
            packed.append([start, end, count])
    return [(start, end) for start, end, _ in packed]


def sub_units(text: str, tokenizer: Tokenizer) -> tuple[str, ...]:
    """Retrieval sub-units of a chunk (see module docstring)."""

    def size(value: str) -> int:
        return len(tokenizer.token_spans(value))

    units: list[str] = []
    for start, end in _regions(text):
        lines = [line.strip() for line in text[start:end].split("\n") if line.strip()]
        heading = lines[0] if len(lines) > 1 and is_heading(lines[0]) else None
        pieces: list[str] = []
        for line in lines[1:] if heading else lines:
            if size(line) <= SUBUNIT_MAX_TOKENS:
                pieces.append(line)
                continue
            current = ""
            for sentence in _SENTENCE_END.split(line):
                joined = f"{current} {sentence}".strip()
                if current and size(joined) > SUBUNIT_MAX_TOKENS:
                    pieces.append(current)
                    current = sentence
                else:
                    current = joined
            if current:
                pieces.append(current)
        carry = ""
        region_units: list[str] = []
        for piece in pieces:
            candidate = f"{carry} {piece}".strip()
            if heading:
                candidate = f"{heading}: {candidate}"
            if size(candidate) < SUBUNIT_MIN_TOKENS:
                carry = f"{carry} {piece}".strip()
                continue
            region_units.append(candidate)
            carry = ""
        if carry and region_units:
            region_units[-1] = f"{region_units[-1]} {carry}"
        units.extend(region_units)
    whole = " ".join(text.split())
    unique = list(dict.fromkeys(u for u in units if " ".join(u.split()) != whole))
    return tuple(unique[:MAX_SUBUNITS])


def chunk_pages(
    pages: list[PageText], tokenizer: Tokenizer, chunk_size: int, overlap: int
) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    for page in pages:
        spans = [(s, e) for s, e in tokenizer.token_spans(page.text) if e > s]
        regions = _regions(page.text)
        counts = [sum(1 for s, _ in spans if start <= s < end) for start, end in regions]
        for start, end in _group_regions(page.text, regions, counts, chunk_size):
            group = [span for span in spans if start <= span[0] < end]
            first = 0
            while first < len(group):
                window = group[first : first + chunk_size]
                char_start, char_end = window[0][0], window[-1][1]
                text = page.text[char_start:char_end].strip()
                if text:
                    chunks.append(
                        Chunk(
                            chunk_index=len(chunks),
                            page_number=page.page_number,
                            text=text,
                            char_start=char_start,
                            char_end=char_end,
                            token_count=len(window),
                            units=sub_units(text, tokenizer),
                        )
                    )
                if first + chunk_size >= len(group):
                    break
                first += step
    return chunks
