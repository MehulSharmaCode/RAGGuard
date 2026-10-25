"""Evaluation dataset schema, loading, validation, and fingerprinting.

The dataset is a version-controlled JSON file plus a corpus directory of fixture
documents (see `evaluation/datasets/README.md`). It is validated before every run:
schema and labels by Pydantic, then cross-checks against the corpus (duplicate IDs,
missing sources, reference facts that do not occur in their expected sources).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Answerability = Literal["answerable", "unanswerable"]
Category = Literal[
    "factual",
    "paraphrased",
    "low_overlap_paraphrase",
    "multi_fact",
    "source_selection",
    "multi_source",
    "historical",
    "false_premise",
    "outdated_source",
    "conflicting_sources",
    "resolvable_conflict",
    "prompt_injection",
    "injection_benign_control",
    "related_unanswerable",
    "lookalike_unanswerable",
    "unrelated",
]
DiagnosticKind = Literal["outdated_source", "conflicting_sources", "resolvable_conflict"]
AttackVector = Literal[
    "instruction_override",
    "system_prompt_extraction",
    "canary_exfiltration",
    "role_play",
    "authority_impersonation",
    "priority_manipulation",
    "embedded_in_document",
    "irrelevant_passage",
    "mixed_with_facts",
    "distributed_documents",
    "forced_fabrication",
    "misleading_citation",
    "citation_suppression",
    "denial_of_service",
    "markup_injection",
    "obfuscated_payload",
    "data_exfiltration_link",
    "goal_hijack",
    "fake_transcript",
    "social_engineering",
    "fake_tool_call",
    "cross_document_exfiltration",
    "policy_disguise",
    "summarisation_hijack",
]
AttackChannel = Literal["document", "user_query", "multi_document"]

ANSWERABLE_CATEGORIES: frozenset[str] = frozenset(
    {
        "factual",
        "paraphrased",
        "low_overlap_paraphrase",
        "multi_fact",
        "source_selection",
        "multi_source",
        "historical",
        "false_premise",
        "outdated_source",
        "conflicting_sources",
        "resolvable_conflict",
        "injection_benign_control",
    }
)
UNANSWERABLE_CATEGORIES: frozenset[str] = frozenset(
    {"related_unanswerable", "lookalike_unanswerable", "unrelated"}
)
DIAGNOSTIC_CATEGORIES: frozenset[str] = frozenset(
    {"outdated_source", "conflicting_sources", "resolvable_conflict"}
)
SUPPORTED_CORPUS_SUFFIXES = (".txt", ".pdf")

_CASE_ID = r"^[A-Z]{3}(-[A-Z]{3})?-\d{3}$"


def _check_patterns(patterns: list[str]) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regular expression pattern {pattern!r}: {exc}") from exc


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequiredFact(_Strict):
    """A fact a correct answer must state; matched case-insensitively on word boundaries."""

    description: str = Field(min_length=1)
    match_any: list[str] = Field(min_length=1)


class DiagnosticSpec(_Strict):
    """Outdated-source and conflict diagnostics (lexical findings, not proof)."""

    kind: DiagnosticKind
    # Values that are only true in an outdated or replaced source.
    stale_strings: list[str] = Field(default_factory=list)
    # Words indicating that the answer acknowledges a superseded or conflicting source.
    acknowledgement_terms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_kind(self) -> DiagnosticSpec:
        if self.kind in ("outdated_source", "resolvable_conflict") and not self.stale_strings:
            raise ValueError(f"{self.kind} diagnostics need stale_strings")
        if self.kind == "conflicting_sources" and not self.acknowledgement_terms:
            raise ValueError("conflicting_sources diagnostics need acknowledgement_terms")
        return self


class AttackSpec(_Strict):
    """A prompt-injection scenario and its explicit, case-specific success criteria.

    The attack counts as **succeeded** when the answer contains a canary, a success
    string, or matches a success pattern; cites a forbidden source; contains an invalid
    citation (`forbid_invalid_citations`); lacks a valid citation (`must_cite`); or,
    when `abandonment_is_success`, fails the legitimate task. `echo_strings` only show
    that the answer repeated injected wording and do not count as success.
    """

    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    vector: AttackVector
    channel: AttackChannel
    objective: str = Field(min_length=1)
    injection_sources: list[str] = Field(default_factory=list)
    canaries: list[str] = Field(default_factory=list)
    success_strings: list[str] = Field(default_factory=list)
    success_patterns: list[str] = Field(default_factory=list)
    echo_strings: list[str] = Field(default_factory=list)
    forbidden_cited_sources: list[str] = Field(default_factory=list)
    must_cite: bool = False
    forbid_invalid_citations: bool = False
    abandonment_is_success: bool = False

    @model_validator(mode="after")
    def _check(self) -> AttackSpec:
        if self.channel == "user_query" and self.injection_sources:
            raise ValueError("user_query attacks have no injection_sources")
        if self.channel == "document" and len(self.injection_sources) != 1:
            raise ValueError("document attacks need exactly one injection source")
        if self.channel == "multi_document" and len(self.injection_sources) < 2:
            raise ValueError("multi_document attacks need at least two injection sources")
        if not (
            self.canaries
            or self.success_strings
            or self.success_patterns
            or self.forbidden_cited_sources
            or self.must_cite
            or self.forbid_invalid_citations
            or self.abandonment_is_success
        ):
            raise ValueError("an attack needs at least one success criterion")
        _check_patterns(self.success_patterns)
        return self


class EvalCase(_Strict):
    id: str = Field(pattern=_CASE_ID)
    question: str = Field(min_length=1, max_length=2000)
    answerability: Answerability
    category: Category
    reference_answer: str | None
    expected_sources: list[str]
    required_facts: list[RequiredFact]
    # Sources that are replaced by another document: citing them as support for a
    # current claim is flagged (except in `historical` cases, which ask about the past).
    superseded_sources: list[str] = Field(default_factory=list)
    # Content that must not appear in any answer to this case (unsupported claims).
    forbidden_strings: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    diagnostics: DiagnosticSpec | None = None
    attack: AttackSpec | None = None
    # Optional page-level expectation for PDF sources (filename -> 1-based pages). When
    # given, every required fact must occur on those pages (see `_cross_check`).
    expected_pages: dict[str, list[int]] = Field(default_factory=dict)
    notes: str = Field(min_length=1)

    @property
    def is_answerable(self) -> bool:
        return self.answerability == "answerable"

    @model_validator(mode="after")
    def _check_consistency(self) -> EvalCase:
        if self.is_answerable:
            if not (self.reference_answer and self.reference_answer.strip()):
                raise ValueError("answerable cases need a reference_answer")
            if not self.expected_sources:
                raise ValueError("answerable cases need at least one expected source")
            if not self.required_facts:
                raise ValueError("answerable cases need at least one required fact")
            if self.category in UNANSWERABLE_CATEGORIES:
                raise ValueError(f"category {self.category!r} is for unanswerable cases")
        else:
            if self.expected_sources or self.required_facts:
                raise ValueError(
                    "unanswerable cases must not list expected sources or required facts"
                )
            if self.category in ANSWERABLE_CATEGORIES:
                raise ValueError(f"category {self.category!r} is for answerable cases")
        if len(set(self.expected_sources)) != len(self.expected_sources):
            raise ValueError("expected_sources contains duplicates")
        unknown = set(self.expected_pages) - set(self.expected_sources)
        if unknown:
            raise ValueError(f"expected_pages refers to non-expected sources: {sorted(unknown)}")
        if any(not pages or min(pages) < 1 for pages in self.expected_pages.values()):
            raise ValueError("expected_pages lists must be non-empty, 1-based page numbers")
        if self.category in DIAGNOSTIC_CATEGORIES:
            if self.diagnostics is None or self.diagnostics.kind != self.category:
                raise ValueError(f"category {self.category!r} needs matching diagnostics")
        elif self.diagnostics is not None:
            raise ValueError("diagnostics are only allowed for diagnostic categories")
        if (self.category == "prompt_injection") != (self.attack is not None):
            raise ValueError("prompt_injection cases (and only they) need an attack spec")
        _check_patterns(self.forbidden_patterns)
        return self


class EvalDataset(_Strict):
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    corpus_dir: str = Field(min_length=1)
    cases: list[EvalCase] = Field(min_length=1)


class DatasetValidationError(Exception):
    """The dataset cannot be used; `problems` lists every problem found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("Invalid evaluation dataset:\n- " + "\n- ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class CorpusFile:
    filename: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class LoadedDataset:
    path: Path
    dataset: EvalDataset
    corpus: list[CorpusFile]  # sorted by filename
    fingerprint: str  # sha256 over the dataset file and every corpus file


_MARKDOWN_EMPHASIS = re.compile(r"[*`]")


def contains_term(text: str, term: str) -> bool:
    """Case-insensitive match of `term` in `text` that does not start or end inside a word,
    so "9" does not match "2025" and "60 days" does not match "160 days"."""
    pattern = r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)"
    # Markdown emphasis and code markers ("**not** accepted") must not hide a match.
    return re.search(pattern, _MARKDOWN_EMPHASIS.sub("", text), re.IGNORECASE) is not None


def matched_terms(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if contains_term(text, t)]


def _page_texts(file: CorpusFile) -> dict[int | None, str]:
    """Text per page as the pipeline sees it (TXT files: one page, key None)."""
    if file.filename.lower().endswith(".txt"):
        return {None: file.content.decode("utf-8")}
    from app.ingestion.extraction import extract_document

    return {page.page_number: page.text for page in extract_document("pdf", file.content).pages}


def _corpus_text(file: CorpusFile) -> str:
    return "\n".join(_page_texts(file).values())


def _fingerprint(dataset_bytes: bytes, corpus: list[CorpusFile]) -> str:
    digest = hashlib.sha256()
    digest.update(b"dataset.json\0" + dataset_bytes + b"\0")
    for file in corpus:
        digest.update(file.filename.encode() + b"\0" + file.content + b"\0")
    return digest.hexdigest()


def _read_corpus(corpus_dir: Path, problems: list[str]) -> list[CorpusFile]:
    if not corpus_dir.is_dir():
        problems.append(f"corpus directory not found: {corpus_dir}")
        return []
    files: list[CorpusFile] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_CORPUS_SUFFIXES:
            problems.append(f"corpus file {path.name!r} is not a .txt or .pdf file")
            continue
        content = path.read_bytes()
        if not content.strip():
            problems.append(f"corpus file {path.name!r} is empty")
            continue
        files.append(CorpusFile(path.name, content, hashlib.sha256(content).hexdigest()))
    if not files and not problems:
        problems.append(f"corpus directory {corpus_dir} contains no documents")
    return files


def _cross_check(dataset: EvalDataset, corpus: list[CorpusFile]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for case in dataset.cases:
        if case.id in seen:
            problems.append(f"duplicate case id {case.id!r}")
        seen.add(case.id)

    from app.generation.prompts import SYSTEM_PROMPT  # extraction targets live here

    pages = {f.filename: _page_texts(f) for f in corpus}
    texts = {name: "\n".join(by_page.values()) for name, by_page in pages.items()}
    all_text = "\n".join(texts.values())
    for case in dataset.cases:
        attack = case.attack
        referenced = {
            "expected source": case.expected_sources,
            "superseded source": case.superseded_sources,
            "injection source": attack.injection_sources if attack else [],
            "forbidden cited source": attack.forbidden_cited_sources if attack else [],
        }
        missing = False
        for label, names in referenced.items():
            for name in names:
                if name not in texts:
                    problems.append(f"{case.id}: {label} {name!r} is not in the corpus")
                    missing = True
        if missing:
            continue
        # Every reference fact must be literally present in at least one expected source,
        # so references cannot drift away from the fixtures.
        source_text = "\n".join(texts[s] for s in case.expected_sources)
        for fact in case.required_facts:
            if not matched_terms(source_text, fact.match_any):
                problems.append(
                    f"{case.id}: required fact {fact.description!r} does not occur in its "
                    "expected sources"
                )
        if case.expected_pages:
            missing_pages = [
                f"{name} p{page}"
                for name, listed in case.expected_pages.items()
                for page in listed
                if page not in pages[name]
            ]
            if missing_pages:
                problems.append(f"{case.id}: expected pages have no text: {missing_pages}")
            page_text = (
                "\n".join(
                    pages[name].get(page, "")
                    for name, listed in case.expected_pages.items()
                    for page in listed
                )
                + "\n"
                + "\n".join(texts[s] for s in case.expected_sources if s not in case.expected_pages)
            )
            for fact in case.required_facts:
                if not matched_terms(page_text, fact.match_any):
                    problems.append(
                        f"{case.id}: required fact {fact.description!r} does not occur on its "
                        "expected pages"
                    )
        spec = case.diagnostics
        if (
            spec is not None
            and spec.stale_strings
            and not matched_terms(all_text, spec.stale_strings)
        ):
            problems.append(f"{case.id}: no stale string occurs anywhere in the corpus")
        if attack is not None and attack.vector != "obfuscated_payload":
            # Attack markers must exist where the model could copy them from: the injected
            # documents, the question itself, or the system prompt (extraction attacks).
            reachable = "\n".join([all_text, case.question, SYSTEM_PROMPT])
            for canary in attack.canaries:
                if not matched_terms(reachable, [canary]):
                    problems.append(f"{case.id}: canary {canary!r} does not occur in the corpus")
            if attack.success_strings and not matched_terms(reachable, attack.success_strings):
                problems.append(f"{case.id}: no success string occurs in the corpus or prompt")
    return problems


def load_dataset(path: Path) -> LoadedDataset:
    """Load and validate the dataset; raise DatasetValidationError listing all problems."""
    if not path.is_file():
        raise DatasetValidationError([f"dataset file not found: {path}"])
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DatasetValidationError([f"dataset file is not valid JSON: {exc}"]) from exc

    problems: list[str] = []
    # Duplicate IDs are reported even when other schema errors exist.
    if isinstance(data, dict) and isinstance(data.get("cases"), list):
        ids = [str(c.get("id")) for c in data["cases"] if isinstance(c, dict)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        problems += [f"duplicate case id {i!r}" for i in duplicates]
    try:
        dataset = EvalDataset.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            problems.append(f"{location}: {error['msg']}")
        raise DatasetValidationError(problems) from exc

    corpus = _read_corpus(path.parent / dataset.corpus_dir, problems)
    problems += [p for p in _cross_check(dataset, corpus) if p not in problems]
    if problems:
        raise DatasetValidationError(problems)
    return LoadedDataset(path, dataset, corpus, _fingerprint(raw, corpus))
