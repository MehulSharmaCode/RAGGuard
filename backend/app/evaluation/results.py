"""Read-only access to saved evaluation reports for the API's Evaluation view.

Reports are the files the evaluation CLI writes to `EVALUATION_RESULTS_DIR/<run_id>/`.
Only directories directly inside that folder whose names match `RUN_ID_PATTERN` are
read, and only `report.json` / `report.md` inside them; no other path can be reached.
Views are built defensively from the JSON, so older report schemas (1.0) are shown
with their missing metrics marked unavailable rather than zero. Nothing here runs an
evaluation or imports the pipeline.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT
from app.core.errors import ReportNotFoundError, ReportUnreadableError
from app.evaluation.catalog import CATALOG, CatalogMetric
from app.schemas.evaluations import (
    AttackView,
    CaseView,
    EvaluationDetail,
    EvaluationList,
    EvaluationSummary,
    Finding,
    JudgeSummary,
    JudgeView,
    LatencySummary,
    MetricDefinitionView,
    MetricValue,
    PassageView,
)
from app.tracking.mlflow_tracking import extract_params

RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
REPORT_FILES = {
    "report.json": "application/json",
    "report.md": "text/markdown; charset=utf-8",
}
EXCERPT_CHARS = 400
HEADLINE_KEYS = ("correctness.case_pass_rate", "security.attack_success_rate")
_DETAIL_CACHE_SIZE = 4

Json = dict[str, Any]


def redact_paths(text: str) -> str:
    """Replace absolute repository and home-directory paths with relative forms."""
    for prefix, replacement in (
        (str(REPO_ROOT) + os.sep, ""),
        (str(REPO_ROOT), "."),
        (str(Path.home()), "~"),
    ):
        text = text.replace(prefix, replacement)
    return text


def display_path(path: Path) -> str:
    """Repository-relative path, or only the final name for locations outside the repo."""
    resolved = path.resolve()
    root = REPO_ROOT.resolve()
    if resolved == root or root in resolved.parents:
        return resolved.relative_to(root).as_posix() or "."
    return f"{resolved.name} (outside the repository)"


# --- metrics -----------------------------------------------------------------------
def _lookup(node: Any, key: str) -> tuple[bool, Any]:
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def metric_value(spec: CatalogMetric, aggregates: Json | None) -> MetricValue:
    """The catalog metric as recorded in a report's aggregates (or unavailable)."""
    found, node = _lookup(aggregates or {}, spec.key)
    value: float | None = None
    numerator: float | None = None
    denominator: int | None = None
    if found and isinstance(node, dict):
        if {"value", "denominator"} <= node.keys():
            value = _number(node.get("value"))
            numerator = _number(node.get("numerator"))
            denominator = int(node["denominator"])
        else:
            found = False  # unexpected shape: do not guess
    elif found and node is not None:
        value = _number(node)
        found = value is not None
    return MetricValue(
        key=spec.key,
        label=spec.label,
        group=spec.group,
        direction=spec.direction,
        kind=spec.kind,
        supplementary=spec.supplementary,
        available=found,
        value=value,
        numerator=numerator,
        denominator=denominator,
    )


# --- summaries ---------------------------------------------------------------------
def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dict(value: Any) -> Json:
    return value if isinstance(value, dict) else {}


def _unreadable(run_id: str, problem: str) -> EvaluationSummary:
    return EvaluationSummary(
        run_id=run_id,
        readable=False,
        problem=problem,
        schema_version=None,
        detail_supported=False,
        started_at=None,
        finished_at=None,
        status=None,
        status_detail=None,
        rescored_from=None,
        dataset_id=None,
        dataset_version=None,
        dataset_fingerprint=None,
        cases_run=None,
        cases_in_dataset=None,
        params={},
        headline=[],
    )


def _supports_detail(report: Json) -> bool:
    schema = _str(report.get("schema_version")) or ""
    return schema.split(".")[0] in {"1", "2"} and isinstance(report.get("cases"), list)


def summarize(run_id: str, report: Json) -> EvaluationSummary:
    dataset = _dict(report.get("dataset"))
    aggregates = _dict(report.get("aggregates")) or None
    by_key = {m.key: m for m in CATALOG}
    return EvaluationSummary(
        run_id=run_id,
        readable=True,
        problem=None,
        schema_version=_str(report.get("schema_version")),
        detail_supported=_supports_detail(report),
        started_at=_str(report.get("started_at")),
        finished_at=_str(report.get("finished_at")),
        status=_str(report.get("status")),
        status_detail=_str(report.get("status_detail")),
        rescored_from=_str(report.get("rescored_from")),
        dataset_id=_str(dataset.get("dataset_id")),
        dataset_version=_str(dataset.get("version")),
        dataset_fingerprint=_str(dataset.get("fingerprint_sha256")),
        cases_run=_int(dataset.get("cases_run")),
        cases_in_dataset=_int(dataset.get("cases_in_dataset")),
        params=extract_params(report),
        headline=[metric_value(by_key[k], aggregates) for k in HEADLINE_KEYS],
    )


# --- cases -------------------------------------------------------------------------
def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("description"), str):
            out.append(item["description"])
    return out


def _excerpt(value: Any) -> str:
    text: str = value if isinstance(value, str) else ""
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rstrip() + "…"


def case_findings(case: Json) -> list[Finding]:
    """Every recorded problem of one case, in a fixed order (empty for a clean pass)."""
    findings: list[Finding] = []

    def add(kind: Any, detail: str) -> None:
        findings.append(Finding(kind=kind, detail=detail))

    answerable = case.get("answerability") == "answerable"
    outcome = case.get("outcome")
    error = _dict(case.get("error"))
    facts = _dict(case.get("facts"))
    citations = _dict(case.get("citations"))
    support = _dict(case.get("citation_support"))
    retrieval = _dict(case.get("retrieval"))
    attack = _dict(case.get("attack"))
    judge = _dict(case.get("judge"))
    verdict = _dict(judge.get("verdict"))

    if error:
        stage = error.get("stage", "pipeline")
        add("pipeline_error", f"{stage} failed: {error.get('code')} — {error.get('message')}")
    if answerable and outcome == "fallback":
        add(
            "false_refusal",
            f"Safe fallback ({case.get('fallback_reason')}) although the documents answer it.",
        )
    if not answerable and outcome == "answered":
        add("false_answer", "Answered a question the documents do not answer.")
    missing = _strings(facts.get("missing"))
    if answerable and outcome == "answered" and missing:
        add("missing_facts", "Required fact not found: " + "; ".join(missing))
    if case.get("unsupported_content"):
        add(
            "unsupported_content",
            "Forbidden content in the answer: " + ", ".join(_strings(case["unsupported_content"])),
        )
    if attack.get("status") == "succeeded":
        add("attack_succeeded", "; ".join(_strings(attack.get("reasons"))) or "Attack succeeded.")
    if attack.get("canary_leaked") is True:
        add("canary_leak", "A synthetic canary string appeared in the answer.")
    invalid = _strings(citations.get("invalid_ids"))
    if invalid:
        add("invalid_citation", "Cited IDs that were not in the evidence: " + ", ".join(invalid))
    superseded = _strings(case.get("superseded_citations"))
    if superseded:
        add("superseded_citation", "Superseded source cited: " + ", ".join(superseded))
    unsupported = _strings(support.get("unsupported"))
    if unsupported:
        add(
            "unsupported_citation",
            "Cited passage does not contain the stated fact: " + "; ".join(unsupported),
        )
    uncited = _strings(support.get("uncited"))
    if uncited:
        add("uncited_fact", "Fact stated without a citation: " + "; ".join(uncited))
    if answerable and retrieval.get("hit_at_k") is False:
        add(
            "retrieval_miss",
            "No expected source in the top-k: expected "
            + ", ".join(_strings(retrieval.get("expected_sources"))),
        )
    if judge.get("status") == "error":
        add("judge_error", str(judge.get("error") or "The judge output could not be used."))
    if verdict.get("unsupported_claims") is True:
        add("judge_flag", "The LLM judge flagged unsupported claims (supplementary).")
    return findings


def _verdict(case: Json) -> Any:
    if "correct" not in case:
        return "error" if case.get("error") else "unscored"
    correct = case.get("correct")
    return "pass" if correct is True else "fail" if correct is False else "error"


def case_view(case: Json) -> CaseView:
    citations = _dict(case.get("citations"))
    facts = _dict(case.get("facts"))
    valid_ids = set(_strings(citations.get("valid_ids")))
    attack = _dict(case.get("attack"))
    judge = _dict(case.get("judge"))
    verdict = _dict(judge.get("verdict"))
    error = _dict(case.get("error"))
    diagnostic = _dict(case.get("diagnostic"))
    passages = [
        PassageView(
            rank=int(p.get("rank", i + 1)),
            filename=str(p.get("filename", "")),
            page_number=_int(p.get("page_number")),
            score=float(p.get("score") or 0.0),
            above_threshold=bool(p.get("above_threshold")),
            source_id=_str(p.get("source_id")),
            cited=p.get("source_id") in valid_ids,
            excerpt=_excerpt(p.get("text")),
        )
        for i, p in enumerate(case.get("retrieved") or [])
        if isinstance(p, dict)
    ]
    return CaseView(
        case_id=str(case.get("case_id", "")),
        category=str(case.get("category", "")),
        answerability=str(case.get("answerability", "")),
        question=str(case.get("question", "")),
        reference_answer=_str(case.get("reference_answer")),
        expected_sources=_strings(case.get("expected_sources")),
        superseded_sources=_strings(case.get("superseded_sources")),
        required_facts=_strings(case.get("required_facts")),
        notes=_str(case.get("notes")),
        verdict=_verdict(case),
        outcome=_str(case.get("outcome")),
        fallback_reason=_str(case.get("fallback_reason")),
        answer=_str(case.get("answer")),
        llm_called=case.get("llm_called") if isinstance(case.get("llm_called"), bool) else None,
        max_score=_number(case.get("max_score")),
        latency_ms=_number(case.get("latency_ms")),
        facts_found=_strings(facts.get("found")),
        facts_missing=_strings(facts.get("missing")),
        cited_filenames=_strings(citations.get("cited_filenames")),
        invalid_citation_ids=_strings(citations.get("invalid_ids")),
        findings=case_findings(case),
        attack=AttackView(
            scenario_id=str(attack.get("scenario_id", "")),
            vector=str(attack.get("vector", "")),
            channel=str(attack.get("channel", "")),
            status=str(attack.get("status", "")),
            reasons=_strings(attack.get("reasons")),
            canary_leaked=attack.get("canary_leaked"),
            echoed=_strings(attack.get("echoed")),
            task_completed=attack.get("task_completed"),
        )
        if attack
        else None,
        diagnostic=_str(diagnostic.get("finding")),
        judge=JudgeView(
            status=str(judge.get("status", "")),
            correctness=_int(verdict.get("correctness")),
            groundedness=_int(verdict.get("groundedness")),
            completeness=_int(verdict.get("completeness")),
            unsupported_claims=verdict.get("unsupported_claims"),
            citations_support_claims=verdict.get("citations_support_claims"),
            unanswerable_handled_correctly=verdict.get("unanswerable_handled_correctly"),
            rationale=_str(verdict.get("rationale")),
            error=_str(judge.get("error")) or _str(judge.get("reason")),
        )
        if judge
        else None,
        error=f"{error.get('code')}: {error.get('message')}" if error else None,
        retrieved=passages,
    )


def _latency(aggregates: Json) -> dict[str, LatencySummary]:
    latency = _dict(aggregates.get("latency"))
    out: dict[str, LatencySummary] = {}
    for name in ("query", "query_with_generation", "query_without_generation"):
        stats = _dict(latency.get(name))
        if stats:
            out[name] = LatencySummary(
                count=_int(stats.get("count")) or 0,
                mean_ms=_number(stats.get("mean_ms")),
                median_ms=_number(stats.get("median_ms")),
                p95_ms=_number(stats.get("p95_ms")),
                min_ms=_number(stats.get("min_ms")),
                max_ms=_number(stats.get("max_ms")),
            )
    return out


def _judge(report: Json, aggregates: Json) -> JudgeSummary | None:
    judge = _dict(aggregates.get("judge"))
    if not judge:
        return None
    config = _dict(report.get("configuration"))
    same = config.get("judge_same_model_as_generation")
    return JudgeSummary(
        enabled=bool(judge.get("enabled")),
        model=_str(config.get("judge_model")),
        same_model_as_generation=same if isinstance(same, bool) else None,
        eligible_cases=_int(judge.get("eligible_cases")),
        scored=_int(judge.get("scored")),
        not_applicable=_int(judge.get("not_applicable")),
        errors=_strings(judge.get("errors")),
    )


def build_detail(run_id: str, report: Json) -> EvaluationDetail:
    aggregates = _dict(report.get("aggregates"))
    cases = report.get("cases") if _supports_detail(report) else []
    definitions = [
        MetricDefinitionView(
            name=str(d.get("name", "")),
            definition=str(d.get("definition", "")),
            denominator=str(d.get("denominator", "")),
        )
        for d in report.get("metric_definitions") or []
        if isinstance(d, dict)
    ]
    return EvaluationDetail(
        summary=summarize(run_id, report),
        fatal_error=_str(report.get("fatal_error")),
        metrics=[metric_value(spec, aggregates or None) for spec in CATALOG],
        latency=_latency(aggregates),
        judge=_judge(report, aggregates),
        cases=[case_view(c) for c in cases or [] if isinstance(c, dict)],
        metric_definitions=definitions,
        limitations=_strings(report.get("limitations")),
    )


# --- store -------------------------------------------------------------------------
class ReportStore:
    """Lists and reads reports below one results directory (thread-safe, cached)."""

    def __init__(self, results_dir: Path) -> None:
        self.root = results_dir
        self._lock = threading.Lock()
        self._summaries: dict[str, tuple[tuple[int, int], EvaluationSummary]] = {}
        self._details: OrderedDict[str, tuple[tuple[int, int], EvaluationDetail]] = OrderedDict()

    @property
    def display_root(self) -> str:
        return display_path(self.root)

    def _run_dir(self, run_id: str) -> Path:
        root = self.root.resolve()
        path = (root / run_id).resolve()
        # The route already validates the pattern; this also rejects symlinks leaving root.
        if path.parent != root or not path.is_dir():
            raise ReportNotFoundError(f"No saved evaluation report has the ID '{run_id}'.")
        return path

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _read(path: Path) -> Json:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ReportUnreadableError("report.json is not valid JSON.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("run_id"), str):
            raise ReportUnreadableError(
                "report.json does not look like a RAGGuard evaluation report."
            )
        return data

    def _summary(self, run_dir: Path) -> EvaluationSummary:
        path = run_dir / "report.json"
        if not path.is_file():
            return _unreadable(run_dir.name, "report.json is missing.")
        stamp = self._stamp(path)
        with self._lock:
            cached = self._summaries.get(run_dir.name)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            summary = summarize(run_dir.name, self._read(path))
        except ReportUnreadableError as exc:
            summary = _unreadable(run_dir.name, exc.message)
        with self._lock:
            self._summaries[run_dir.name] = (stamp, summary)
        return summary

    def list(self) -> EvaluationList:
        pattern = re.compile(RUN_ID_PATTERN)
        summaries: list[EvaluationSummary] = []
        if self.root.is_dir():
            for child in self.root.iterdir():
                if child.is_dir() and not child.is_symlink() and pattern.match(child.name):
                    summaries.append(self._summary(child))
        summaries.sort(key=lambda s: s.run_id, reverse=True)
        summaries.sort(key=lambda s: s.started_at or "", reverse=True)
        return EvaluationList(results_dir=self.display_root, reports=summaries)

    def detail(self, run_id: str) -> EvaluationDetail:
        path = self._run_dir(run_id) / "report.json"
        if not path.is_file():
            raise ReportUnreadableError("report.json is missing for this run.")
        stamp = self._stamp(path)
        with self._lock:
            cached = self._details.get(run_id)
            if cached and cached[0] == stamp:
                self._details.move_to_end(run_id)
                return cached[1]
        detail = build_detail(run_id, self._read(path))
        with self._lock:
            self._details[run_id] = (stamp, detail)
            while len(self._details) > _DETAIL_CACHE_SIZE:
                self._details.popitem(last=False)
        return detail

    def file(self, run_id: str, name: str) -> tuple[str, str]:
        """Text of report.json / report.md with absolute paths redacted, and its media type."""
        if name not in REPORT_FILES:
            raise ReportNotFoundError(f"'{name}' is not a report file.")
        path = self._run_dir(run_id) / name
        if not path.is_file():
            raise ReportNotFoundError(f"This run has no {name}.")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReportUnreadableError(f"{name} could not be read.") from exc
        return redact_paths(text), REPORT_FILES[name]

    def latest(self) -> EvaluationSummary | None:
        return next((s for s in self.list().reports if s.readable), None)
