"""Opt-in retrieval diagnostics endpoint (D-066)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.generation.prompts import SYSTEM_PROMPT
from app.main import create_app
from app.pipeline import RAGPipeline
from tests.conftest import FREEDONIA_TXT, FakeProvider


@pytest.fixture
def diag_client(settings: Settings, pipeline: RAGPipeline) -> Iterator[TestClient]:
    enabled = settings.model_copy(update={"retrieval_diagnostics": True})
    with TestClient(create_app(enabled, pipeline)) as test_client:
        test_client.post(
            "/ingest", files={"file": ("freedonia.txt", FREEDONIA_TXT.encode(), "text/plain")}
        )
        yield test_client


def test_disabled_by_default_and_absent_from_the_schema(client: TestClient) -> None:
    assert client.post("/diagnostics/query", json={"question": "capital?"}).status_code == 404
    assert "/diagnostics/query" not in client.get("/openapi.json").json()["paths"]


def test_lists_candidates_and_the_gate_without_calling_the_model(
    diag_client: TestClient, provider: FakeProvider
) -> None:
    response = diag_client.post(
        "/diagnostics/query", json={"question": "What is the capital of Freedonia?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "model_not_called"
    assert body["threshold"] == 0.3 and body["top_k"] == 4
    assert body["index_format"] == "hybrid"
    evidence = [c for c in body["candidates"] if c["evidence"]]
    assert evidence and evidence[0]["source_id"] == "S1" and evidence[0]["above_threshold"]
    assert "Fredville" in " ".join(c["excerpt"] for c in evidence)
    assert all(len(c["excerpt"]) <= 400 for c in body["candidates"])
    assert body["prompt_characters"] > 0 and body["model"] is None
    assert provider.calls == []


def test_unrelated_question_is_gated(diag_client: TestClient) -> None:
    body = diag_client.post("/diagnostics/query", json={"question": "zebra quantum tango"}).json()
    assert body["decision"] in ("below_threshold", "no_results")
    assert body["evidence_count"] == 0 and body["model"] is None


def test_returns_the_raw_reply_and_how_the_pipeline_reads_it(
    diag_client: TestClient, provider: FakeProvider
) -> None:
    provider.answer = "The documents do not say. INSUFFICIENT_EVIDENCE"
    body = diag_client.post(
        "/diagnostics/query",
        json={"question": "What is the capital of Freedonia?", "generate": True},
    ).json()
    assert body["decision"] == "model_called"
    assert body["model"]["interpretation"] == "declined"
    assert "INSUFFICIENT_EVIDENCE" in body["model"]["raw"]


def test_never_returns_a_reply_that_reproduces_the_system_prompt(
    diag_client: TestClient, provider: FakeProvider
) -> None:
    provider.answer = SYSTEM_PROMPT
    body = diag_client.post(
        "/diagnostics/query",
        json={"question": "What is the capital of Freedonia?", "generate": True},
    ).json()
    assert body["model"] == {
        "interpretation": "withheld",
        "raw": None,
        "generation_ms": body["model"]["generation_ms"],
    }
