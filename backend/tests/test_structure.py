"""Structure-aware extraction, chunking, sub-units, and retrieval (D-063).

The PDF fixtures live in `evaluation/datasets/structure/corpus/` (synthetic, built by
`build_pdf_fixtures.py`) plus the copy of the VEIL proposal. Retrieval tests use the real
embedding model only when it is already cached (like `test_embeddings_model.py`) and never
call an LLM; they check what reaches the evidence gate, not answers.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.core.config import REPO_ROOT
from app.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.ingestion import extraction
from app.ingestion.chunking import (
    SUBUNIT_MIN_TOKENS,
    chunk_pages,
    is_heading,
    sub_units,
)
from app.ingestion.extraction import PageText, extract_document
from app.retrieval.evidence import LEGACY_MIN_RETRIEVAL_SCORE, evidence_threshold
from tests.conftest import FakeEmbedder, make_pdf

CORPUS = REPO_ROOT / "evaluation" / "datasets" / "structure" / "corpus"
VEIL_PDF = CORPUS / "SIH2026_BinaryBrainCells_PS_26171.pdf"
THRESHOLD = 0.35  # default MIN_RETRIEVAL_SCORE for the sub-unit index


def _pages(name: str) -> list[PageText]:
    path = CORPUS / name
    return extract_document("pdf" if path.suffix == ".pdf" else "txt", path.read_bytes()).pages


# --- extraction ------------------------------------------------------------------
def test_table_cells_written_as_separate_boxes_stay_in_their_row() -> None:
    [page] = _pages("northwind_service_tiers.pdf")
    assert "Team | 2 TB storage; API limited to 1,000 requests per minute" in page.text
    assert "Education | Only for accredited schools; single sign-on not included" in page.text
    # A heading starts its own line above its paragraph, and regions are separated.
    assert "About the plans\nEvery plan encrypts files" in page.text
    assert "\n\nService tiers and limitations\nTier | Limitations\nStarter |" in page.text


def test_pdf_written_in_character_fragments_keeps_its_words() -> None:
    # The AgriSense PDF writes text in kerned runs of one to a few characters; the first
    # layout extractor split its words into cells ("Agr | iSens | e") (D-064).
    path = REPO_ROOT / "evaluation" / "datasets" / "agrisense" / "corpus"
    [pdf] = path.glob("*.pdf")
    data = pdf.read_bytes()
    pages = extract_document("pdf", data).pages
    text = "\n".join(page.text for page in pages)
    plain = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    assert len(pages) == 22
    assert "AgriSense" in pages[0].text and "Agr |" not in text
    assert text.count("AgriSense") >= plain.count("AgriSense")
    assert len(text) <= 1.05 * len(plain)


def test_row_major_table_with_wrapped_cells_is_rebuilt_row_by_row() -> None:
    page1, page2 = _pages("incident_severity_matrix.pdf")
    assert (
        "SEV-1 | Full outage of customer logins | Page the on-call lead and open a bridge call "
        "| 15 minutes"
    ) in page1.text
    assert "SEV-4 | Cosmetic issue in the admin console | Add to the backlog | Next release" in (
        page1.text
    )
    assert (page1.page_number, page2.page_number) == (1, 2)
    assert "average resolution time was 9 hours" in page2.text


def test_multi_region_slide_keeps_the_risk_table_together() -> None:
    page4 = next(
        p for p in extract_document("pdf", VEIL_PDF.read_bytes()).pages if p.page_number == 4
    )
    table = (
        "Risks → Mitigation\nRisk | Mitigation\n"
        "Free-tier rate limits | Retries + Groq to Gemini failover\n"
        "Heuristic PII detection | Fail-closed gate + canary tests\n"
        "One controlled page tested | Staged tests: React, then complex sites\n"
        "OCR-only visual slice | Add face detection and pixel redaction"
    )
    assert table in page4.text
    regions = [r for r in page4.text.split("\n\n") if "Risks → Mitigation" in r]
    assert regions == [table]  # no other section is interleaved with the table


def test_simple_pdf_text_is_unchanged_apart_from_reflowed_lines() -> None:
    pages = extract_document("pdf", make_pdf(["Alpha line one\nAlpha line two", "", "Gamma"])).pages
    assert [(p.page_number, p.text) for p in pages] == [
        (1, "Alpha line one Alpha line two"),
        (3, "Gamma"),
    ]


def test_layout_text_falls_back_to_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = make_pdf(["Alpha line one\nAlpha line two"])

    def broken(_page: object) -> str:
        raise RuntimeError("positions unusable")

    monkeypatch.setattr(extraction, "layout_text", broken)
    assert extract_document("pdf", pdf).pages[0].text == "Alpha line one\nAlpha line two"
    monkeypatch.setattr(extraction, "layout_text", lambda _page: "Alpha")  # would lose text
    assert extract_document("pdf", pdf).pages[0].text == "Alpha line one\nAlpha line two"


# --- chunking and sub-units ------------------------------------------------------
def test_regions_are_packed_whole_and_short_regions_attach_to_neighbours() -> None:
    text = (
        "Night access\n\n"  # heading-like: attaches forward
        + " ".join(f"rule{i}" for i in range(30))
        + "\n\n42\n\n"  # short label: attaches backward
        + " ".join(f"note{i}" for i in range(30))
    )
    chunks = chunk_pages([PageText(None, text)], FakeEmbedder(), chunk_size=40, overlap=5)
    assert [c.text.split()[0] for c in chunks] == ["Night", "note0"]
    assert chunks[0].text.endswith("rule29\n\n42")
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_oversized_region_still_uses_overlapping_windows() -> None:
    words = " ".join(f"w{i}" for i in range(100))
    chunks = chunk_pages(
        [PageText(None, f"Intro sentence here.\n\n{words}")], FakeEmbedder(), 30, 10
    )
    intro = FakeEmbedder().token_spans("Intro sentence here.")
    assert [c.token_count for c in chunks][:2] == [len(intro), 30]
    assert chunks[1].text.split()[-10:] == chunks[2].text.split()[:10]


def test_subunits_carry_their_heading_and_skip_short_fragments() -> None:
    text = (
        "Risks → Mitigation\nRisk | Mitigation\n"
        "Free-tier rate limits | Retries + Groq to Gemini failover\n"
        "Heuristic PII detection | Fail-closed gate + canary tests"
    )
    units = sub_units(text, FakeEmbedder())
    assert "Risks → Mitigation: Free-tier rate limits | Retries + Groq to Gemini failover" in units
    assert all(len(FakeEmbedder().token_spans(u)) >= SUBUNIT_MIN_TOKENS for u in units)
    assert "Risks → Mitigation" not in units  # a heading alone is never a unit


def test_long_lines_are_split_into_sentence_units() -> None:
    sentences = [
        f"Sentence {i} " + " ".join(f"word{i}x{j}" for j in range(20)) + "." for i in range(8)
    ]
    units = sub_units(" ".join(sentences), FakeEmbedder())
    assert len(units) > 2
    assert all(len(FakeEmbedder().token_spans(u)) <= 64 + 22 for u in units)


@pytest.mark.parametrize(
    "name",
    [
        "northwind_service_tiers.pdf",
        "incident_severity_matrix.pdf",
        "kestrel_ridge_staff_handbook.txt",
        "millbrook_reservoir_inspection_report.txt",
        "SIH2026_BinaryBrainCells_PS_26171.pdf",
    ],
)
def test_every_subunit_maps_back_to_its_chunk(name: str) -> None:
    """Sub-units are derived representations; each one must be traceable to the source."""

    def norm(value: str) -> str:
        return " ".join(value.split())

    for chunk in chunk_pages(_pages(name), FakeEmbedder(), 180, 30):
        body = norm(chunk.text)
        for unit in chunk.units:
            heading, sep, rest = unit.partition(": ")
            mapped = rest if sep and is_heading(heading) and heading in chunk.text else unit
            assert norm(mapped) in body or all(norm(p) in body for p in re.split(r"\s{2,}", mapped))


def test_threshold_follows_the_index_format() -> None:
    assert evidence_threshold(0.35, "subunit") == 0.35
    assert evidence_threshold(0.35, "legacy") == LEGACY_MIN_RETRIEVAL_SCORE == 0.30


# --- retrieval with the real embedding model (no LLM) ------------------------------
@pytest.fixture(scope="module")
def real_embedder() -> SentenceTransformerEmbedder:
    embedder = SentenceTransformerEmbedder(
        "sentence-transformers/all-MiniLM-L6-v2", local_files_only=True
    )
    try:
        _ = embedder.dimension
    except Exception:
        pytest.skip("all-MiniLM-L6-v2 is not in the local Hugging Face cache")
    return embedder


Index = list[tuple[str, str, list[list[float]]]]


@pytest.fixture(scope="module")
def index(real_embedder: SentenceTransformerEmbedder) -> Iterator[Index]:
    entries: Index = []
    for path in sorted(CORPUS.iterdir()):
        if path.suffix not in (".pdf", ".txt"):
            continue
        for chunk in chunk_pages(_pages(path.name), real_embedder, 180, 30):
            vectors = real_embedder.embed_documents([chunk.text, *chunk.units])
            entries.append((path.name, chunk.text, vectors))
    yield entries


def _evidence(
    index: Index, embedder: SentenceTransformerEmbedder, question: str
) -> list[tuple[float, str, str]]:
    query = embedder.embed_query(question)
    scored = [
        (max(sum(a * b for a, b in zip(query, v, strict=True)) for v in vectors), name, text)
        for name, text, vectors in index
    ]
    top = sorted(scored, reverse=True)[:4]
    return [hit for hit in top if hit[0] >= THRESHOLD]


@pytest.mark.parametrize(
    ("question", "source", "needed"),
    [
        # VEIL risk table, three wordings (the owner's Queries A-C)
        ("What mitigates free-tier rate limits?", "SIH2026", ["Retries", "Gemini failover"]),
        (
            "According to the 'Risks → Mitigation' table on page 4, what mitigation does VEIL "
            "specify for free-tier rate limits?",
            "SIH2026",
            ["Retries"],
        ),
        (
            "What risks does the proposal identify and what mitigation is proposed for each?",
            "SIH2026",
            ["Retries", "Fail-closed gate", "Staged tests", "face detection"],
        ),
        # independent fixtures: tables, nested lists, long paragraphs, similar documents
        ("What are the limitations of the Team tier?", "northwind", ["2 TB", "1,000"]),
        ("Which Northwind plan keeps audit logs the longest?", "northwind", ["400 days"]),
        pytest.param(
            "If customers cannot log in at all, who has to be paged?",
            "incident",
            ["on-call lead"],
            marks=pytest.mark.xfail(
                reason="Known limitation (2026-10-16): low-overlap paraphrase of a table row; "
                "the row scores 0.336 against the 0.35 gate (whole chunk before D-063: 0.113).",
                strict=True,
            ),
        ),
        ("Who is paged for a full outage of customer logins?", "incident", ["on-call lead"]),
        (
            "What is the required action for each severity level?",
            "incident",
            ["duty manager", "backlog"],
        ),
        ("Until what time may students stay at Kestrel Ridge?", "kestrel", ["02:00"]),
        (
            "What must staff do if there is a thunderstorm nearby?",
            "kestrel",
            ["shut down all instruments"],
        ),
        (
            "What was the maximum settlement measured at the reservoir?",
            "millbrook",
            ["18 millimetres"],
        ),
        ("How much is the annual parking permit on the South Campus?", "south_campus", ["310"]),
    ],
)
def test_needed_evidence_passes_the_gate(
    index: Index,
    real_embedder: SentenceTransformerEmbedder,
    question: str,
    source: str,
    needed: list[str],
) -> None:
    evidence = _evidence(index, real_embedder, question)
    text = "\n".join(t for _, name, t in evidence if source in name)
    missing = [fact for fact in needed if fact not in text]
    assert not missing, f"missing {missing}; evidence: {[(round(s, 3), n) for s, n, _ in evidence]}"


UNRELATED = [
    "What is the boiling point of liquid nitrogen?",
    "Who painted the Mona Lisa?",
    "What is the capital city of Australia?",
    "How many players are on a basketball team?",
    "When did the Second World War end?",
    "What is photosynthesis?",
    "Who wrote Pride and Prejudice?",
    "How far is the Moon from Earth?",
    "What is the speed of light?",
    "Can you give me a recipe for banana bread?",
    "Who won the 2018 FIFA World Cup?",
    "What is the tallest mountain in Africa?",
    "How do I change a car tyre?",
    "What does DNA stand for?",
    "Which planet has the most moons?",
    "What is the population of Brazil?",
    "How long should I boil an egg?",
    "Who discovered penicillin?",
    "What is the exchange rate between yen and euro?",
    "What causes the northern lights?",
]


def test_unrelated_questions_stay_below_the_gate(
    index: Index, real_embedder: SentenceTransformerEmbedder
) -> None:
    leaked = [q for q in UNRELATED if _evidence(index, real_embedder, q)]
    assert leaked == []


def test_similar_documents_do_not_swap_facts(
    index: Index, real_embedder: SentenceTransformerEmbedder
) -> None:
    evidence = _evidence(
        index, real_embedder, "How much is the annual parking permit on the South Campus?"
    )
    assert evidence[0][1] == "harlow_parking_permits_south_campus.txt"


def test_fixture_pdfs_are_reproducible(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_pdf_fixtures", CORPUS.parent / "build_pdf_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.northwind_tiers() == (CORPUS / "northwind_service_tiers.pdf").read_bytes()
    assert module.incident_matrix() == (CORPUS / "incident_severity_matrix.pdf").read_bytes()
