"""Build the two synthetic PDF fixtures of the structural-retrieval benchmark.

Deterministic: running it again rewrites byte-identical files. The PDFs use the
standard Helvetica font and absolutely positioned text, like slide and report
generators do, so they exercise multi-region pages and tables with wrapped cells
without any third-party content. Run from the repository root:

    backend/.venv/bin/python evaluation/datasets/structure/build_pdf_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"

# (x, y, font size, text); y is measured from the bottom of the page.
Run = tuple[float, float, float, str]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[Run]], width: int, height: int) -> bytes:
    """One content stream per page; runs are written in the order given."""
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
        f"/Count {len(pages)} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for page_id, runs in zip(page_ids, pages, strict=True):
        ops = " ".join(
            f"BT /F1 {size:g} Tf 1 0 0 1 {x:g} {y:g} Tm ({_escape(text)}) Tj ET"
            for x, y, size, text in runs
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        )
        objects[page_id + 1] = f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("cp1252")
    xref_at = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def _box(x: float, y: float, size: float, lines: list[str], leading: float = 1.2) -> list[Run]:
    """A text box: one run per line, top line first (emitted as one unit)."""
    return [(x, y - i * size * leading, size, line) for i, line in enumerate(lines)]


def northwind_tiers() -> bytes:
    """Slide-style page, 960x540: title, stats row, prose region, tier table, limitations list.

    Emitted box by box (like presentation software); table cells are separate boxes,
    and wrapped cells continue on the next line inside their own box.
    """
    runs: list[Run] = []
    runs += _box(300, 500, 26, ["NORTHWIND CLOUD PLAN OVERVIEW"])
    # stats row (three cards)
    runs += _box(60, 450, 20, ["99.95%"]) + _box(40, 430, 10, ["monthly uptime target"])
    runs += _box(260, 450, 20, ["3"]) + _box(230, 430, 10, ["storage regions in the EU"])
    runs += _box(460, 450, 20, ["30 days"]) + _box(440, 430, 10, ["deleted-file recovery window"])
    # left region: prose
    runs += _box(40, 380, 14, ["About the plans"])
    runs += _box(
        40,
        355,
        10,
        [
            "Every plan encrypts files at rest and in transit. Upgrades take",
            "effect immediately; downgrades take effect at the start of the next",
            "billing cycle. The public status API is limited to 60 requests per",
            "minute for every customer, independent of the plan.",
        ],
    )
    runs += _box(40, 270, 14, ["Billing"])
    runs += _box(
        40,
        245,
        10,
        [
            "Invoices are issued on the first working day of each month and are",
            "payable within 21 days. Annual contracts receive a 12% discount.",
        ],
    )
    # right region: table, cell by cell
    runs += _box(600, 380, 14, ["Service tiers and limitations"])
    runs += _box(520, 355, 10, ["Tier"]) + _box(640, 355, 10, ["Limitations"])
    runs += _box(520, 330, 10, ["Starter"])
    runs += _box(640, 336, 10, ["50 GB storage; no shared folders;", "email support only"])
    runs += _box(520, 296, 10, ["Team"])
    runs += _box(640, 302, 10, ["2 TB storage; API limited to 1,000", "requests per minute"])
    runs += _box(520, 262, 10, ["Enterprise"])
    runs += _box(640, 268, 10, ["No storage cap; audit log retained", "for 400 days"])
    runs += _box(520, 228, 10, ["Education"])
    runs += _box(640, 234, 10, ["Only for accredited schools; single", "sign-on not included"])
    # bottom region: support hours
    runs += _box(520, 160, 14, ["Support hours"])
    runs += _box(520, 138, 10, ["- Chat: weekdays 08:00-20:00 CET"])
    runs += _box(520, 124, 10, ["- Phone: Enterprise only, around the clock"])
    return build_pdf([runs], 960, 540)


def incident_matrix() -> bytes:
    """Report-style A4 pages, 595x842, emitted row-major across the table columns
    (as some report generators do), plus a prose page with overlapping keywords."""
    page1: list[Run] = []
    page1 += _box(60, 780, 18, ["Incident severity matrix"])
    page1 += _box(
        60,
        750,
        10,
        [
            "Operations teams classify every production incident with this matrix",
            "before paging anyone. Response time is measured from detection.",
        ],
    )
    cols = (60, 140, 330, 480)
    header = ["Severity", "Example", "Required action", "Response time"]
    rows = [
        ("SEV-1", ["Full outage of", "customer logins"], ["Page the on-call lead and", "open a bridge call"], ["15 minutes"]),
        ("SEV-2", ["Payments delayed", "for one region"], ["Notify the duty manager and", "post a status update"], ["4 hours"]),
        ("SEV-3", ["Single report export", "failing"], ["Create a ticket for the", "owning team"], ["2 working days"]),
        ("SEV-4", ["Cosmetic issue in", "the admin console"], ["Add to the backlog"], ["Next release"]),
    ]  # fmt: skip
    y = 700.0
    for x, text in zip(cols, header, strict=True):
        page1.append((x, y, 10, text))
    y -= 24
    for sev, example, action, response in rows:
        depth = max(len(example), len(action), len(response))
        for i in range(depth):  # row-major: line i of every cell, left to right
            for x, cell in zip(cols, [[sev], example, action, response], strict=True):
                if i < len(cell):
                    page1.append((x, y - i * 12, 10, cell[i]))
        y -= 12 * depth + 14
    page2: list[Run] = []
    page2 += _box(60, 780, 16, ["Lessons from the 2025 pilot"])
    page2 += _box(
        60,
        755,
        10,
        [
            "During the pilot the operations board reviewed SEV-2 incidents every",
            "Thursday. Their average resolution time was 9 hours, and most of the",
            "delay came from waiting for the payment provider. The board recommends",
            "rehearsing the bridge call for SEV-1 incidents twice a year.",
        ],
    )
    return build_pdf([page1, page2], 595, 842)


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    (CORPUS / "northwind_service_tiers.pdf").write_bytes(northwind_tiers())
    (CORPUS / "incident_severity_matrix.pdf").write_bytes(incident_matrix())


if __name__ == "__main__":
    main()
