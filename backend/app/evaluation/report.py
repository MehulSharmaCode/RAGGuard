"""Write the JSON report and render the Markdown report from the same data.

The Markdown is a pure function of the JSON report: `render_markdown(load(json))`
reproduces the written Markdown exactly, which `write_reports` verifies.
"""

from __future__ import annotations

from pathlib import Path

from app.evaluation.schemas import (
    CaseResult,
    ClassificationScores,
    EvaluationReport,
    LatencyStats,
    Metric,
)

JSON_NAME = "report.json"
MARKDOWN_NAME = "report.md"


class ReportConsistencyError(Exception):
    pass


# --- formatting ------------------------------------------------------------------
def _num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return str(int(value)) if float(value).is_integer() else f"{value:.4f}".rstrip("0")


def fmt_metric(metric: Metric) -> str:
    if metric.value is None:
        return f"n/a (denominator {metric.denominator})"
    return f"{metric.value:.4f} ({_num(metric.numerator)}/{metric.denominator})"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _flag(value: bool | None) -> str:
    return "n/a" if value is None else ("yes" if value else "no")


def _cell(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(text.split()).replace("|", "\\|")


def _quote(text: str | None) -> list[str]:
    if not text:
        return ["> (none)"]
    return [f"> {line}" if line else ">" for line in text.strip().splitlines()]


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _latency_row(name: str, stats: LatencyStats) -> list[str]:
    return [
        name,
        str(stats.count),
        _ms(stats.mean_ms),
        _ms(stats.median_ms),
        _ms(stats.p95_ms),
        _ms(stats.min_ms),
        _ms(stats.max_ms),
    ]


def _classification_rows(scores: ClassificationScores) -> list[list[str]]:
    return [
        ["Precision", fmt_metric(scores.precision)],
        ["Recall", fmt_metric(scores.recall)],
        ["F1", fmt_metric(scores.f1)],
        ["Correct fallback rate (unanswerable)", fmt_metric(scores.correct_fallback_rate)],
        ["False-answer rate (unanswerable)", fmt_metric(scores.false_answer_rate)],
        ["False-fallback rate (answerable)", fmt_metric(scores.false_fallback_rate)],
    ]


# --- sections --------------------------------------------------------------------
def _header(report: EvaluationReport) -> list[str]:
    c = report.configuration
    d = report.dataset
    lines = [
        f"# RAGGuard evaluation report `{report.run_id}`",
        "",
        f"- **Run status:** {report.status} — {report.status_detail}",
        f"- **Started / finished (UTC):** {report.started_at} / {report.finished_at}",
        f"- **Dataset:** {d.dataset_id} v{d.version}, {d.cases_run} of {d.cases_in_dataset} "
        f"cases run" + (f" (limit {d.case_limit})" if d.case_limit else ""),
        f"- **Dataset fingerprint (sha256):** `{d.fingerprint_sha256}`",
        f"- **Report schema:** {report.schema_version}",
        *(
            [
                f"- **Re-scored from:** `{report.rescored_from}` (recorded answers and retrieval "
                "re-scored with the current evaluator; no new model calls)"
            ]
            if report.rescored_from
            else []
        ),
        "",
        "The run status describes whether the evaluation executed, not whether quality is "
        "acceptable. No quality thresholds are applied in this report.",
    ]
    if report.fatal_error:
        lines += ["", f"**Fatal error:** {report.fatal_error}"]
    lines += [
        "",
        "## Configuration",
        "",
        *_table(
            ["Setting", "Value"],
            [
                [
                    "Generation",
                    f"{c.generation_provider} `{c.generation_model}` (prompt "
                    f"{c.prompt_version}, temperature {c.generation_temperature})",
                ],
                ["Generation readiness at start", _cell(c.generation_readiness)],
                [
                    "Judge",
                    "disabled"
                    if not c.judge_enabled
                    else f"{c.judge_provider} `{c.judge_model}` (prompt {c.judge_prompt_version}, "
                    f"temperature {c.judge_temperature}, seed {c.judge_seed})",
                ],
                ["Judge readiness at start", _cell(c.judge_readiness) or "n/a"],
                ["Judge model = generation model", _flag(c.judge_same_model_as_generation)],
                ["Embedding model", f"`{c.embedding_model}`"],
                ["Chunking", f"{c.chunk_size_tokens} tokens, overlap {c.chunk_overlap_tokens}"],
                ["Top-k", str(c.top_k)],
                ["Evidence threshold (MIN_RETRIEVAL_SCORE)", str(c.min_retrieval_score)],
                ["Retrieval index", c.retrieval_index or "not recorded (single-vector chunks)"],
                ["Evaluator version", c.evaluator_version or "e1 (not recorded)"],
                ["Vector store", c.vector_store],
                ["Categories run", ", ".join(f"{k} {v}" for k, v in d.category_counts.items())],
            ],
        ),
    ]
    if c.judge_same_model_as_generation:
        lines += [
            "",
            "> The same model generates and judges the answers. Self-evaluation bias is likely; "
            "judge scores are supplementary and never replace the deterministic metrics.",
        ]
    return lines


def _aggregates(report: EvaluationReport) -> list[str]:
    a = report.aggregates
    if a is None:
        return ["", "## Metrics", "", "No case results: metrics were not computed."]
    r, ans, cit, f, lat, j = a.retrieval, a.answerability, a.citations, a.facts, a.latency, a.judge
    cor, sec = a.correctness, a.security
    cm = ans.confusion
    lines = [
        "",
        "## Summary",
        "",
        f"Cases: {a.cases_total} run, {a.cases_completed} completed, {a.cases_failed} failed "
        "in the pipeline. Values are shown as `value (numerator/denominator)`.",
        "",
        *_table(
            ["Metric", "Value"],
            [
                ["Case pass rate (deterministic, all cases)", fmt_metric(cor.case_pass_rate)],
                ["Correct answers (answerable cases)", fmt_metric(cor.answer_correct_rate)],
                ["Unsupported content in answers", fmt_metric(cor.unsupported_content_rate)],
                ["Prompt-injection attack success rate", fmt_metric(sec.attack_success_rate)],
                ["Canary leak rate", fmt_metric(sec.canary_leak_rate)],
                ["Benign-control success rate", fmt_metric(sec.benign_control_success_rate)],
                [
                    "Unnecessary refusal rate (benign controls)",
                    fmt_metric(sec.unnecessary_refusal_rate),
                ],
                [f"Expected-source hit rate@{r.k}", fmt_metric(r.hit_rate_at_k)],
                [
                    "Expected-source hit rate in evidence (above threshold)",
                    fmt_metric(r.evidence_hit_rate),
                ],
                ["Mean expected-source coverage", fmt_metric(r.mean_coverage)],
                ["Multi-source coverage", fmt_metric(r.multi_source_coverage)],
                ["Answerability precision", fmt_metric(ans.precision)],
                ["Answerability recall", fmt_metric(ans.recall)],
                ["Answerability F1", fmt_metric(ans.f1)],
                ["Correct fallback rate (unanswerable)", fmt_metric(ans.correct_fallback_rate)],
                ["False-answer rate (unanswerable)", fmt_metric(ans.false_answer_rate)],
                ["False-fallback rate (answerable)", fmt_metric(ans.false_fallback_rate)],
                ["Citation presence rate", fmt_metric(cit.citation_presence_rate)],
                ["Citation validity rate", fmt_metric(cit.citation_validity_rate)],
                ["Expected-source citation rate", fmt_metric(cit.expected_source_citation_rate)],
                ["Cited-source precision", fmt_metric(cit.cited_source_precision)],
                ["Cited-fact support rate (lexical)", fmt_metric(cit.cited_fact_support_rate)],
                ["Superseded-source citation rate", fmt_metric(cit.superseded_citation_rate)],
                ["Required-fact recall", fmt_metric(f.required_fact_recall)],
                ["Complete-answer rate", fmt_metric(f.complete_answer_rate)],
                [
                    "Query latency mean / median / p95 (ms)",
                    f"{_ms(lat.query.mean_ms)} / {_ms(lat.query.median_ms)} / "
                    f"{_ms(lat.query.p95_ms)} (n={lat.query.count})",
                ],
                ["Judge mean correctness (supplementary)", fmt_metric(j.mean_correctness)],
                ["Judge mean groundedness (supplementary)", fmt_metric(j.mean_groundedness)],
                ["Judge mean completeness (supplementary)", fmt_metric(j.mean_completeness)],
            ],
        ),
        "",
        "## Correctness (deterministic)",
        "",
        *_table(["Category", "Correct"], [[k, fmt_metric(v)] for k, v in cor.by_category.items()]),
        "",
        "Answer failures (answered, not correct): " + (", ".join(cor.answer_failures) or "none"),
        "",
        "False refusals (answerable, fell back): " + (", ".join(cor.false_refusals) or "none"),
        "",
        "Unsupported content found: " + (", ".join(cor.unsupported_content_cases) or "none"),
        "",
        "## Prompt-injection security",
        "",
        f"{sec.attack_cases} attack cases covering {sec.distinct_scenarios} distinct scenarios. "
        "Results apply to these synthetic cases only and are not proof of general resistance.",
        "",
        *_table(
            ["Measure", "Value"],
            [
                ["Attack success rate (cases)", fmt_metric(sec.attack_success_rate)],
                [
                    "Attack success rate (scenarios)",
                    fmt_metric(sec.attack_success_rate_by_scenario),
                ],
                ["Canary leak rate", fmt_metric(sec.canary_leak_rate)],
                [
                    "Attack payload reached the evidence",
                    fmt_metric(sec.injection_exposure_rate)
                    if sec.injection_exposure_rate
                    else "not recorded",
                ],
                ["Legitimate task completed under attack", fmt_metric(sec.task_completion_rate)],
                ["Benign-control success rate", fmt_metric(sec.benign_control_success_rate)],
                ["Unnecessary refusal rate", fmt_metric(sec.unnecessary_refusal_rate)],
            ],
        ),
        "",
        "Succeeded attacks: " + (", ".join(sec.succeeded_cases) or "none"),
        "",
        "Canary leaks: " + (", ".join(sec.leaked_cases) or "none"),
        "",
        "Payload never reached the model (blocked by retrieval, not by the model): "
        + (", ".join(sec.unexposed_attack_cases) or "none"),
        "",
        "Injected wording echoed (not counted as success): "
        + (", ".join(sec.echo_cases) or "none"),
        "",
        "Benign-control failures: " + (", ".join(sec.benign_failures) or "none"),
        "",
        "Attack errors (excluded): " + (", ".join(sec.errors) or "none"),
        "",
        *_table(["Vector", "Success rate"], [[k, fmt_metric(v)] for k, v in sec.by_vector.items()]),
        "",
        *_table(
            ["Channel", "Success rate"], [[k, fmt_metric(v)] for k, v in sec.by_channel.items()]
        ),
        "",
        "## Answerability and fallback",
        "",
        "Positive class = answerable. Predicted positive = the pipeline answered; predicted "
        "negative = the pipeline's safe fallback.",
        "",
        *_table(
            ["", "Pipeline answered", "Pipeline fell back"],
            [
                ["Answerable", f"TP {cm.tp}", f"FN {cm.fn}"],
                ["Unanswerable", f"FP {cm.fp}", f"TN {cm.tn}"],
            ],
        ),
        "",
        *_table(["Rate", "Value"], _classification_rows(ans)),
        "",
        "Fallback reasons: "
        + (", ".join(f"{k} {v}" for k, v in ans.fallback_reasons.items()) or "none"),
        "",
        "Unclassified (pipeline error): " + (", ".join(ans.unclassified_errors) or "none"),
        "",
        *_table(
            ["Category", "Answered", "Fallback", "Error"],
            [
                [k, str(v.get("answered", 0)), str(v.get("fallback", 0)), str(v.get("error", 0))]
                for k, v in ans.outcomes_by_category.items()
            ],
        ),
        "",
        "## Retrieval",
        "",
        *_table(
            ["Category", f"Hit rate@{r.k}"],
            [[k, fmt_metric(v)] for k, v in r.by_category.items()],
        ),
        "",
        "Answerable cases without any expected source in the top-k: "
        + (", ".join(r.misses) or "none"),
        "",
        "Retrieval errors: " + (", ".join(r.retrieval_errors) or "none"),
        "",
        "## Citations",
        "",
        f"Answered cases: {cit.answered_cases}. Invalid citation identifiers: "
        f"{cit.invalid_citation_count}. Unexpected cited sources: {cit.unexpected_citation_count}. "
        "Answers without any citation: "
        + (", ".join(cit.answers_without_citations) or "none")
        + ".",
        "",
        "A valid citation identifier does not by itself prove that the passage supports the claim. "
        f"Claim support (lexical): {fmt_metric(cit.cited_fact_support_rate)} of required facts in "
        f"answers are cited to a passage containing them; {cit.uncited_fact_count} stated without "
        f"a citation; {cit.unsupported_citation_fact_count} cited to passages that do not contain "
        "them. Superseded sources cited for current facts: "
        + (", ".join(cit.superseded_citation_cases) or "none")
        + ".",
        "",
        "## Required facts (lexical)",
        "",
        "Answered answerable cases missing a required fact: "
        + (", ".join(f.incomplete_cases) or "none"),
        "",
        "## Latency",
        "",
        *_table(
            ["Scope", "n", "Mean ms", "Median ms", "p95 ms", "Min ms", "Max ms"],
            [
                _latency_row("All queries", lat.query),
                _latency_row("With generation", lat.query_with_generation),
                _latency_row(
                    "Without generation (retrieval fallback)", lat.query_without_generation
                ),
                *[_latency_row(k, v) for k, v in lat.by_category.items()],
            ],
        ),
        "",
        f"Corpus ingestion: {_ms(lat.ingestion_ms)} ms. "
        f"Judging total: {_ms(lat.judge_total_ms)} ms. "
        f"Whole run: {_ms(lat.run_total_ms)} ms. p95 uses the nearest-rank method and equals the "
        "maximum when n < 20; treat it as unstable for this dataset size.",
        "",
        "## LLM judge (supplementary)",
        "",
    ]
    if not j.enabled:
        lines.append("Judging was skipped for this run (`--skip-judge`).")
    else:
        lines += _table(
            ["Judge measure", "Value"],
            [
                ["Eligible (answered) cases", str(j.eligible_cases)],
                ["Scored", str(j.scored)],
                ["Judge errors", ", ".join(j.errors) or "none"],
                ["Not applicable (fallback or pipeline error)", str(j.not_applicable)],
                ["Mean correctness", fmt_metric(j.mean_correctness)],
                ["Mean groundedness", fmt_metric(j.mean_groundedness)],
                ["Mean completeness", fmt_metric(j.mean_completeness)],
                ["Unsupported-claim flags", fmt_metric(j.unsupported_claim_flags)],
                [
                    "Unanswerable handled correctly (answered unanswerable cases)",
                    fmt_metric(j.unanswerable_handled_correctly),
                ],
                ["Citations support claims", fmt_metric(j.citations_support_claims)],
            ],
        )
    return lines


def _threshold(report: EvaluationReport) -> list[str]:
    t = report.threshold_analysis
    if t is None:
        return ["", "## Threshold analysis", "", "No retrieval scores were recorded."]
    rows = []
    for p in t.points:
        cm = p.confusion
        e2e = p.estimated_end_to_end
        rows.append(
            [
                f"{p.threshold:.2f}" + (" (run)" if p.threshold == t.run_threshold else ""),
                f"{cm.tp}/{cm.fp}/{cm.tn}/{cm.fn}",
                fmt_metric(p.precision),
                fmt_metric(p.recall),
                fmt_metric(p.f1),
                fmt_metric(p.false_answer_rate),
                fmt_metric(p.false_fallback_rate),
                "n/a" if e2e is None else fmt_metric(e2e.f1),
            ]
        )
    categories = list(t.points[0].pass_rate_by_category) if t.points else []
    lines = [
        "",
        "## Threshold analysis",
        "",
        f"Run threshold: {t.run_threshold}. Calculated offline from the recorded maximum "
        "retrieval score of each case; no answers were regenerated.",
        "",
        *_table(
            [
                "Threshold",
                "TP/FP/TN/FN",
                "Precision",
                "Recall",
                "F1",
                "False-answer rate",
                "False-fallback rate",
                "Est. end-to-end F1",
            ],
            rows,
        ),
        "",
        "Share of cases whose maximum score reaches each threshold, by category:",
        "",
        *_table(
            ["Threshold", *categories],
            [
                [
                    f"{p.threshold:.2f}",
                    *[fmt_metric(p.pass_rate_by_category[c]) for c in categories],
                ]
                for p in t.points
            ],
        ),
        "",
        "Maximum-score distribution:",
        "",
        *_table(
            ["Group", "n", "Min", "Median", "Max"],
            [
                [k, str(v.count), _num(v.min), _num(v.median), _num(v.max)]
                for k, v in t.score_distribution.items()
            ],
        ),
        "",
        f"Lowest answerable max score: {_num(t.lowest_answerable_max_score)}. Highest unanswerable "
        f"max score: {_num(t.highest_unanswerable_max_score)}. Cases in the overlapping range: "
        + (", ".join(t.overlapping_cases) or "none")
        + ".",
        "",
        "Best retrieval-gate F1 at threshold(s): "
        + (", ".join(f"{x:.2f}" for x in t.best_retrieval_f1_thresholds) or "n/a")
        + " (informational; the production threshold is not changed automatically).",
        "",
        "High-similarity failures (max score at or above the run threshold, wrong outcome):",
        "",
    ]
    if t.high_similarity_failures:
        lines += _table(
            ["Case", "Category", "Max score", "Outcome", "Problem"],
            [
                [f.case_id, f.category, _num(f.max_score), f.outcome, _cell(f.problem)]
                for f in t.high_similarity_failures
            ],
        )
    else:
        lines.append("None.")
    if t.excluded_cases:
        lines += ["", "Excluded (no retrieval score): " + ", ".join(t.excluded_cases)]
    lines += ["", "Notes:", "", *[f"- {n}" for n in t.notes]]
    return lines


def _diagnostics(report: EvaluationReport) -> list[str]:
    lines = ["", "## Diagnostics: outdated, superseded, and conflicting sources", ""]
    cases = [c for c in report.cases if c.diagnostic is not None]
    if not cases:
        lines.append("No source-handling diagnostic cases in this run.")
    else:
        lines += [
            "Findings from lexical checks plus the answer text; they are not a claim that "
            "conflicting or outdated sources are handled in general.",
            "",
        ]
    for c in cases:
        d = c.diagnostic
        assert d is not None
        lines += [
            f"### {c.case_id} — {d.kind}",
            "",
            f"- Outcome: {c.outcome}" + (f" ({c.fallback_reason})" if c.fallback_reason else ""),
            f"- Finding: {d.finding}",
            f"- Outdated value mentioned: {_flag(d.stale_value_mentioned)}",
            f"- Required values present: {_flag(d.current_value_mentioned)}",
            f"- Acknowledgement wording found: {_flag(d.acknowledges_limitation)}",
            f"- Cited documents: {', '.join(d.cited_filenames) or 'none'}",
            "- Superseded sources cited: " + (", ".join(c.superseded_citations) or "none"),
            "- Unsupported content: " + (", ".join(c.unsupported_content) or "none"),
            "- Matched terms: "
            + ("; ".join(f"{k}: {', '.join(v)}" for k, v in d.matched_terms.items()) or "none"),
        ]
        if c.judge.verdict is not None:
            lines.append(f"- Judge rationale (supplementary): {_cell(c.judge.verdict.rationale)}")
        lines += ["", *_quote(c.answer), ""]

    attacks = [c for c in report.cases if c.attack is not None]
    lines += ["## Prompt-injection cases", ""]
    if not attacks:
        return [*lines, "No prompt-injection cases in this run."]
    lines += _table(
        ["Case", "Scenario", "Vector", "Channel", "Outcome", "Attack", "Task done", "Reasons"],
        [
            [
                c.case_id,
                c.attack.scenario_id,
                c.attack.vector,
                c.attack.channel,
                c.outcome + (f" ({c.fallback_reason})" if c.fallback_reason else ""),
                c.attack.status,
                _flag(c.attack.task_completed),
                _cell("; ".join(c.attack.reasons)) or "-",
            ]
            for c in attacks
            if c.attack is not None
        ],
    )
    lines.append("")
    for c in attacks:
        if c.attack is None or c.attack.status != "succeeded":
            continue
        lines += [
            f"### {c.case_id} — attack succeeded ({c.attack.vector})",
            "",
            *_quote(c.answer),
            "",
        ]
    return lines


def _case_row(c: CaseResult) -> list[str]:
    v = c.judge.verdict
    judge = (
        f"C{_num(v.correctness)} G{v.groundedness} Cm{_num(v.completeness)}"
        if v is not None
        else c.judge.status
    )
    return [
        c.case_id,
        c.category,
        c.answerability,
        c.outcome + (f" ({c.fallback_reason})" if c.fallback_reason else ""),
        c.classification or "n/a",
        _num(c.max_score),
        _flag(c.retrieval.hit_at_k if c.retrieval else None),
        f"{c.facts.facts_found}/{c.facts.facts_total}" if c.facts else "n/a",
        (f"{len(c.citations.valid_ids)}/{len(c.citations.cited_ids)}" if c.citations else "n/a"),
        judge,
        _ms(c.latency_ms),
    ]


def _case_detail(c: CaseResult) -> list[str]:
    lines = [
        f"### {c.case_id}",
        "",
        f"- Question: {_cell(c.question)}",
        f"- Category / label: {c.category} / {c.answerability}",
        f"- Expected sources: {', '.join(c.expected_sources) or 'none'}",
        f"- Outcome: {c.outcome}"
        + (f" ({c.fallback_reason})" if c.fallback_reason else "")
        + f"; LLM called: {_flag(c.llm_called)}; latency {_ms(c.latency_ms)} ms",
    ]
    if c.error:
        lines.append(f"- Error ({c.error.stage}): {c.error.code} — {_cell(c.error.message)}")
    if c.facts and c.facts.missing:
        lines.append(f"- Missing required facts: {', '.join(c.facts.missing)}")
    if c.citations:
        lines.append(
            f"- Citations: {', '.join(c.citations.cited_ids) or 'none'}"
            + (
                f"; invalid: {', '.join(c.citations.invalid_ids)}"
                if c.citations.invalid_ids
                else ""
            )
            + (
                f"; unexpected sources: {', '.join(c.citations.unexpected_filenames)}"
                if c.citations.unexpected_filenames
                else ""
            )
        )
    lines += [
        "",
        "Reference answer:",
        "",
        *_quote(c.reference_answer),
        "",
        "Generated answer:",
        "",
        *_quote(c.answer),
        "",
    ]
    if c.retrieved:
        lines += _table(
            ["Rank", "Source", "Document", "Chunk", "Score", "Evidence"],
            [
                [
                    str(p.rank),
                    p.source_id or "-",
                    p.filename,
                    str(p.chunk_index),
                    _num(p.score),
                    _flag(p.above_threshold),
                ]
                for p in c.retrieved
            ],
        )
        lines.append("")
    if c.judge.verdict is not None:
        v = c.judge.verdict
        lines.append(
            f"Judge (supplementary): correctness {_num(v.correctness)}, groundedness "
            f"{v.groundedness}, completeness {_num(v.completeness)}, unsupported claims "
            f"{_flag(v.unsupported_claims)}, unanswerable handled correctly "
            f"{_flag(v.unanswerable_handled_correctly)}. {_cell(v.rationale)}"
        )
    else:
        lines.append(
            f"Judge: {c.judge.status}"
            + (f" — {_cell(c.judge.reason)}" if c.judge.reason else "")
            + (f" — {_cell(c.judge.error)}" if c.judge.error else "")
        )
    lines.append("")
    return lines


def _cases(report: EvaluationReport) -> list[str]:
    lines = [
        "",
        "## Per-case results",
        "",
        "Facts = required facts found (lexical); Citations = valid/total identifiers; Judge = "
        "correctness / groundedness / completeness (supplementary).",
        "",
        *_table(
            [
                "Case",
                "Category",
                "Label",
                "Outcome",
                "Class",
                "Max score",
                "Hit@k",
                "Facts",
                "Citations",
                "Judge",
                "Latency ms",
            ],
            [_case_row(c) for c in report.cases],
        ),
        "",
    ]
    for c in report.cases:
        lines += _case_detail(c)
    return lines


def _footer(report: EvaluationReport) -> list[str]:
    lines = ["## Metric definitions", ""]
    for d in report.metric_definitions:
        lines.append(f"- **{d.name}** — {d.definition} Denominator: {d.denominator}")
    lines += ["", "## Limitations and interpretation", ""]
    lines += [f"- {item}" for item in report.limitations]
    return lines


def render_markdown(report: EvaluationReport) -> str:
    lines = [
        *_header(report),
        *_aggregates(report),
        *_threshold(report),
        *_diagnostics(report),
        *_cases(report),
        *_footer(report),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]:
    """Write `<output_dir>/<run_id>/report.{json,md}` and check that they agree."""
    run_dir = output_dir / report.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    json_path = run_dir / JSON_NAME
    md_path = run_dir / MARKDOWN_NAME
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    verify_reports(json_path, md_path)
    return json_path, md_path


def verify_reports(json_path: Path, md_path: Path) -> EvaluationReport:
    """Re-validate the JSON file against the schema and check the Markdown matches it."""
    loaded = EvaluationReport.model_validate_json(json_path.read_text(encoding="utf-8"))
    if render_markdown(loaded) != md_path.read_text(encoding="utf-8"):
        raise ReportConsistencyError(f"{md_path} does not match {json_path}")
    return loaded
