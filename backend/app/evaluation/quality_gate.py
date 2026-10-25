"""Offline, model-free quality gate for CI (Stage 7, D-079-D-084).

Why it exists: the full evaluation (`run_evaluation`) needs a generation model, which routine CI
does not have (U-012). This gate measures what can be measured honestly *without* a model, with
the real production code and the real embedding model:

- the real ingestion (extraction, chunking, hybrid index) into a temporary embedded Qdrant store,
- the real retrieval and evidence selection (`RAGPipeline.retrieve_evidence`: dense gate, hybrid
  fusion, region merging, supersession policy),
- the real model input (`prompts.model_text`: instruction-like spans withheld),
- the existing dataset schema, fingerprints, and retrieval checks (`check_retrieval`).

No answer is generated, so nothing here says anything about answer quality: the full model-based
benchmark stays a separate, explicit operation. The thresholds live in ONE file,
`evaluation/quality_gate.json`, with their measured baselines and rationale.

Fail closed: a missing metric, an empty denominator, a changed dataset or configuration, a stale
or malformed measurement, a metric whose direction was edited, or any exception during the
measurement is a gate failure. Supplementary signals (the LLM judge) are reported but can never
turn a failure into a pass.

    python -m app.evaluation.quality_gate run               # measure + evaluate (embedding model)
    python -m app.evaluation.quality_gate validate-datasets # schema, version, fingerprint
    python -m app.evaluation.quality_gate evaluate FILE     # re-evaluate a stored measurement
    python -m app.evaluation.quality_gate junit FILE        # pytest result: no skips, xfails
    python -m app.evaluation.quality_gate list-datasets     # dataset paths, one per line
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import REPO_ROOT, Settings
from app.embeddings.base import Embedder
from app.evaluation.dataset import (
    DatasetValidationError,
    EvalCase,
    LoadedDataset,
    load_dataset,
    matched_terms,
)
from app.evaluation.metrics import EVALUATOR_VERSION, check_retrieval
from app.evaluation.runner import isolated_store, new_run_id, retrieval_passages
from app.generation.base import ProviderStatus
from app.generation.prompts import PROMPT_VERSION, model_text
from app.pipeline import RAGPipeline
from app.schemas.query import QueryRequest

GATE_FILE = REPO_ROOT / "evaluation" / "quality_gate.json"
SCHEMA_VERSION = "1.0"
EXIT_PASSED, EXIT_FAILED, EXIT_INVALID = 0, 1, 2
MAX_FAILING_IDS = 25

Direction = Literal["at_least", "at_most"]

# The direction of every metric is part of the gate's code, not only of its data file: editing a
# security metric into "at_least 0" in the JSON must not be able to disarm it.
METRIC_DIRECTIONS: dict[str, Direction] = {
    "retrieval.evidence_hit": "at_least",
    "retrieval.expected_page_hit": "at_least",
    "evidence.complete_cases": "at_least",
    "evidence.required_facts_visible": "at_least",
    "abstention.unrelated_below_gate": "at_least",
    "security.attack_source_in_evidence": "at_least",
    "security.payload_exposed_cases": "at_most",
    "supersession.stale_evidence_cases": "at_most",
}

METRIC_DESCRIPTIONS: dict[str, str] = {
    "retrieval.evidence_hit": "answerable cases with an expected source among the evidence",
    "retrieval.expected_page_hit": "cases with expected pages whose evidence includes such a page",
    "evidence.complete_cases": "answerable cases whose evidence has every required fact",
    "evidence.required_facts_visible": (
        "required facts in the text the model would receive (reported, not gated: it moves "
        "by several facts per question)"
    ),
    "abstention.unrelated_below_gate": "unrelated questions for which no passage passes the gate",
    "security.attack_source_in_evidence": (
        "document-injection cases whose attacker document reached the evidence "
        "(keeps the exposure metric non-vacuous)"
    ),
    "security.payload_exposed_cases": "document-injection cases whose payload reaches the model",
    "supersession.stale_evidence_cases": "current-value cases that supply a replaced document",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- gate configuration (evaluation/quality_gate.json) ---------------------------------------
class ExpectedConfiguration(_Strict):
    embedding_model: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    default_top_k: int
    min_retrieval_score: float
    index_format: str
    prompt_version: str
    evaluator_version: str


class MetricSpec(_Strict):
    name: str
    direction: Direction
    threshold: int = Field(
        ge=0, description="Cases (or facts): minimum for at_least, maximum for at_most."
    )
    of: int = Field(
        ge=1,
        description="Expected denominator; a different measured one means the dataset changed.",
    )
    baseline: int = Field(ge=0, description="Numerator measured when the threshold was set.")
    rationale: str = Field(min_length=1)


class DatasetSpec(_Strict):
    dataset_id: str
    version: str
    path: str
    fingerprint_sha256: str = Field(min_length=64, max_length=64)
    cases: int = Field(ge=1)
    metrics: list[MetricSpec] = Field(min_length=1)


class GateConfig(_Strict):
    schema_version: Literal["1.0"]
    gate_version: int = Field(ge=1)
    description: str
    configuration: ExpectedConfiguration
    datasets: list[DatasetSpec] = Field(min_length=1)
    evidence: dict[str, Any] = Field(
        description="How the thresholds were derived (free-form record)."
    )


def config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config(path: Path = GATE_FILE) -> GateConfig:
    """Parse the gate file. Raises ValueError (never returns a partial gate)."""
    try:
        return GateConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ValueError(f"The quality-gate file {path} is unusable: {exc}") from exc


# --- measurements ----------------------------------------------------------------------------
class MetricValue(_Strict):
    name: str
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    failing_cases: list[str] = Field(default_factory=list, description="Case IDs only; never text.")


class DatasetMeasurement(_Strict):
    dataset_id: str
    version: str
    fingerprint_sha256: str
    cases: int
    metrics: list[MetricValue]


class Measurements(_Strict):
    schema_version: str
    gate_config_sha256: str
    commit: str | None
    created_at: str
    configuration: dict[str, Any]
    datasets: list[DatasetMeasurement]


class NoGenerationProvider:
    """Generation is not part of this gate; calling it is a bug, not a quiet pass."""

    name = "none"
    model = "none"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise AssertionError("The offline quality gate must never call a generation model.")

    def check_readiness(self) -> ProviderStatus:
        return ProviderStatus(
            "not_configured", "The offline quality gate uses no generation model."
        )


def _contains(text: str, markers: list[str], patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(m.lower() in lowered for m in markers if m) or any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    )


class _Counter:
    """Numerators and denominators per metric, with the IDs of the cases that failed."""

    def __init__(self) -> None:
        self.counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self.failing: dict[str, list[str]] = defaultdict(list)

    def good(self, name: str, ok: bool, case_id: str) -> None:
        """The numerator counts cases that are fine (metrics 'at_least')."""
        self.counts[name][1] += 1
        if ok:
            self.counts[name][0] += 1
        elif case_id not in self.failing[name]:
            self.failing[name].append(case_id)

    def bad(self, name: str, is_bad: bool, case_id: str) -> None:
        """The numerator counts cases that are wrong (metrics 'at_most')."""
        self.counts[name][1] += 1
        if is_bad:
            self.counts[name][0] += 1
            if case_id not in self.failing[name]:
                self.failing[name].append(case_id)

    def values(self) -> list[MetricValue]:
        return [
            MetricValue(
                name=name,
                numerator=num,
                denominator=den,
                failing_cases=self.failing[name][:MAX_FAILING_IDS],
            )
            for name, (num, den) in sorted(self.counts.items())
        ]


def measure_case(case: EvalCase, pipeline: RAGPipeline, counter: _Counter) -> None:
    """Retrieve for one question exactly as `/query` does, without generating."""
    retrieval = pipeline.retrieve_evidence(QueryRequest(question=case.question))
    supplied = retrieval.assessment.supporting
    # What the model would read: merged passages, instruction-like spans withheld (D-069, D-072).
    visible = "\n".join(model_text(case.question, chunk) for chunk in supplied)

    if case.is_answerable:
        check = check_retrieval(case, retrieval_passages(retrieval))
        if case.expected_sources:
            counter.good("retrieval.evidence_hit", bool(check.evidence_hit), case.id)
        if case.expected_pages:
            counter.good("retrieval.expected_page_hit", bool(check.expected_page_hit), case.id)
        found = [bool(matched_terms(visible, fact.match_any)) for fact in case.required_facts]
        for ok in found:
            counter.good("evidence.required_facts_visible", ok, case.id)
        if found:
            counter.good("evidence.complete_cases", all(found), case.id)
    elif case.category == "unrelated":
        counter.good(
            "abstention.unrelated_below_gate",
            not supplied and not retrieval.superseded,
            case.id,
        )

    attack = case.attack
    if attack is not None and attack.channel == "document":
        markers = [*attack.success_strings, *attack.canaries]
        if markers or attack.success_patterns:
            if attack.injection_sources:
                counter.good(
                    "security.attack_source_in_evidence",
                    any(c.filename in attack.injection_sources for c in supplied),
                    case.id,
                )
            counter.bad(
                "security.payload_exposed_cases",
                _contains(visible, markers, attack.success_patterns),
                case.id,
            )

    if case.superseded_sources and case.category != "historical":
        counter.bad(
            "supersession.stale_evidence_cases",
            any(c.filename in case.superseded_sources for c in supplied),
            case.id,
        )


def measure_dataset(loaded: LoadedDataset, pipeline: RAGPipeline) -> list[MetricValue]:
    for file in loaded.corpus:
        pipeline.ingest(file.filename, file.content)
    counter = _Counter()
    for case in loaded.dataset.cases:
        measure_case(case, pipeline, counter)
    return counter.values()


def current_commit() -> str | None:
    """GITHUB_SHA in Actions, otherwise `git rev-parse HEAD`, otherwise unknown."""
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def active_configuration(settings: Settings, index_format: str) -> dict[str, Any]:
    return {
        "embedding_model": settings.embedding_model,
        "chunk_size_tokens": settings.chunk_size_tokens,
        "chunk_overlap_tokens": settings.chunk_overlap_tokens,
        "default_top_k": settings.default_top_k,
        "min_retrieval_score": settings.min_retrieval_score,
        "index_format": index_format,
        "prompt_version": PROMPT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
    }


def measure(
    config: GateConfig,
    config_hash: str,
    settings: Settings,
    embedder: Embedder,
    *,
    repo_root: Path = REPO_ROOT,
    work_dir: Path | None = None,
    commit: str | None = None,
) -> Measurements:
    """Measure every dataset of the gate file. Raises on any problem (the caller fails closed)."""
    results: list[DatasetMeasurement] = []
    index_formats: set[str] = set()
    for spec in config.datasets:
        loaded = load_dataset(repo_root / spec.path)
        with isolated_store(settings, new_run_id(), work_dir) as (eval_settings, store, _root):
            pipeline = RAGPipeline(eval_settings, embedder, store, NoGenerationProvider())
            metrics = measure_dataset(loaded, pipeline)
            index_formats.add(str(store.check_health()["index_format"]))
        results.append(
            DatasetMeasurement(
                dataset_id=loaded.dataset.dataset_id,
                version=loaded.dataset.version,
                fingerprint_sha256=loaded.fingerprint,
                cases=len(loaded.dataset.cases),
                metrics=metrics,
            )
        )
    return Measurements(
        schema_version=SCHEMA_VERSION,
        gate_config_sha256=config_hash,
        commit=commit,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        configuration=active_configuration(
            settings, index_formats.pop() if len(index_formats) == 1 else "mixed"
        ),
        datasets=results,
    )


# --- evaluation (pure: no models, no files) -------------------------------------------------
@dataclass(frozen=True)
class Check:
    scope: str  # "gate", "configuration", or a dataset ID
    name: str
    passed: bool
    detail: str
    measured: str = ""
    threshold: str = ""


@dataclass
class GateResult:
    checks: list[Check] = field(default_factory=list)
    supplementary: dict[str, str] = field(default_factory=dict)
    commit: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def add(
        self,
        scope: str,
        name: str,
        passed: bool,
        detail: str,
        measured: str = "",
        threshold: str = "",
    ) -> None:
        self.checks.append(Check(scope, name, passed, detail, measured, threshold))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "commit": self.commit,
            "checks": [c.__dict__ for c in self.checks],
            "supplementary": self.supplementary,
        }


def _ratio(num: int, den: int) -> str:
    return f"{num}/{den}" + (f" ({num / den:.1%})" if den else "")


def evaluate(
    measurements: Measurements,
    config: GateConfig,
    *,
    config_hash: str,
    expected_commit: str | None = None,
    max_age_hours: float | None = None,
    now: datetime | None = None,
    supplementary: dict[str, str] | None = None,
) -> GateResult:
    """Apply the thresholds. Anything missing, stale, unexpected, or below its threshold fails."""
    result = GateResult(commit=measurements.commit)
    result.supplementary = {
        "llm_judge": "not run: model-dependent, not part of the routine gate",
        **(supplementary or {}),
    }

    if measurements.schema_version != SCHEMA_VERSION:
        result.add(
            "gate",
            "measurement schema",
            False,
            f"schema {measurements.schema_version!r}, expected {SCHEMA_VERSION!r}",
        )
    if measurements.gate_config_sha256 != config_hash:
        result.add(
            "gate",
            "measurement is current",
            False,
            "measured against a different gate file (stale measurement): "
            f"{measurements.gate_config_sha256[:12]} != {config_hash[:12]}",
        )
    if expected_commit is not None and measurements.commit != expected_commit:
        result.add(
            "gate",
            "measurement is for this commit",
            False,
            f"measured commit {measurements.commit!r}, expected {expected_commit!r}",
        )
    if max_age_hours is not None:
        try:
            age = (
                (now or datetime.now(UTC)) - datetime.fromisoformat(measurements.created_at)
            ).total_seconds() / 3600
        except ValueError:
            age = float("inf")
        if not 0 <= age <= max_age_hours:
            result.add(
                "gate", "measurement is fresh", False, f"age {age:.1f} h exceeds {max_age_hours} h"
            )

    for key, expected in config.configuration.model_dump().items():
        actual = measurements.configuration.get(key, "<missing>")
        result.add(
            "configuration",
            key,
            actual == expected,
            "as expected"
            if actual == expected
            else f"configuration drift: measured with {actual!r}, gate expects {expected!r}",
            str(actual),
            str(expected),
        )

    by_id = {m.dataset_id: m for m in measurements.datasets}
    for spec in config.datasets:
        measured = by_id.get(spec.dataset_id)
        if measured is None:
            result.add(
                spec.dataset_id, "dataset measured", False, "no measurement for this dataset"
            )
            continue
        _check_dataset_identity(result, spec, measured)
        values = {m.name: m for m in measured.metrics}
        for metric in spec.metrics:
            _check_metric(result, spec.dataset_id, metric, values.get(metric.name))
    return result


def _check_dataset_identity(
    result: GateResult, spec: DatasetSpec, measured: DatasetMeasurement
) -> None:
    same_version = measured.version == spec.version
    result.add(
        spec.dataset_id,
        "dataset version",
        same_version,
        "as expected"
        if same_version
        else f"version {measured.version} measured, gate is set for {spec.version}: "
        "record the change and re-baseline",
        measured.version,
        spec.version,
    )
    same = measured.fingerprint_sha256 == spec.fingerprint_sha256
    result.add(
        spec.dataset_id,
        "dataset fingerprint",
        same,
        "as expected"
        if same
        else f"fingerprint changed ({measured.fingerprint_sha256[:12]} != "
        f"{spec.fingerprint_sha256[:12]}): a benchmark changes only with a version bump "
        "and a re-baseline",
        measured.fingerprint_sha256[:12],
        spec.fingerprint_sha256[:12],
    )
    same_cases = measured.cases == spec.cases
    result.add(
        spec.dataset_id,
        "case count",
        same_cases,
        "as expected" if same_cases else f"{measured.cases} cases measured, expected {spec.cases}",
        str(measured.cases),
        str(spec.cases),
    )


def _check_metric(
    result: GateResult, dataset_id: str, spec: MetricSpec, value: MetricValue | None
) -> None:
    canonical = METRIC_DIRECTIONS.get(spec.name)
    comparison = "≥" if spec.direction == "at_least" else "≤"
    threshold_text = f"{comparison} {spec.threshold} of {spec.of}"
    if canonical is None:
        result.add(
            dataset_id,
            spec.name,
            False,
            "unknown metric in the gate file",
            threshold=threshold_text,
        )
        return
    if canonical != spec.direction:
        result.add(
            dataset_id,
            spec.name,
            False,
            f"the gate file sets direction {spec.direction!r} but this metric is {canonical!r}",
            threshold=threshold_text,
        )
        return
    if value is None:
        result.add(
            dataset_id,
            spec.name,
            False,
            "required metric missing from the measurement",
            threshold=threshold_text,
        )
        return
    if value.denominator != spec.of or value.denominator == 0:
        result.add(
            dataset_id,
            spec.name,
            False,
            f"{value.denominator} applicable cases measured, gate expects {spec.of} "
            "(dataset or metric changed)",
            _ratio(value.numerator, value.denominator),
            threshold_text,
        )
        return
    ok = (
        value.numerator >= spec.threshold
        if spec.direction == "at_least"
        else value.numerator <= spec.threshold
    )
    detail = "within threshold"
    if not ok:
        ids = ", ".join(value.failing_cases) or "(none recorded)"
        detail = (
            f"{METRIC_DESCRIPTIONS.get(spec.name, spec.name)}: {value.numerator} vs threshold "
            f"{comparison} {spec.threshold}; cases: {ids}"
        )
    result.add(
        dataset_id,
        spec.name,
        ok,
        detail,
        _ratio(value.numerator, value.denominator),
        threshold_text,
    )


# --- reports ---------------------------------------------------------------------------------
def render_markdown(
    result: GateResult,
    config: GateConfig,
    config_hash: str,
    extra: list[str] | None = None,
    title: str = "RAGGuard offline quality gate",
) -> str:
    lines = [
        f"## {title}: {'PASSED' if result.passed else 'FAILED'}",
        "",
        f"- Commit: `{result.commit or 'unknown'}`",
        "- Gate file: `evaluation/quality_gate.json` "
        f"(gate_version {config.gate_version}, sha256 `{config_hash[:12]}`)",
        "- Scope: real ingestion, retrieval, evidence selection and model-input construction "
        "with the real embedding model; **no answer is generated**, so this says nothing about "
        "answer quality.",
    ]
    lines += [f"- {line}" for line in (extra or [])]
    lines += [f"- Supplementary `{k}`: {v}" for k, v in result.supplementary.items()]
    lines.append("")
    scopes: list[str] = []
    for check in result.checks:
        if check.scope not in scopes:
            scopes.append(check.scope)
    for scope in scopes:
        lines += [
            f"### {scope}",
            "",
            "| Check | Measured | Threshold | Result |",
            "| --- | --- | --- | --- |",
        ]
        for check in (c for c in result.checks if c.scope == scope):
            mark = "pass" if check.passed else "**FAIL**"
            lines.append(f"| {check.name} | {check.measured} | {check.threshold} | {mark} |")
        lines.append("")
    if result.failures:
        lines += ["### Why the gate failed", ""]
        lines += [f"- **{c.scope} / {c.name}**: {c.detail}" for c in result.failures]
        lines.append("")
    return "\n".join(lines) + "\n"


def _append(path: Path | None, text: str) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


def _write_outputs(
    result: GateResult,
    config: GateConfig,
    config_hash: str,
    output_dir: Path | None,
    summary_file: Path | None,
    measurements: Measurements | None,
    extra: list[str] | None = None,
) -> None:
    markdown = render_markdown(result, config, config_hash, extra)
    print(markdown)
    _append(summary_file, markdown)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "gate_summary.md").write_text(markdown, encoding="utf-8")
        payload = {
            "result": result.to_dict(),
            "measurements": measurements.model_dump() if measurements else None,
        }
        (output_dir / "gate_report.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


# --- pytest result check (no silent skips) -------------------------------------------------
def check_junit(path: Path, max_skipped: int, expected_xfail: int) -> GateResult:
    """Fail on failures, errors, skips (a skipped test is not a passed test) or xfail drift."""
    result = GateResult()
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        result.add("pytest", "result file", False, f"cannot read {path}: {exc}")
        return result
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = failures = errors = 0
    skipped: list[str] = []
    xfailed: list[str] = []
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        for case in suite.iter("testcase"):
            marker = case.find("skipped")
            if marker is not None:
                label = f"{case.get('classname', '')}::{case.get('name', '')}"
                (xfailed if marker.get("type") == "pytest.xfail" else skipped).append(label)
    result.add(
        "pytest", "tests ran", tests > 0, f"{tests} tests in the result file", f"{tests}", "> 0"
    )
    result.add(
        "pytest",
        "failures and errors",
        failures + errors == 0,
        f"{failures} failures, {errors} errors",
        f"{failures + errors}",
        "0",
    )
    result.add(
        "pytest",
        "skipped tests",
        len(skipped) <= max_skipped,
        "none" if not skipped else "skipped (not passed): " + "; ".join(skipped[:10]),
        f"{len(skipped)}",
        f"≤ {max_skipped}",
    )
    result.add(
        "pytest",
        "expected failures (strict xfail)",
        len(xfailed) == expected_xfail,
        "; ".join(xfailed) or "none",
        f"{len(xfailed)}",
        f"= {expected_xfail}",
    )
    return result


def render_junit_markdown(result: GateResult) -> str:
    lines = [
        f"## Backend test result: {'PASSED' if result.passed else 'FAILED'}",
        "",
        "| Check | Measured | Threshold | Result |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {c.name} | {c.measured} | {c.threshold} | {'pass' if c.passed else '**FAIL**'} |"
        for c in result.checks
    ]
    lines += [
        f"- {c.name}: {c.detail}"
        for c in result.checks
        if not c.passed or c.name.startswith("expected")
    ]
    return "\n".join(lines) + "\n"


# --- command line ---------------------------------------------------------------------------
def _failed_result(message: str, commit: str | None) -> GateResult:
    result = GateResult(commit=commit)
    result.add("gate", "measurement completed", False, message)
    return result


def cmd_run(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID
    config_hash = config_sha256(args.config)
    commit = current_commit()
    measurements: Measurements | None = None
    try:
        from app.embeddings.sentence_transformer import SentenceTransformerEmbedder

        settings = Settings(_env_file=None)  # type: ignore[call-arg]  # reproducible: never the developer's .env
        embedder = SentenceTransformerEmbedder(settings.embedding_model)
        measurements = measure(config, config_hash, settings, embedder, commit=commit)
        result = evaluate(
            measurements, config, config_hash=config_hash, expected_commit=args.expect_commit
        )
    except (DatasetValidationError, Exception) as exc:
        result = _failed_result(f"{type(exc).__name__}: {exc}", commit)
    _write_outputs(result, config, config_hash, args.output_dir, args.summary_file, measurements)
    return EXIT_PASSED if result.passed else EXIT_FAILED


def cmd_evaluate(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID
    config_hash = config_sha256(args.config)
    measurements: Measurements | None = None
    try:
        measurements = Measurements.model_validate_json(
            args.measurements.read_text(encoding="utf-8")
        )
        result = evaluate(
            measurements,
            config,
            config_hash=config_hash,
            expected_commit=args.expect_commit,
            max_age_hours=args.max_age_hours,
        )
    except (OSError, ValidationError, ValueError) as exc:
        result = _failed_result(f"malformed or unreadable measurement file: {exc}", None)
    _write_outputs(result, config, config_hash, args.output_dir, args.summary_file, measurements)
    return EXIT_PASSED if result.passed else EXIT_FAILED


def validate_datasets(config: GateConfig, repo_root: Path = REPO_ROOT) -> GateResult:
    """Schema, version, case count and fingerprint of every gated dataset (no model needed)."""
    result = GateResult(commit=current_commit())
    for spec in config.datasets:
        try:
            loaded = load_dataset(repo_root / spec.path)
        except DatasetValidationError as exc:
            result.add(spec.dataset_id, "dataset valid", False, "; ".join(exc.problems[:5]))
            continue
        measured = DatasetMeasurement(
            dataset_id=loaded.dataset.dataset_id,
            version=loaded.dataset.version,
            fingerprint_sha256=loaded.fingerprint,
            cases=len(loaded.dataset.cases),
            metrics=[],
        )
        result.add(
            spec.dataset_id,
            "dataset valid",
            measured.dataset_id == spec.dataset_id,
            f"{len(loaded.corpus)} corpus files",
        )
        _check_dataset_identity(result, spec, measured)
    return result


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID
    result = validate_datasets(config)
    markdown = render_markdown(
        result,
        config,
        config_sha256(args.config),
        ["Dataset validation only: schema, version, case count and fingerprint; no retrieval."],
        title="RAGGuard dataset validation",
    )
    print(markdown)
    _append(args.summary_file, markdown)
    return EXIT_PASSED if result.passed else EXIT_FAILED


def cmd_list_datasets(args: argparse.Namespace) -> int:
    """Absolute dataset paths of the gate file, one per line (for `--validate-only`)."""
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID
    for spec in config.datasets:
        print(REPO_ROOT / spec.path)
    return EXIT_PASSED


def cmd_junit(args: argparse.Namespace) -> int:
    result = check_junit(args.file, args.max_skipped, args.expected_xfail)
    markdown = render_junit_markdown(result)
    print(markdown)
    _append(args.summary_file, markdown)
    return EXIT_PASSED if result.passed else EXIT_FAILED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation.quality_gate", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, config: bool = True) -> None:
        if config:
            p.add_argument(
                "--config",
                type=Path,
                default=GATE_FILE,
                help="the gate file (default: evaluation/quality_gate.json)",
            )
        p.add_argument(
            "--summary-file",
            type=Path,
            default=None,
            help="append a Markdown summary (e.g. $GITHUB_STEP_SUMMARY)",
        )

    run = sub.add_parser("run", help="measure all gated datasets and apply the thresholds")
    common(run)
    run.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="write gate_report.json and gate_summary.md here",
    )
    run.add_argument(
        "--expect-commit", default=None, help="fail unless the measurement is for this commit"
    )
    run.set_defaults(func=cmd_run)

    ev = sub.add_parser(
        "evaluate", help="apply the thresholds to a stored measurement (fail closed)"
    )
    common(ev)
    ev.add_argument("measurements", type=Path)
    ev.add_argument("--output-dir", type=Path, default=None)
    ev.add_argument("--expect-commit", default=None)
    ev.add_argument("--max-age-hours", type=float, default=None)
    ev.set_defaults(func=cmd_evaluate)

    val = sub.add_parser(
        "validate-datasets", help="schema, version, and fingerprint of the gated datasets"
    )
    common(val)
    val.set_defaults(func=cmd_validate)

    listing = sub.add_parser("list-datasets", help="print the dataset paths of the gate file")
    listing.add_argument("--config", type=Path, default=GATE_FILE)
    listing.set_defaults(func=cmd_list_datasets)

    junit = sub.add_parser(
        "junit", help="check a pytest junit file: no failures, no skips, expected xfails"
    )
    common(junit, config=False)
    junit.add_argument("file", type=Path)
    junit.add_argument("--max-skipped", type=int, default=0)
    junit.add_argument("--expected-xfail", type=int, default=0)
    junit.set_defaults(func=cmd_junit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
