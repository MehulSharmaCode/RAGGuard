"""Runtime smoke test for a running RAGGuard deployment (Stage 6).

Standard library only, so it runs on the host without installing anything:

    python3 deployment/smoke_test.py                       # Compose stack on 127.0.0.1:8080
    python3 deployment/smoke_test.py --base-url http://127.0.0.1:18080
    python3 deployment/smoke_test.py --api-only --base-url http://127.0.0.1:8000   # no web server

What it does (every request goes through the real HTTP API of the running stack):
  1. web server: `/` serves the frontend, `/healthz` answers          (skipped with --api-only)
  2. `/health` and `/system/status` answer and report real components
  3. uploads a small synthetic TXT document written by this script (never your documents)
  4. the document is listed; a question stated in it is answered with a citation to it
  5. an unrelated question gets the safe fallback without calling the model
  6. deletes ONLY that document by the ID the API returned (unless --keep)

Persistence checks (documents survive restarts of the backend / Qdrant / the stack):
    python3 deployment/smoke_test.py --keep                # prints the document ID
    ... restart something ...
    python3 deployment/smoke_test.py --verify <document-id>
    python3 deployment/smoke_test.py --delete <document-id>

Every query is scoped to the synthetic document (`document_ids`), so whatever else is indexed
cannot influence the result. Exit code: 0 all checks passed, 1 a check failed, 2 nothing failed
but the generation provider was not ready, so answering was NOT verified (reported as SKIP).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

DOCUMENT_TEXT = """\
Zephyrine Harbour Beacon Maintenance Log (synthetic smoke-test document)

The beacon lamp of Zephyrine Harbour is serviced every 17 days by the harbour electrician
Marisol Quenby. During each service the lens is cleaned and the backup battery is tested.

The harbour office of Zephyrine Harbour is open from 07:30 to 16:00 on weekdays.
"""
ANSWERABLE = "How often is the beacon lamp of Zephyrine Harbour serviced?"
EXPECTED_FACT = "17 days"
UNRELATED = "Who painted the Mona Lisa?"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        print(f"  [{status:4}] {name}" + (f" — {detail}" if detail else ""), flush=True)

    def check(self, condition: bool, name: str, detail: str = "") -> bool:
        self.add("PASS" if condition else "FAIL", name, detail)
        return condition

    def count(self, status: str) -> int:
        return sum(1 for s, _, _ in self.rows if s == status)


def call(
    base: str,
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    multipart: tuple[str, bytes] | None = None,
    timeout: float = 400.0,
) -> tuple[int, dict[str, str], bytes]:
    data = None
    headers: dict[str, str] = {}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    if multipart is not None:
        filename, content = multipart
        boundary = f"----ragguard{uuid.uuid4().hex}"
        data = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def as_json(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def check_stack(base: str, report: Report, *, api_only: bool, expect_qdrant: str) -> bool:
    """Web server, /health, /system/status. Returns whether generation is ready."""
    if not api_only:
        status, headers, body = call(base, "GET", "/", timeout=15)
        report.check(
            status == 200 and b'id="root"' in body,
            "frontend is served at /",
            f"HTTP {status}, {headers.get('Content-Type', '?')}",
        )
        status, _, body = call(base, "GET", "/healthz", timeout=15)
        report.check(
            status == 200 and body.strip() == b"ok",
            "web server /healthz",
            f"HTTP {status}",
        )
    status, _, body = call(base, "GET", "/health", timeout=60)
    health = as_json(body)
    report.check(status == 200, "API /health answers (liveness)", f"HTTP {status}")
    components = health.get("components") or {}
    config = health.get("config") or {}
    assert isinstance(components, dict) and isinstance(config, dict)
    vector = components.get("vector_store") or {}
    report.check(
        isinstance(vector, dict) and vector.get("status") == "ok",
        "vector store is reachable",
        str(vector.get("detail", "") if isinstance(vector, dict) else ""),
    )
    if expect_qdrant != "any":
        report.check(
            config.get("qdrant_mode") == expect_qdrant,
            f"Qdrant mode is {expect_qdrant}",
            f"reported: {config.get('qdrant_mode')}",
        )
    report.add(
        "INFO",
        "prompt / model / embeddings",
        f"{config.get('prompt_version')} / {config.get('generation_provider')} "
        f"{config.get('generation_model')} / {config.get('embedding_model')}",
    )
    ready = health.get("generation_ready") is True
    generation = components.get("generation") or {}
    report.add(
        "INFO",
        "generation provider",
        ("ready" if ready else "NOT ready")
        + (f": {generation.get('detail')}" if isinstance(generation, dict) else ""),
    )
    status, _, body = call(base, "GET", "/system/status", timeout=60)
    system = as_json(body)
    states = {
        c["id"]: c["state"]
        for c in system.get("components", [])  # type: ignore[union-attr]
        if isinstance(c, dict)
    }
    report.check(status == 200 and bool(states), "API /system/status answers", f"HTTP {status}")
    report.add("INFO", "component states", json.dumps(states))
    return ready


def ingest(base: str, report: Report) -> str | None:
    filename = f"smoke-{uuid.uuid4().hex[:8]}.txt"
    status, _, body = call(base, "POST", "/ingest", multipart=(filename, DOCUMENT_TEXT.encode()))
    result = as_json(body)
    document_id = result.get("document_id")
    ok = status == 201 and result.get("status") == "indexed" and isinstance(document_id, str)
    report.check(
        ok,
        "synthetic document is uploaded and indexed",
        f"HTTP {status}, status={result.get('status')}, chunks={result.get('chunk_count')}",
    )
    return document_id if ok and isinstance(document_id, str) else None


def listed(base: str, document_id: str) -> bool:
    _, _, body = call(base, "GET", "/documents", timeout=60)
    documents = as_json(body).get("documents", [])
    return any(isinstance(d, dict) and d.get("document_id") == document_id for d in documents)  # type: ignore[union-attr]


def check_answer(base: str, report: Report, document_id: str, generation_ready: bool) -> None:
    status, _, body = call(
        base,
        "POST",
        "/query",
        json_body={"question": ANSWERABLE, "document_ids": [document_id]},
    )
    result = as_json(body)
    sources = [s for s in result.get("sources", []) if isinstance(s, dict)]  # type: ignore[union-attr]
    if status == 200 and result.get("status") == "answered":
        answer = str(result.get("answer", ""))
        cited = [s for s in sources if s.get("cited")]
        report.check(
            EXPECTED_FACT in answer,
            "answerable question is answered with the stated fact",
            answer[:140].replace("\n", " "),
        )
        report.check(
            bool(cited) and all(s.get("document_id") == document_id for s in cited),
            "the answer cites the synthetic document",
            f"cited={[s.get('source_id') for s in cited]}",
        )
        report.check(
            any(EXPECTED_FACT in str(s.get("excerpt", "")) for s in cited),
            "the cited passage contains the fact",
        )
        return
    if not generation_ready:
        error = (result.get("error") or {}) if isinstance(result.get("error"), dict) else {}
        report.add(
            "SKIP",
            "answerable question (model inference NOT verified)",
            f"generation provider not ready; /query returned HTTP {status} {error.get('code', '')}",
        )
        return
    report.check(False, "answerable question is answered", f"HTTP {status}: {body[:200]!s}")


def check_fallback(base: str, report: Report, document_id: str) -> None:
    status, _, body = call(
        base,
        "POST",
        "/query",
        json_body={"question": UNRELATED, "document_ids": [document_id]},
    )
    result = as_json(body)
    report.check(
        status == 200
        and result.get("status") == "insufficient_evidence"
        and result.get("fallback_reason") == "below_threshold"
        and result.get("generation") is None
        and result.get("sources") == [],
        "unrelated question gets the safe fallback (no sources, model not called)",
        f"HTTP {status}, status={result.get('status')}, reason={result.get('fallback_reason')}",
    )


def delete(base: str, report: Report, document_id: str) -> None:
    status, _, _ = call(base, "DELETE", f"/documents/{document_id}", timeout=60)
    report.check(status == 200, "synthetic document is deleted by its ID", f"HTTP {status}")
    report.check(not listed(base, document_id), "the deleted document is no longer listed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-only", action="store_true", help="the URL is the API itself")
    parser.add_argument(
        "--expect-qdrant",
        choices=["remote", "local", "any"],
        default="remote",
        help="Qdrant mode /health must report (Compose: remote; default remote)",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--keep", action="store_true", help="do not delete the document; print its ID"
    )
    action.add_argument("--verify", metavar="ID", help="check that this document still works")
    action.add_argument("--delete", metavar="ID", help="delete this document and stop")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    report = Report()
    print(f"RAGGuard smoke test against {base}")

    try:
        if args.delete:
            delete(base, report, args.delete)
        else:
            ready = check_stack(
                base, report, api_only=args.api_only, expect_qdrant=args.expect_qdrant
            )
            if args.verify:
                document_id = args.verify
                report.check(listed(base, document_id), "document is still listed", document_id)
                check_answer(base, report, document_id, ready)
                check_fallback(base, report, document_id)
            else:
                document_id = ingest(base, report) or ""
                if document_id:
                    report.check(listed(base, document_id), "the document is listed", document_id)
                    check_answer(base, report, document_id, ready)
                    check_fallback(base, report, document_id)
                    if args.keep:
                        print(f"\nKEPT document {document_id} (remove: --delete {document_id})")
                    else:
                        delete(base, report, document_id)
    except (urllib.error.URLError, OSError) as error:
        report.add("FAIL", "the stack is reachable", f"{type(error).__name__}: {error}")

    failed, skipped, passed = (
        report.count("FAIL"),
        report.count("SKIP"),
        report.count("PASS"),
    )
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        return 1
    if skipped:
        print("Some checks were SKIPPED: the result is not a full pass.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
