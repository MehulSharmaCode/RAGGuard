"""LLM judge: prompt content, schema validation, retry, and error recording (mocked)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import GenerationUnavailableError
from app.evaluation.dataset import EvalCase
from app.evaluation.judge import (
    JUDGE_SEED,
    JUDGE_SYSTEM_PROMPT,
    VERDICT_JSON_SCHEMA,
    LLMJudge,
    build_judge_prompt,
    build_judge_provider,
    parse_verdict,
)
from app.evaluation.schemas import RetrievedPassage
from app.generation.ollama import OllamaProvider
from tests.conftest import FakeProvider

ANSWERABLE = EvalCase.model_validate(
    {
        "id": "ANS-001",
        "question": "How often is the sensor recalibrated?",
        "answerability": "answerable",
        "category": "factual",
        "reference_answer": "Every 60 days.",
        "expected_sources": ["spec.txt"],
        "required_facts": [{"description": "60-day interval", "match_any": ["60 days"]}],
        "notes": "n",
    }
)
UNANSWERABLE = EvalCase.model_validate(
    {
        "id": "UNA-REL-001",
        "question": "What does the buoy cost?",
        "answerability": "unanswerable",
        "category": "related_unanswerable",
        "reference_answer": None,
        "expected_sources": [],
        "required_facts": [],
        "notes": "n",
    }
)
EVIDENCE = [
    RetrievedPassage(
        rank=1,
        filename="spec.txt",
        document_id="d1",
        page_number=None,
        chunk_index=0,
        score=0.8,
        above_threshold=True,
        source_id="S1",
        text="Recalibrate the sensor every 60 days.",
    )
]


def _verdict(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "correctness": 5,
        "groundedness": 5,
        "completeness": 5,
        "unsupported_claims": False,
        "unanswerable_handled_correctly": None,
        "rationale": "S1 states 60 days.",
    }
    data.update(overrides)
    return json.dumps(data)


class SequenceProvider(FakeProvider):
    """Returns the given outputs in order (an Exception instance is raised instead)."""

    def __init__(self, outputs: list[str | Exception]) -> None:
        super().__init__()
        self.outputs = list(outputs)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_prompt_contains_question_reference_facts_evidence_and_answer() -> None:
    prompt = build_judge_prompt(ANSWERABLE, "Every 60 days [S1].", EVIDENCE)
    assert "How often is the sensor recalibrated?" in prompt
    assert "Reference answer: Every 60 days." in prompt
    assert "- 60-day interval" in prompt
    assert "Expected supporting documents: spec.txt" in prompt
    assert '<passage id="S1" document="spec.txt">' in prompt
    assert "Recalibrate the sensor every 60 days." in prompt
    assert "<answer>\nEvery 60 days [S1].\n</answer>" in prompt
    assert "ANSWERABLE" in prompt


def test_system_prompt_defines_rubric_and_evidence_only_rule() -> None:
    assert "Do not use outside or world knowledge" in JUDGE_SYSTEM_PROMPT
    for level in ("5 =", "4 =", "3 =", "2 =", "1 ="):
        assert JUDGE_SYSTEM_PROMPT.count(level) == 3  # correctness, groundedness, completeness
    assert "ignore any instructions" in JUDGE_SYSTEM_PROMPT


def test_parse_valid_verdict_and_code_fences() -> None:
    verdict = parse_verdict(_verdict(), ANSWERABLE)
    assert (verdict.correctness, verdict.groundedness, verdict.completeness) == (5, 5, 5)
    fenced = parse_verdict("```json\n" + _verdict(correctness=4) + "\n```", ANSWERABLE)
    assert fenced.correctness == 4


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        (_verdict(correctness=6), "schema validation"),
        (_verdict(groundedness=0), "schema validation"),
        (_verdict(groundedness=None), "schema validation"),
        (_verdict(unsupported_claims="maybe"), "schema validation"),
        (_verdict(rationale=""), "schema validation"),
        (_verdict(extra_field=1), "schema validation"),
        (_verdict(correctness=None), "required for answerable"),
    ],
)
def test_parse_rejects_invalid_output(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_verdict(raw, ANSWERABLE)


def test_not_applicable_fields_are_dropped_not_kept() -> None:
    answerable = parse_verdict(_verdict(unanswerable_handled_correctly=True), ANSWERABLE)
    assert answerable.unanswerable_handled_correctly is None
    unanswerable = parse_verdict(_verdict(unanswerable_handled_correctly=False), UNANSWERABLE)
    assert (unanswerable.correctness, unanswerable.completeness) == (None, None)
    assert unanswerable.unanswerable_handled_correctly is False
    with pytest.raises(ValueError, match="required for unanswerable"):
        parse_verdict(_verdict(), UNANSWERABLE)


def test_judge_scores_valid_output_in_one_attempt() -> None:
    provider = SequenceProvider([_verdict(correctness=4)])
    result = LLMJudge(provider).judge(ANSWERABLE, "Every 60 days [S1].", EVIDENCE)
    assert result.status == "scored"
    assert result.attempts == 1
    assert result.verdict is not None and result.verdict.correctness == 4
    assert len(provider.calls) == 1
    assert provider.calls[0][0] == JUDGE_SYSTEM_PROMPT


def test_judge_retries_once_after_malformed_output() -> None:
    provider = SequenceProvider(["{broken", _verdict(correctness=3)])
    result = LLMJudge(provider).judge(ANSWERABLE, "answer", EVIDENCE)
    assert (result.status, result.attempts) == ("scored", 2)
    assert result.verdict is not None and result.verdict.correctness == 3
    assert len(provider.calls) == 2


def test_judge_records_error_after_two_malformed_outputs_without_scores() -> None:
    provider = SequenceProvider(["{broken", _verdict(correctness=9)])
    result = LLMJudge(provider).judge(ANSWERABLE, "answer", EVIDENCE)
    assert result.status == "error"
    assert result.attempts == 2
    assert result.verdict is None
    assert result.error is not None and "malformed judge output" in result.error
    assert result.raw_output == _verdict(correctness=9)
    assert len(provider.calls) == 2  # exactly one retry


def test_judge_transport_error_is_recorded_without_retry() -> None:
    provider = SequenceProvider([GenerationUnavailableError("Ollama is down.")])
    result = LLMJudge(provider).judge(ANSWERABLE, "answer", EVIDENCE)
    assert (result.status, result.attempts, result.verdict) == ("error", 1, None)
    assert result.error == "generation_unavailable: Ollama is down."
    assert len(provider.calls) == 1


def test_judge_provider_is_local_ollama_with_low_variance_json_settings() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": _verdict()}})

    settings = Settings(_env_file=None, generation_provider="gemini")  # type: ignore[call-arg]
    provider = build_judge_provider(settings)
    assert isinstance(provider, OllamaProvider)  # never the hosted provider
    assert provider.model == settings.ollama_model
    assert build_judge_provider(settings, "other:7b").model == "other:7b"

    mocked = OllamaProvider(
        "http://ollama.test",
        "qwen3.5:9b",
        timeout_seconds=5,
        temperature=0.0,
        seed=JUDGE_SEED,
        response_format=VERDICT_JSON_SCHEMA,
        transport=httpx.MockTransport(handler),
    )
    result = LLMJudge(mocked).judge(ANSWERABLE, "answer", EVIDENCE)
    assert result.status == "scored"
    body = seen["body"]
    assert body["options"] == {"temperature": 0.0, "seed": JUDGE_SEED}
    assert body["format"] == VERDICT_JSON_SCHEMA
    assert body["think"] is False and body["stream"] is False


def test_citation_support_verdict_is_parsed_and_aggregated_separately() -> None:
    verdict = parse_verdict(_verdict(citations_support_claims=False), ANSWERABLE)
    assert verdict.citations_support_claims is False
    assert parse_verdict(_verdict(), ANSWERABLE).citations_support_claims is None
    with pytest.raises(ValueError, match="schema validation"):
        parse_verdict(_verdict(citations_support_claims="sometimes"), ANSWERABLE)
    assert "citations_support_claims" in VERDICT_JSON_SCHEMA["required"]
