"""Layout-aware text for one PDF page, rebuilt from pypdf's positioned text runs.

pypdf's plain extraction returns text in content-stream order with line breaks only.
On multi-region pages (slides, reports with side-by-side tables) that order interleaves
unrelated regions and splits wrapped table cells, so a table row's cells end up far
apart and every chunk mixes several topics (D-063). This module uses the position and
font size of each text run to rebuild, without any document-specific rule:

- lines: runs on one baseline, left to right; a run that follows a real horizontal gap
  and starts at a recurring column position opens a new cell (`a | b`);
- blocks: lines stacked with normal line spacing and the same font size; a wrapped
  continuation of a row (left column empty, cells under existing cells) is merged into
  that row's cells;
- rows: blocks side by side whose vertical extents overlap (table cells written as
  separate text boxes) are joined into one row;
- regions: rows stacked closely and overlapping horizontally; a larger font starts a
  new region (a heading starts a section).

Regions are separated by a blank line, rows by a line break. Text widths are not read
from the font: each page's average character width is estimated from its own runs
(consecutive runs on a line are almost always adjacent), so gaps and extents are
estimates. Many PDF writers emit one run per glyph group ("Ag", "r", "iSe"); gaps, not
mere positions, decide cell boundaries, and a page whose cells still look like word
fragments returns None so the caller uses plain extraction (2026-10-16, D-064). The
caller also falls back when text would be lost.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# Default advance width of one character in font-size units (no font metrics); each page
# replaces it with an estimate from its own runs when there are enough samples.
_CHAR_WIDTH = 0.5
_CELL_MIN_GAP = 1.0  # min horizontal gap / size before a run can open a new cell
_FRAGMENT_SHARE = 0.25  # max share of 1-2 character cells before the page is rejected
_SAME_BASELINE = 0.35  # |dy| / size for runs on one line
_LINE_STEP = 1.8  # max baseline step / size inside a block
_SIZE_CHANGE = 0.15  # relative font-size change that ends a block
_COLUMN_MIN_LINES = 3  # an x position is a column start if runs start there on >= 3 lines
_REGION_GAP = 3.0  # max vertical gap / size between rows of one region
_CELL_GAP = 4.0  # max horizontal gap / size between side-by-side cells without a column
_BULLETS = frozenset("➤•▪●◦■□○►✓-*\u2013")  # \u2013: en dash
_BULLET_START = re.compile("^\\s*(?:[➤•▪●◦■□○►✓]|[-*\u2013]\\s)")
_LIST_MARKER = re.compile(r"^\(?(?:\d{1,3}|[a-zA-Z]|[ivxIVX]{1,4})[.)]$")  # "4.", "a)", "(iv)"
_LINE_START_MIN_GAP = 0.3  # a cell at a line-start column still needs a visible gap


@dataclass
class _Run:
    x: float
    y: float
    size: float
    text: str


@dataclass
class _Cell:
    x: float
    text: str


@dataclass
class _Line:
    y: float
    size: float
    cells: list[_Cell]
    last_x: float
    end: float  # estimated right edge

    @property
    def x0(self) -> float:
        return self.cells[0].x

    def text(self) -> str:
        return " | ".join(t for t in (c.text.strip() for c in self.cells) if t)


@dataclass
class _Block:
    lines: list[_Line] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return min(line.x0 for line in self.lines)

    @property
    def x1(self) -> float:
        return max(line.end for line in self.lines)

    @property
    def top(self) -> float:
        return max(line.y + line.size for line in self.lines)

    @property
    def bottom(self) -> float:
        return min(line.y for line in self.lines)

    @property
    def size(self) -> float:
        return max(line.size for line in self.lines)

    def text(self) -> str:
        """Wrapped prose is reflowed; table rows and bullet items keep their own line."""
        out = ""
        previous: _Line | None = None
        for line in self.lines:
            text = line.text()
            if not text:
                continue
            if out:
                keep = (
                    _BULLET_START.match(text)
                    or len(line.cells) > 1
                    or (previous is not None and len(previous.cells) > 1)
                )
                out += "\n" if keep else " "
            out += text
            previous = line
        return out


@dataclass
class _Region:
    rows: list[str]
    x0: float
    x1: float
    bottom: float
    size: float


def _width(text: str, size: float, ratio: float = _CHAR_WIDTH) -> float:
    return len(text) * size * ratio


def _char_ratio(runs: list[_Run]) -> float:
    """Median advance per character / size, from consecutive runs on one baseline."""
    samples = []
    for run, nxt in itertools.pairwise(runs):
        if (
            run.text
            and abs(nxt.y - run.y) <= _SAME_BASELINE * max(run.size, nxt.size)
            and nxt.x > run.x
        ):
            ratio = (nxt.x - run.x) / (len(run.text) * run.size)
            if 0.15 <= ratio <= 1.2:  # larger steps are column jumps, not adjacency
                samples.append(ratio)
    if len(samples) < 5:
        return _CHAR_WIDTH
    samples.sort()
    # Capped at the typical 0.5 em of proportional Latin fonts: when runs are whole cells,
    # consecutive runs are column jumps and inflate the estimate. Underestimating widths
    # only makes real gaps look slightly larger, which is the safe direction.
    return min(samples[len(samples) // 2], _CHAR_WIDTH)


def _gap(previous: _Run, run: _Run, ratio: float) -> float:
    return run.x - (previous.x + _width(previous.text, previous.size, ratio))


def page_runs(page: Any) -> list[_Run] | None:
    """Positioned, non-empty runs of a page, or None when positions are unusable."""
    runs: list[_Run] = []
    rotated = 0
    width, height = float(page.mediabox.width), float(page.mediabox.height)

    def visit(text: str, cm: list[float], tm: list[float], _font: Any, size: float) -> None:
        nonlocal rotated
        if not text:
            return
        if not text.strip():
            # pypdf reports spaces it infers from glyph gaps as whitespace-only runs; keep
            # them as a word break on the previous run (line breaks are rebuilt from y).
            if " " in text and runs and not runs[-1].text.endswith(" "):
                runs[-1].text += " "
            return
        _a, b, c, d, e, f = (float(v) for v in tm)
        ca, cb, cc, cd, ce, cf = (float(v) for v in cm)
        if abs(b) > 1e-6 or abs(c) > 1e-6 or abs(cb) > 1e-6 or abs(cc) > 1e-6:
            rotated += 1
        x = e * ca + f * cc + ce
        y = e * cb + f * cd + cf
        scale = abs(d * cd) or 1.0
        runs.append(_Run(x, y, float(size) * scale, text.replace("\n", " ")))

    page.extract_text(visitor_text=visit)
    if not runs or page.rotation % 360 or rotated > 0.1 * len(runs):
        return None
    inside = [r for r in runs if -1 <= r.x <= width + 1 and -1 <= r.y <= height + 1]
    return inside or None


def _same_line(run: _Run, line: _Line) -> bool:
    return abs(run.y - line.y) <= _SAME_BASELINE * max(run.size, line.size) and run.x >= line.last_x


def _column_starts(runs: list[_Run], ratio: float) -> tuple[set[int], set[int]]:
    """Columns: x positions (rounded) where, on at least `_COLUMN_MIN_LINES` lines, a run
    starts a line or follows a real gap (positions inside words do not count). Line-start
    columns: x positions where at least two lines start (e.g. wrapped cell text)."""
    seen: dict[int, set[int]] = defaultdict(set)
    starts: dict[int, int] = defaultdict(int)
    line_id = 0
    previous: _Run | None = None
    for run in runs:
        same = previous is not None and (
            abs(run.y - previous.y) <= _SAME_BASELINE * max(run.size, previous.size)
            and run.x >= previous.x
        )
        if previous is not None and not same:
            line_id += 1
        if previous is None or not same:
            starts[round(run.x)] += 1
        if previous is None or not same or _gap(previous, run, ratio) >= _CELL_MIN_GAP * run.size:
            seen[round(run.x)].add(line_id)
        previous = run
    columns = {x for x, lines in seen.items() if len(lines) >= _COLUMN_MIN_LINES}
    return columns, {x for x, count in starts.items() if count >= 2 and x in columns}


def _lines(runs: list[_Run], columns: set[int], line_starts: set[int], ratio: float) -> list[_Line]:
    lines: list[_Line] = []
    previous: _Run | None = None
    for run in runs:
        line = lines[-1] if lines else None
        if line is not None and previous is not None and _same_line(run, line):
            current = line.cells[-1].text.strip()
            gap = _gap(previous, run, ratio)
            text = line.cells[-1].text
            inside_word = bool(text) and text[-1].isalpha() and run.text[:1].islower()
            new_cell = (
                round(run.x) in columns
                and run.x > line.x0 + 0.5 * run.size
                and (
                    (round(run.x) in line_starts and gap >= _LINE_START_MIN_GAP * run.size)
                    or gap >= _CELL_MIN_GAP * run.size
                )
                and current
                and current not in _BULLETS
                and not _LIST_MARKER.match(current)
                and not inside_word
            )
            if new_cell:
                line.cells.append(_Cell(run.x, run.text.lstrip()))
            else:
                line.cells[-1].text += run.text
            line.last_x = run.x
            line.end = max(line.end, run.x + _width(run.text, run.size, ratio))
        else:
            lines.append(
                _Line(
                    run.y,
                    run.size,
                    [_Cell(run.x, run.text)],
                    run.x,
                    run.x + _width(run.text, run.size, ratio),
                )
            )
        previous = run
    return lines


def _is_row_continuation(line: _Line, row: _Line) -> bool:
    """A wrapped table row: left column empty, every cell under a cell of `row`."""
    if len(row.cells) < 2 or line.x0 <= row.x0 + line.size:
        return False
    return all(any(abs(c.x - r.x) <= 2 for r in row.cells) for c in line.cells)


def _blocks(lines: list[_Line]) -> list[_Block]:
    blocks: list[_Block] = []
    for line in lines:
        block = blocks[-1] if blocks else None
        if block is not None:
            last = block.lines[-1]
            size = max(line.size, last.size)
            step = last.y - line.y
            same_size = abs(line.size - last.size) <= _SIZE_CHANGE * size
            if 0 < step <= _LINE_STEP * size and same_size:
                if _is_row_continuation(line, last):
                    for cell in line.cells:
                        target = min(last.cells, key=lambda r: abs(r.x - cell.x))
                        target.text = f"{target.text.rstrip()} {cell.text.strip()}"
                    last.y = line.y
                    continue
                if abs(line.x0 - last.x0) <= 3 * line.size:
                    block.lines.append(line)
                    continue
        blocks.append(_Block([line]))
    return blocks


def _rows(blocks: list[_Block], columns: set[int]) -> list[list[_Block]]:
    rows: list[list[_Block]] = []
    for block in blocks:
        row = rows[-1] if rows else None
        if row is not None:
            left = row[-1]
            overlap = min(block.top, left.top) - max(block.bottom, left.bottom)
            height = min(block.top - block.bottom, left.top - left.bottom)
            aligned = round(left.x0) in columns and round(block.x0) in columns
            near = block.x0 - left.x1 <= _CELL_GAP * block.size
            if (
                block.x0 > left.x0 + 2 * block.size
                and overlap >= 0.5 * height
                and (near or aligned)
            ):
                row.append(block)
                continue
        rows.append([block])
    return rows


def _regions(rows: list[list[_Block]]) -> list[_Region]:
    regions: list[_Region] = []
    for row in rows:
        text = " | ".join(b.text().replace("\n", " ") if len(row) > 1 else b.text() for b in row)
        x0, x1 = min(b.x0 for b in row), max(b.x1 for b in row)
        top, bottom = max(b.top for b in row), min(b.bottom for b in row)
        size = max(b.size for b in row)
        region = regions[-1] if regions else None
        if region is not None:
            gap = region.bottom - top
            close = -0.5 * size <= gap <= _REGION_GAP * max(size, region.size)
            overlaps = min(x1, region.x1) > max(x0, region.x0)
            heading = size > region.size * (1 + _SIZE_CHANGE)
            if close and overlaps and not heading:
                region.rows.append(text)
                region.x0, region.x1 = min(region.x0, x0), max(region.x1, x1)
                region.bottom, region.size = bottom, size
                continue
        regions.append(_Region([text], x0, x1, bottom, size))
    return regions


def layout_text(page: Any) -> str | None:
    """The page's text as regions separated by blank lines, or None if not derivable."""
    runs = page_runs(page)
    if runs is None:
        return None
    ratio = _char_ratio(runs)
    columns, line_starts = _column_starts(runs, ratio)
    lines = _lines(runs, columns, line_starts, ratio)
    cells = [c.text.strip() for line in lines if len(line.cells) > 1 for c in line.cells]
    fragments = sum(1 for c in cells if len(re.sub(r"\W", "", c)) <= 2)
    if cells and fragments > _FRAGMENT_SHARE * len(cells):
        return None  # cells look like pieces of words: positions are not trustworthy
    regions = _regions(_rows(_blocks(lines), columns))
    return "\n\n".join("\n".join(r.rows) for r in regions)
