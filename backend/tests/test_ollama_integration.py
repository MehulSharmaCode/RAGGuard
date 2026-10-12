"""Opt-in end-to-end check with the real embedding model and a running Ollama.

Excluded from the default run. Execute with:  .venv/bin/pytest -m ollama
Skips (with a reason) if Ollama is unreachable or the model is not installed.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import FREEDONIA_TXT

pytestmark = pytest.mark.ollama


@pytest.fixture
def live_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        generation_provider="ollama",
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen3.5:9b"),
        qdrant_local_path=tmp_path / "qdrant",
        qdrant_collection_name="ollama_integration",
    )
    with TestClient(create_app(settings)) as client:
        generation = client.get("/health").json()["components"]["generation"]
        if generation["status"] != "ready":
            pytest.skip(f"Ollama not ready: {generation['detail']}")
        yield client


def test_real_answer_with_sources_and_real_fallback(live_client: TestClient) -> None:
    ingest = live_client.post(
        "/ingest", files={"file": ("freedonia.txt", FREEDONIA_TXT.encode(), "text/plain")}
    )
    assert ingest.status_code == 201, ingest.text

    answered = live_client.post("/query", json={"question": "What is the capital of Freedonia?"})
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["status"] == "answered", body
    assert "Fredville" in body["answer"]
    assert "<think>" not in body["answer"]
    assert body["generation"]["provider"] == "ollama"
    assert body["sources"][0]["filename"] == "freedonia.txt"

    unrelated = live_client.post(
        "/query", json={"question": "What is the boiling point of liquid nitrogen?"}
    ).json()
    assert unrelated["status"] == "insufficient_evidence", unrelated
