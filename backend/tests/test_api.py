"""HTTP API tests through FastAPI's TestClient with a fake embedder and fake LLM."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import (
    GenerationConfigError,
    GenerationRateLimitError,
    GenerationUnavailableError,
    GenerationUpstreamError,
)
from app.generation.base import ProviderStatus
from app.generation.gemini import GeminiProvider
from app.generation.ollama import OllamaProvider
from app.generation.prompts import FALLBACK_ANSWER, SYSTEM_PROMPT
from app.main import build_pipeline, create_app
from tests.conftest import FREEDONIA_TXT, ORBIT_PAGES, FakeProvider, make_pdf


def _upload(client: TestClient, name: str, content: bytes, mime: str = "text/plain") -> Any:
    return client.post("/ingest", files={"file": (name, content, mime)})


def _ingest_txt(client: TestClient) -> dict[str, Any]:
    response = _upload(client, "freedonia.txt", FREEDONIA_TXT.encode())
    assert response.status_code == 201, response.text
    return dict(response.json())


def _ingest_pdf(client: TestClient) -> dict[str, Any]:
    response = _upload(client, "orbits.pdf", make_pdf(ORBIT_PAGES), "application/pdf")
    assert response.status_code == 201, response.text
    return dict(response.json())


# --- /health ---------------------------------------------------------------------
def test_health_ok_without_calling_the_llm(client: TestClient, provider: FakeProvider) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["api"] == "ok"
    assert body["generation_ready"] is True
    assert body["components"]["vector_store"]["status"] == "ok"
    assert body["components"]["generation"]["status"] == "ready"
    assert body["config"]["chunk_size_tokens"] == 40
    assert body["config"]["max_upload_size_mb"] == 1
    assert provider.calls == []


def test_health_is_degraded_but_up_when_provider_unavailable(
    client: TestClient, provider: FakeProvider
) -> None:
    provider.status = ProviderStatus("unavailable", "The Ollama service is not reachable.")
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["api"] == "ok"
    assert body["generation_ready"] is False
    assert body["components"]["generation"]["status"] == "unavailable"


def test_health_never_exposes_secrets(tmp_path: Any) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        generation_provider="gemini",
        gemini_api_key="super-secret-test-key",
        qdrant_local_path=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        body = client.get("/health").text
    assert "super-secret-test-key" not in body
    assert '"configured"' in body


# --- /ingest ---------------------------------------------------------------------
def test_ingest_txt(client: TestClient) -> None:
    body = _ingest_txt(client)
    uuid.UUID(body["document_id"])
    assert body["filename"] == "freedonia.txt"
    assert body["file_type"] == "txt"
    assert body["total_pages"] is None
    assert body["chunk_count"] >= 1
    assert body["status"] == "indexed"


def test_ingest_pdf_records_pages(client: TestClient) -> None:
    body = _ingest_pdf(client)
    assert body["file_type"] == "pdf"
    assert body["total_pages"] == 3
    assert body["pages_with_text"] == 2
    assert body["chunk_count"] >= 2


def test_each_upload_gets_a_new_document_id(client: TestClient) -> None:
    first, second = _ingest_txt(client), _ingest_txt(client)
    assert first["document_id"] != second["document_id"]
    listed = client.get("/documents").json()["documents"]
    assert {d["document_id"] for d in listed} == {first["document_id"], second["document_id"]}


@pytest.mark.parametrize(
    ("name", "content", "status", "code"),
    [
        ("notes.docx", b"hello", 415, "unsupported_file"),
        ("fake.pdf", b"not a pdf", 415, "unsupported_file"),
        ("empty.txt", b"", 415, "unsupported_file"),
        ("blank.txt", b"  \n\n ", 422, "empty_document"),
        ("latin1.txt", "café".encode("latin-1"), 422, "extraction_failed"),
        ("broken.pdf", b"%PDF-1.4 garbage", 422, "extraction_failed"),
        ("scan.pdf", make_pdf([""]), 422, "empty_document"),
    ],
)
def test_ingest_rejects_invalid_files(
    client: TestClient, name: str, content: bytes, status: int, code: str
) -> None:
    response = _upload(client, name, content)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_ingest_rejects_oversized_file(client: TestClient) -> None:
    response = _upload(client, "big.txt", b"word " * (1024 * 1024 // 5 + 10))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_ingest_requires_a_file(client: TestClient) -> None:
    response = client.post("/ingest")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- /query ----------------------------------------------------------------------
def test_query_returns_answer_with_genuine_sources(
    client: TestClient, provider: FakeProvider
) -> None:
    doc = _ingest_txt(client)
    _ingest_pdf(client)

    response = client.post("/query", json={"question": "What is the capital of Freedonia?"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "answered"
    assert body["answerable"] is True
    assert body["fallback_reason"] is None
    assert body["answer"] == provider.answer
    assert body["generation"] == {"provider": "fake", "model": "fake-model", "prompt_version": "v1"}

    sources = body["sources"]
    assert sources, "an answered query must carry sources"
    top = sources[0]
    assert top["source_id"] == "S1"
    assert top["document_id"] == doc["document_id"]
    assert top["filename"] == "freedonia.txt"
    assert top["page_number"] is None
    assert "Fredville" in top["excerpt"]
    assert top["cited"] is True
    assert all(s["score"] >= 0.3 for s in sources)
    assert [s["source_id"] for s in sources] == [f"S{i + 1}" for i in range(len(sources))]
    assert body["evidence"]["supporting_count"] == len(sources)

    # The model saw exactly these passages, labelled with the same IDs.
    assert len(provider.calls) == 1
    system_prompt, user_prompt = provider.calls[0]
    assert system_prompt == SYSTEM_PROMPT
    for source in sources:
        assert f'<source id="{source["source_id"]}" document="{source["filename"]}"' in user_prompt
        assert source["excerpt"] in user_prompt
    assert user_prompt.rstrip().endswith("Question: What is the capital of Freedonia?")

    latency = body["latency_ms"]
    assert latency["total_ms"] >= latency["embedding_ms"]
    assert latency["generation_ms"] is not None


def test_query_pdf_sources_carry_page_numbers(client: TestClient, provider: FakeProvider) -> None:
    pdf = _ingest_pdf(client)
    provider.answer = "About 35786 kilometres [S1]."
    body = client.post(
        "/query", json={"question": "At what altitude do geostationary satellites orbit?"}
    ).json()
    assert body["status"] == "answered"
    top = body["sources"][0]
    assert top["document_id"] == pdf["document_id"]
    assert top["filename"] == "orbits.pdf"
    assert top["page_number"] == 3


def test_uncited_sources_are_marked(client: TestClient, provider: FakeProvider) -> None:
    _ingest_txt(client)
    provider.answer = "Fredville, founded in 1820."
    body = client.post("/query", json={"question": "capital of Freedonia Fredville"}).json()
    assert body["status"] == "answered"
    assert all(s["cited"] is False for s in body["sources"])


def test_query_document_filter(client: TestClient, provider: FakeProvider) -> None:
    _ingest_txt(client)
    pdf = _ingest_pdf(client)
    body = client.post(
        "/query",
        json={
            "question": "What is the capital of Freedonia?",
            "document_ids": [pdf["document_id"]],
        },
    ).json()
    # The PDF says nothing about Freedonia, so evidence is insufficient within the filter.
    assert body["status"] == "insufficient_evidence"
    assert provider.calls == []
    assert all(s["document_id"] == pdf["document_id"] for s in body["sources"])


def test_query_top_k_override(client: TestClient) -> None:
    _ingest_pdf(client)
    _ingest_txt(client)
    body = client.post(
        "/query", json={"question": "Freedonia capital Fredville river", "top_k": 1}
    ).json()
    assert body["evidence"]["top_k"] == 1
    assert body["evidence"]["retrieved_count"] == 1
    assert len(body["sources"]) <= 1


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {},
        {"question": "ok", "top_k": 0},
        {"question": "ok", "top_k": 21},
        {"question": "ok", "document_ids": []},
        {"question": "ok", "document_ids": ["not-a-uuid"]},
        {"question": "ok", "unexpected": 1},
        {"question": "x" * 2001},
    ],
)
def test_query_rejects_invalid_requests(
    client: TestClient, provider: FakeProvider, payload: dict[str, Any]
) -> None:
    response = client.post("/query", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert provider.calls == []


def test_query_malformed_json(client: TestClient) -> None:
    response = client.post(
        "/query", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422


def test_fallback_when_nothing_indexed(client: TestClient, provider: FakeProvider) -> None:
    body = client.post("/query", json={"question": "What is the capital of Freedonia?"}).json()
    assert body["status"] == "insufficient_evidence"
    assert body["answerable"] is False
    assert body["fallback_reason"] == "no_results"
    assert body["answer"] == FALLBACK_ANSWER
    assert body["sources"] == []
    assert body["generation"] is None
    assert body["latency_ms"]["generation_ms"] is None
    assert provider.calls == []


def test_fallback_when_evidence_below_threshold(client: TestClient, provider: FakeProvider) -> None:
    _ingest_txt(client)
    body = client.post(
        "/query", json={"question": "How do penguins hunt beneath antarctic ice shelves?"}
    ).json()
    assert body["status"] == "insufficient_evidence"
    assert body["fallback_reason"] == "below_threshold"
    assert body["evidence"]["retrieved_count"] >= 1
    assert body["evidence"]["max_score"] < 0.3
    assert "did not provide sufficient evidence" in body["answer"]
    assert body["sources"] == []
    assert provider.calls == []


def test_fallback_when_model_declines(client: TestClient, provider: FakeProvider) -> None:
    _ingest_txt(client)
    provider.answer = "INSUFFICIENT_EVIDENCE"
    body = client.post(
        "/query", json={"question": "What is the population of Freedonia's capital?"}
    ).json()
    assert len(provider.calls) == 1
    assert body["status"] == "insufficient_evidence"
    assert body["fallback_reason"] == "model_declined"
    assert body["answer"] == FALLBACK_ANSWER
    assert body["sources"] == []
    assert body["generation"]["provider"] == "fake"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (
            GenerationUnavailableError("The Ollama service is not reachable."),
            503,
            "generation_unavailable",
        ),
        (GenerationConfigError("GEMINI_API_KEY is not set."), 500, "generation_not_configured"),
        (GenerationRateLimitError("rate limited"), 429, "generation_rate_limited"),
        (GenerationUpstreamError("upstream"), 502, "generation_upstream_error"),
    ],
)
def test_provider_errors_map_to_http_errors(
    client: TestClient, provider: FakeProvider, error: Exception, status: int, code: str
) -> None:
    _ingest_txt(client)
    provider.error = error
    response = client.post("/query", json={"question": "What is the capital of Freedonia?"})
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": str(error)}}


def test_unexpected_errors_do_not_leak_details(settings: Settings, pipeline: Any) -> None:
    pipeline.provider.error = RuntimeError("secret internal path /etc/x")
    with TestClient(create_app(settings, pipeline), raise_server_exceptions=False) as client:
        _ingest_txt(client)
        response = client.post("/query", json={"question": "capital of Freedonia?"})
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred."}
    }


# --- /documents ------------------------------------------------------------------
def test_list_and_delete_documents(client: TestClient) -> None:
    txt, pdf = _ingest_txt(client), _ingest_pdf(client)
    listed = {d["document_id"]: d for d in client.get("/documents").json()["documents"]}
    assert listed[pdf["document_id"]]["chunk_count"] == pdf["chunk_count"]
    assert listed[txt["document_id"]]["filename"] == "freedonia.txt"

    response = client.delete(f"/documents/{txt['document_id']}")
    assert response.status_code == 200
    assert response.json()["deleted_chunks"] == txt["chunk_count"]
    remaining = [d["document_id"] for d in client.get("/documents").json()["documents"]]
    assert remaining == [pdf["document_id"]]

    assert client.delete(f"/documents/{txt['document_id']}").status_code == 404
    assert client.delete("/documents/not-a-uuid").status_code == 422


# --- provider isolation ----------------------------------------------------------
def test_gemini_is_never_used_when_ollama_is_selected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Gemini must not be used when GENERATION_PROVIDER=ollama")

    monkeypatch.setattr(GeminiProvider, "__init__", forbidden)
    monkeypatch.setattr(GeminiProvider, "generate", forbidden)
    pipeline = build_pipeline(settings)
    assert isinstance(pipeline.provider, OllamaProvider)
    pipeline.vector_store.close()


def test_ollama_failure_is_not_rerouted_to_gemini(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, pipeline: Any
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no silent failover to Gemini")

    monkeypatch.setattr(GeminiProvider, "generate", forbidden)
    pipeline.provider = OllamaProvider(
        "http://127.0.0.1:9", "qwen3.5:9b", timeout_seconds=2, temperature=0.1
    )
    with TestClient(create_app(settings, pipeline)) as client:
        _ingest_txt(client)
        response = client.post("/query", json={"question": "What is the capital of Freedonia?"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "generation_unavailable"


def test_cors_allows_the_default_vite_origins(client: TestClient) -> None:
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/query",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    blocked = client.options(
        "/query",
        headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in blocked.headers
