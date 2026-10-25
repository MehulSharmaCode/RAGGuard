# RAGGuard — Architecture

> Status as of Stage 5.5 plus the pre-demo pass (2026-10-15: second benchmark, prompt v6, citation groups; D-059–D-062) the retrieval pass (2026-10-16: layout-aware extraction, structure-aware chunks, sub-unit index; D-063), and Stage 5.7 (2026-10-16: fragment-safe extraction, hybrid candidates with dense-order evidence, conversations per document context, opt-in diagnostics; D-064–D-066; stabilisation: prompt v7, evaluator e2; D-067, D-068; closure 2026-10-25: prompt v8 — span withholding, supersession policy, answer check, split-region passages — evaluator e3; D-069–D-074), and Stage 6 (2026-10-26: Docker Compose deployment; D-075–D-078, §3e), and Stage 7 (2026-10-26: GitHub Actions workflow and offline quality gate, CI runs in the Pipeline view; D-079–D-084, §5): the **backend RAG pipeline and API** (sections 2 "Backend API", 3, 3a — with the Stage 5 prompt-injection and source-handling mitigations, §3c), the **frontend** (sections 2 "Frontend", 3b) including the Evaluation, Experiments, and Pipeline views and app-level conversation state (§3d), the **offline evaluation path** (sections 2 "Evaluation", 4, 4a), **MLflow experiment tracking** (section 2 "Experiment tracking", 4a), and the **read-only dashboard API** (§3d) are implemented. The visual redesign is deferred until the owner supplies references (D-046, D-053); CI remains proposed. Decisions referenced as `D-xxx` are in [`DECISIONS.md`](DECISIONS.md).

## 1. System overview

RAGGuard has three distinct flows that share one RAG pipeline implementation:

| Flow | Trigger | Purpose | Runs where |
| --- | --- | --- | --- |
| Live query path | A user asks a question | Answer from indexed documents with citations | Running backend service |
| Evaluation path | A developer or CI job runs the evaluation suite | Measure pipeline quality on a fixed dataset | Locally or in CI |
| Release path | A code change (push / pull request, as configured) | Decide whether a change may be built and released | GitHub Actions |

The same retrieval and generation code serves both live queries and evaluation, so the evaluation measures what users actually get.

## 2. Components and responsibilities

### Frontend (`frontend/`) — implemented in Stage 3, data views in Stage 5.5
React + TypeScript + Vite + Tailwind CSS single-page application. Talks to the backend only through its HTTP API and holds no secrets; the only build-time variable is the public `VITE_API_BASE_URL`.

| Path | Responsibility |
| --- | --- |
| `src/main.tsx`, `src/app/` | Entry point; `App` (shell, `ConversationProvider`, hash routing via `useRoute` — `#/<view>[/<param>]`, lazy-loaded data views, theme), `Shell` (nav rail, top bar, backend status), `Workspace` (three-column composition), `useHealth` (polls `GET /health` every 30 s) |
| `src/lib/api/` | The only HTTP code: `client.ts` (base URL, timeouts, error normalisation), `endpoints.ts` (one function per endpoint), `guards.ts` (runtime response validation) |
| `src/lib/` | `format.ts` (display formatting), `browser.ts` (media queries, storage, WebGL detection, theme, token colours), `metrics.ts` (metric values: "Not recorded" vs. "n/a" vs. value with count; deltas), `useResource.ts` (keyed GET loader with refresh and abort) |
| `src/types/api.ts` | Types mirroring the backend Pydantic schemas |
| `src/components/ui/` | Primitives: `Button`, `StatusTag`, `InlineAlert` |
| `src/components/data/` | `MetricLedger` (grouped metric rows), `Section`, field and download-link styles |
| `src/features/documents/` | `useDocuments` / `useUpload` (state), `UploadZone`, `DocumentList` (scope checkboxes, confirmed removal) |
| `src/features/chat/` | `ConversationProvider` (app-level thread, selection, scope; runs `/query`), `conversationStorage` (sessionStorage copy, D-054), `useConversation` (context hook and turn types), `QuestionInput`, `TurnView` (answer / fallback / failure), `AnswerText` + `parseAnswer` (paragraphs, lists, citation markers; adjacent markers form one `[S1, S2]` group, D-062), `EvidencePanel` |
| `src/features/chat/trace/` | Evidence Trace: `traceModel` (from real response + document list), `layout` (shared geometry), `TraceScene3D` (lazy, R3F), `TraceDiagram2D` (SVG fallback), `SceneView` (renderer choice, lazy loading, error boundary), `EvidenceTrace`, `FirstRunIllustration` |
| `src/styles/` | `tokens.css` (design tokens, both themes), `index.css` (fonts, Tailwind theme binding, base styles) |
| `src/test/` | Vitest + React Testing Library tests with a mocked HTTP layer |
| `src/features/evaluation/` | `EvaluationView` (report selector, run header, open findings, metric ledger, latency, judge, definitions), `CaseTable` (filters, expected-vs-actual case detail), `labels` |
| `src/features/experiments/` | `ExperimentsView` (tracking state, runs table with baseline/candidate selection, run detail with artifact links, comparison) |
| `src/features/pipeline/` | `PipelineView` (code-path diagram with current settings, offline lane, component status, recent GitHub Actions runs, not-built-yet list) |
| `src/lib/api/github.ts` | Anonymous, validated, cached read of GitHub's public Actions API for the Pipeline view (D-083); separate from the RAGGuard API client |

### Backend API (`backend/app/`) — implemented in Stage 2
FastAPI service with Pydantic schemas.

| Module | Responsibility |
| --- | --- |
| `main.py` | Application factory (`create_app`), lifespan (builds the pipeline), CORS, JSON error handlers, router registration |
| `pipeline.py` | `RAGPipeline`: the single orchestration of ingestion, question answering, listing, deletion, and health — shared by the API and the evaluation runner (D-028). Question answering is `answer()` = `generate_answer(retrieve_evidence())` (D-041) |
| `api/routes/` | Thin HTTP handlers: `documents.py` (`POST /ingest`, `GET /documents`, `DELETE /documents/{id}`), `query.py` (`POST /query`), `health.py` (`GET /health`), and the read-only dashboard routes `evaluations.py`, `experiments.py`, `system.py` (§3d); `api/dependencies.py` injects the pipeline, settings, report store, and tracking reader |
| `core/` | `config.py` (pydantic-settings `Settings`), `errors.py` (error hierarchy with HTTP status + code), `logging.py` |
| `schemas/` | Pydantic request/response models — the API contract with the frontend |
| `ingestion/` | `validation.py` (extension, size, signature), `extraction.py` (pypdf per page with layout-aware text and plain-text fallback / UTF-8 TXT), `pdf_layout.py` (lines, blocks, table rows, regions from positioned text runs), `chunking.py` (structure-aware, token-aware chunks, page-bounded; retrieval sub-units) |
| `embeddings/` | `base.py` (`Embedder` protocol incl. tokenizer spans), `sentence_transformer.py` (lazy-loaded local MiniLM) |
| `retrieval/` | `vector_store.py` (Qdrant client modes, index formats hybrid/subunit/legacy, upsert, filtered dense or hybrid search, listing, deletion), `lexical.py` (BM25-weighted sparse vectors, rank fusion; D-064), `evidence.py` (sufficiency rule, format-aware threshold) |
| `generation/` | `base.py` (`GenerationProvider` protocol), `ollama.py`, `gemini.py`, `factory.py` (provider selection), `prompts.py` (prompt v8: system rules, evidence framing, markup neutralisation, instruction-hint and supersession labels, instruction-span withholding, supersession policy, repair prompt, citation parsing, decline detection, system-prompt leak check, fallback text), `answer_check.py` (citation, page, and value check, D-071) |
| `evaluation/` | Offline evaluation (Stages 4–5): `dataset` (schema 2 incl. attack specs, validation, fingerprint), `runner` (isolated store, execution through `RAGPipeline`, `score_case`, `rescore_report`), `metrics` (deterministic checks, versioned as `EVALUATOR_VERSION` and recorded in each report — e2 counts forbidden content only when not negated in its clause, D-068; e3 ignores short parenthetical glosses inside required facts, D-073: retrieval incl. expected pages, citations, claim support, superseded citations, unsupported content, attacks, correctness; aggregates), `threshold` (offline sweep), `judge` (local LLM judge v2), `schemas` + `report` (JSON/Markdown reports, schema 2.0), `run_evaluation` (CLI), `quality_gate` (Stage 7, D-079: the offline, model-free CI gate and its thresholds file `evaluation/quality_gate.json`) |
| `evaluation/` (Stage 5.5 additions) | `catalog` (principal metrics: report JSON path = MLflow metric name, label, group, direction), `results` (`ReportStore`: list, view, and serve saved reports read-only, path redaction) |
| `tracking/` | `mlflow_tracking.py` (Stage 5): logs a report as an MLflow run — whitelisted parameters, flattened metrics, report artifacts (evaluation CLI). `reader.py` (Stage 5.5): read-only `TrackingReader` and run comparison for the API, lazy MLflow import |
| `system_status.py` | Component states for `GET /system/status` (Stage 5.5) |

Provider-specific code (embedding model, LLM provider) sits behind small interfaces so it can be swapped and so tests can use fakes. Retrieval, prompt construction, and source references are provider-independent; providers only turn a system prompt + user prompt into text.

### Vector store — Qdrant
Stores one point per chunk with named vectors ("hybrid" index, D-064): `dense`, several 384-dimensional normalized vectors — the whole chunk and its structural sub-units — compared with `MAX_SIM`, so a chunk's score is its best vector's cosine (D-063); and `lexical`, a BM25-weighted sparse vector of the chunk text with Qdrant's IDF modifier; payload: document ID, filename, file type, total pages, page number or null, chunk index, chunk text, character span, token count, sub-unit texts, embedding model, ingestion time. Older collections are detected and keep working: D-063 "subunit" collections (dense multivector only, dense search) and pre-D-063 "legacy" collections (one vector per point, threshold 0.30); an empty older collection is recreated as hybrid on the next upload, and one holding documents is never dropped. Point IDs are UUIDv5 of `document_id:chunk_index`. Distance is COSINE. In development the embedded client runs in **local persistent mode** (`QDRANT_LOCAL_PATH`); setting `QDRANT_URL` switches to a Qdrant server (D-027). The collection is created on first ingest, and its vector size/distance are validated against the embedding model.

### Evaluation (`evaluation/`, `backend/app/evaluation/`) — implemented in Stage 4
- `evaluation/datasets/`: fixed, version-controlled `dataset.json` (questions, labels, reference answers, expected sources, required facts, diagnostics) and the synthetic `corpus/` it references (D-039; see its README) — the core regression benchmark `ragguard-synthetic`. A second benchmark, `evaluation/datasets/veil/` (`veil-document-challenge`, D-059), uses the same schema, evaluator, and CLI (`--dataset`); every report and MLflow run carries the dataset ID, version, and fingerprint, and runs on different fingerprints are never compared.
- `backend/app/evaluation/`: the runner and metrics (section 4a), run as `python -m app.evaluation.run_evaluation` from `backend/` (D-040).
- Generated reports are written to `evaluation/results/<run_id>/` (git-ignored) and, from Stage 5, logged to MLflow.

### Experiment tracking — MLflow (implemented in Stage 5)
Each evaluation run (and each imported or re-scored report) becomes one run in the experiment `ragguard-evaluation` (D-051):
- **Store:** local SQLite `mlflow.db` in the repository root with artifacts in `mlartifacts/` (both git-ignored); `MLFLOW_TRACKING_URI` or `--tracking-uri` overrides it (e.g. a server). No server is needed to log; `mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5050` shows the runs.
- **Parameters** (whitelist only): generation provider/model/prompt version/temperature, judge settings, embedding model, chunking, top-k, threshold, dataset id/version/fingerprint/case counts, report schema. **Tags:** RAGGuard run ID, status, dataset fingerprint, Git commit and dirty flag, label, imported/re-scored source.
- **Metrics:** every numeric aggregate under its JSON path (`security.attack_success_rate`, `correctness.case_pass_rate`, `latency.query.p95_ms`, …), each rate with `<name>.denominator`; null rates are omitted, not logged as 0. The threshold sweep is logged as stepped series (`threshold_sweep.f1`, step = threshold × 100).
- **Artifacts:** `reports/report.json`, `reports/report.md`, `reports/failures.json` (failed case IDs, failed checks, truncated synthetic answers).
- The query path never imports MLflow; a tracking failure makes the CLI exit with code 3 after the reports are written. Since Stage 5.5 the API **reads** the same store for the Experiments view, importing MLflow lazily (§3d, D-056).

### CI/CD — GitHub Actions (`.github/workflows/`)
`ragguard-ci.yml` (Stage 7, D-080) runs on pull requests to `main`, pushes to `main`, and manual dispatch: backend checks, frontend checks, dataset validation, and the offline quality gate (D-079), and only if all of them succeed builds the Docker images. It builds and validates; it does not publish or deploy (§5). Read-only permissions, no secrets, pinned actions (D-084).

### Packaging — Docker / Docker Compose (`compose.yaml`, `deployment/`; implemented in Stage 6)
Three containers orchestrated locally with Docker Compose — web (Nginx, production frontend + reverse proxy), backend (FastAPI), and a Qdrant server — with named volumes; Ollama stays on the host and no MLflow server is used. A local/demo deployment, not production infrastructure. Topology, networking, and data: §3e.

## 3. Live query path

```
User question
   │
   ▼
Frontend ── POST question ──▶ FastAPI
                                │
                                ▼
                     Embed question (embeddings/)
                                │
                                ▼
                  Similarity search in Qdrant (retrieval/)
                                │
                                ▼
                  Evidence sufficiency check
                     │                    │
              sufficient             insufficient
                     │                    │
                     ▼                    ▼
       Generate answer from        Safe fallback response
       retrieved chunks only       ("not enough evidence in the
       (generation/)                indexed documents"); no LLM call,
                     │              no sources, evidence summary only
                     ▼                    │
       Map claims to citations            │
       (document, page, chunk)            │
                     └─────────┬──────────┘
                               ▼
              Response: answer | fallback, sources, timing
```

- The LLM is instructed to answer only from supplied evidence and to cite it.
- The sufficiency rule (e.g. similarity threshold, minimum supporting chunks) is configurable and tuned using evaluation results — it is not hard-coded guesswork.
- No evaluation or LLM-judge call happens on this path.

## 3a. Implemented backend flows (Stage 2)

**Ingestion — `POST /ingest` (multipart `file`)**
1. Sanitize the filename; check extension (`.pdf`/`.txt`), size (`MAX_UPLOAD_SIZE_MB`, read at most limit + 1 byte), PDF signature / no binary in TXT.
2. Extract text: pypdf page by page (1-based page numbers, blank pages skipped; no text at all → rejected as scanned/image-only) or UTF-8 TXT (page = null). PDF pages are rebuilt from positioned text runs into regions separated by blank lines, with table rows on one line (`cell | cell`) and bullets on their own line; a cell opens only after a measured horizontal gap (character width estimated per page from its own runs), never inside a word or after a list marker, and spaces inferred by pypdf are kept; rotated pages, unusable positions, errors, a result keeping < 90 % of the plain text's characters, or cells that look like word fragments fall back to plain extraction (D-063, D-064).
3. Chunk each page separately with the embedding model's tokenizer: whole regions packed up to `CHUNK_SIZE_TOKENS` (180); a longer region is split into windows advancing by size − `CHUNK_OVERLAP_TOKENS` (30); short heading-like regions attach forward, other short regions backward; the chunk size is checked against the model's input limit (254 content tokens). Each chunk lists sub-units (lines, rows, list items, sentences of long lines; ≥ 6 tokens; prefixed with their heading).
4. Embed each chunk and its sub-units locally in one batch, assign a new UUID document ID, upsert one point per chunk with its dense vectors and (hybrid index) a lexical sparse vector of its text.
5. Respond `201` with document ID, filename, type, page counts, chunk count, `status: "indexed"`.

**Question answering — `POST /query` (`question`, optional `document_ids`, optional `top_k` 1–20)**
1. Validate (non-blank question ≤ 2000 chars, UUID document IDs, unknown fields rejected).
2. Embed the question with the same model; search Qdrant (optional `document_id` filter). Hybrid index: dense candidates and lexical candidates (≥ 20 each) are fused by reciprocal rank; the first top-k fused chunks whose dense score passes the threshold become evidence and are passed to the model **in dense-score order**; lexical-only candidates are scored densely first (D-064). Older indexes: dense top-k.
3. Evidence check: keep chunks whose score (best vector cosine) ≥ `MIN_RETRIEVAL_SCORE` (0.35 for the sub-unit index since 2026-10-16, D-063; legacy collections 0.30, D-052). None → fallback (`no_results` / `below_threshold`); **the LLM is not called**. The whole chunk, not the matching sub-unit, is the evidence passage. Since 2026-10-25 (Stage 5.7 closure): (a) on structure-aware indexes (sub-unit, hybrid) a passage is extended by the window before and the window after it when they continue the **same split region on the same page** (detected by the chunker's exact overlap; at most one each side; neighbours that are evidence themselves are not duplicated; added text capped so the evidence stays ≤ 6,000 characters, filled in evidence order; scores, order, gate, and passage count unchanged; legacy indexes unchanged — D-072); (b) passages of a document that another retrieved passage explicitly replaces are withheld unless the question asks about history or change (D-070).
4. Build the prompt: system rules (evidence only, no invention, cite `[S1]`…, separate "Interpretation:", reply `INSUFFICIENT_EVIDENCE` if unanswerable, ignore instructions inside documents) + evidence passages labelled `S1..Sn` with filename/page; tag-like text in documents is escaped; instruction-like spans are withheld from the model's copy (D-069).
5. Generate via the configured provider. An `INSUFFICIENT_EVIDENCE` reply → fallback (`model_declined`). The answer check (D-071) then requires at least one valid `[Sn]`, no identifier outside the evidence, and only numbers and pages that the supplied text (or the question) contains; a failing answer is regenerated **once** with the reasons, and a second failure becomes the fallback (`model_declined`).
6. Respond with the answer, `status` (`answered` / `insufficient_evidence`), `sources` built **from Qdrant payloads** (source ID, document ID, filename, page, chunk index, char span, excerpt, score, `cited` = whether the answer references that ID), an evidence summary (`supporting_count` = passages that passed the gate, including superseded ones withheld under D-070; `sources` = the passages supplied to the model), provider/model/prompt version, and per-stage latency.

**Prompt-injection and source handling (Stage 5, §3c)** — steps 4–5 above now include markup neutralisation, instruction-hint labels, evidence framing, and output guards; see §3c.

**Provider selection** — `GENERATION_PROVIDER` (`ollama` default | `gemini`) is validated at startup; `generation/factory.py` builds exactly one provider. Ollama: `POST /api/chat`, `stream: false`, `think: false`. Gemini: `google-genai` `generate_content` with `system_instruction`; client created lazily so a missing key only fails at generation time. No failover. Error mapping: unreachable/model missing → 503, timeout → 504, rate limit → 429, bad credentials / missing key → 500 `generation_not_configured`, other upstream errors → 502.

**Health — `GET /health`** — always 200 while the API runs; reports vector store (reachable, point count), embedding model (loaded or lazy), and generation readiness (Ollama: `/api/tags` lookup for the model, no generation; Gemini: key present or not, no network call). Overall `status` is `degraded` when the store or generation is not ready.

## 3b. Frontend ↔ backend interactions (Stage 3)

| UI action | Request | UI result |
| --- | --- | --- |
| App load, every 30 s, "check again" | `GET /health` | Top-bar status (connected / generation unavailable / vector store unavailable / unreachable), model and collection names, upload limit (`config.max_upload_size_mb`) |
| Workspace load, after upload/delete, "reload" | `GET /documents` | Document list with type, pages, chunks, indexed time |
| Choose or drop a file | `POST /ingest` (multipart `file`) | "Indexed · N chunks" only after `201`; otherwise the backend's error message and code. Unsupported, empty, or oversized files are rejected in the browser first (the backend still validates) |
| Remove → confirm | `DELETE /documents/{id}` | List re-fetched from the server |
| Ask (Enter) | `POST /query` (`question`, optional `document_ids`) | Answer with citation markers, cited sources, timing strip; or the fallback panel; or a failed-request alert with retry |
| Trace this answer | none (uses the `/query` response and the current `GET /documents` list) | Evidence Trace |
| Open Evaluation (Stage 5.5) | `GET /evaluations`, then `GET /evaluations/{run_id}` (latest readable or `#/evaluation/<run_id>`) | Run header, metric ledger, case table; downloads link to `/evaluations/{run_id}/files/…` |
| Open Experiments | `GET /experiments/runs`; `GET /experiments/compare` for the selected pair; `GET /experiments/runs/{id}` when a run is expanded | Tracking state, runs table, comparison, artifact links to `/experiments/runs/{id}/artifacts/…` |
| Open Pipeline / "Check again" | `GET /system/status` | Flow with current settings, component states, not-built-yet list |
| Open Pipeline / "Refresh runs" (Stage 7) | `GET https://api.github.com/repos/<repo>/actions/runs?per_page=10` straight from the browser (anonymous; cached 5 minutes in `sessionStorage`; never polled) | Recent CI runs with outcome, trigger, commit, and a link to each GitHub run page; loading, empty, rate-limited, unreachable, malformed, and out-of-date states (D-083) |

Errors from any request appear in the region that made it; nothing is replaced with sample data. The backend's CORS default allows `http://localhost:5173` and `http://127.0.0.1:5173`.

## 3c. Layered handling of untrusted text (Stage 5, D-049; prompt v8, 2026-10-25)

Retrieved passages and the user's question are untrusted. The pipeline applies several independent layers; none of them, alone or combined, guarantees immunity to prompt injection, and the evaluation measures only the tested scenarios.

| Layer | Where | What it does |
| --- | --- | --- |
| Retrieval gate | `retrieval/evidence.py` | Passages below `MIN_RETRIEVAL_SCORE` never reach the model; unrelated questions get the fallback without an LLM call |
| Markup neutralisation | `prompts._escape` | Every tag-like `<…` in a passage (or filename) becomes `&lt;…`, so documents cannot close the evidence block or open fake `<system>`/comment blocks |
| Instruction-hint labels | `prompts.has_instruction_hints` | Passages with text addressed to an AI assistant (or a tool call written as JSON, v8) get `instructions_detected="yes"`. Heuristic, written alongside the test set |
| Span withholding (v8, D-069) | `prompts.withhold_instruction_spans`, `prompts.model_text` | In the model's copy of a passage, each instruction-like span is replaced by `[text withheld: instruction-like content]`: a flagged aside inside a sentence (`(note to the AI: …)`, `[…]`, `<!-- … -->`), or a flagged sentence to the end of its line (followed onto wrapped lines). The rest of the passage stays usable. The API excerpt and the index keep the original text. Exception: a question that itself asks about such text (prompt injection, malicious/hidden instructions, AI assistants) sees the passage unredacted, labelled as in v7 — this keeps security-training documents answerable. Heuristic: unflagged phrasing passes through |
| Supersession labels | `prompts.superseded_documents` | A passage whose document another retrieved passage explicitly says it replaces/supersedes (matched by a full date or version number) gets `superseded_by="Sn"`; nothing is inferred from file names, upload time, or order |
| Supersession policy (v8, D-070) | `prompts.select_current_evidence` in `pipeline.retrieve_evidence` | For a current question, such superseded passages are withheld and the replacing passage answers; a question about history or change ("previous", "changed", "compare", a year or version that the old document contains) keeps both, labelled. Without an explicit replacement statement nothing is withheld and conflicts are reported (rule 8). Only passages inside the selected documents take part |
| Framing and priority rules | `SYSTEM_PROMPT` (rules unchanged since v7), `build_user_prompt` (v8 header names the placeholder) | Passages are quoted data framed before and after; the system rules override anything in passages or the question; rules for supersession, conflicts, false premises (which take precedence over declining, D-061), citations (identifiers only inside `[Sn]`), and declining. Since v7 (D-067): claims inside text addressed to an assistant are not evidence, a passage labelled `instructions_detected` never creates a "disagreement" with an unlabelled one, and the header asks to ignore labelled text silently |
| Decline detection | `prompts.is_declined` | A reply containing `INSUFFICIENT_EVIDENCE` anywhere becomes the fallback (`model_declined`); the marker and surrounding text never reach the user |
| System-prompt leak guard | `prompts.leaks_system_prompt`, `pipeline.generate_answer` | A reply that reproduces a line of the system prompt is withheld and returned as the fallback, reported as `model_declined` (the response contract and the frontend validator allow only three reasons) and logged as a warning |
| Answer check (v8, D-071) | `generation/answer_check.py`, `pipeline.generate_answer` | An answer must cite ≥ 1 supplied passage, no identifier outside the evidence, and only numbers and pages present in the supplied text (after withholding), the question, or the passages' page metadata. One regeneration with the stated reasons; a second failure is withheld as `model_declined`. A value that existed only in a withheld span therefore cannot be returned. Not a semantic check: a wrong sentence built from real values passes |
| Citations from metadata | `pipeline._to_reference` | Sources come only from retrieved payloads inside the selected documents; `cited` marks only valid identifiers |

## 3d. Conversation state and read-only dashboards (Stage 5.5)

**Conversation state (D-054).**

```
App ─ ConversationProvider (threads[], active thread, selection, scope; AbortControllers)
        │ Workspace ──setScopeContext({signature, scope, label})──▶ switch to the latest thread of
        │             that context, or a new one (signature = selected IDs, or all indexed IDs)
        │ ask(question) ──▶ thread of the CURRENT context ──▶ POST /query {question, document_ids?}
        │               ──▶ update that turn, in its own thread (done / failed)  ← continues while another view is shown
        │ every change ──▶ sessionStorage "ragguard.conversation.v2" (threads; ≤ 50 turns each)
        │ app start   ◀── restore threads + the active thread's selection (pending → failed "interrupted");
        │                 a v1 conversation becomes an "Earlier conversation" thread
        └ Workspace / TurnView / EvidencePanel read the active thread via useConversation()
```

Views mount and unmount on navigation; the provider does not, so nothing is lost or re-requested. Conversations are separated by document context (D-065): an upload or removal changes the "all documents" context, another selection is another context; earlier threads stay in the selector and open as history. "Clear conversation" aborts that thread's in-flight requests and deletes only that thread. No conversation history is sent to the backend; each `/query` is independent.

**Retrieval diagnostics (D-066).** With `RETRIEVAL_DIAGNOSTICS=true`, `POST /diagnostics/query` runs `retrieve_evidence` twice (exact `/query` evidence, and a wider candidate list) and optionally the provider on the same prompt; it returns candidates, decision, prompt size, and the raw reply (withheld if it reproduces the system prompt). Not registered otherwise.

**Evaluation reports (D-055).** `ReportStore` lists the directories directly inside `EVALUATION_RESULTS_DIR` (pattern-checked names, no symlinks), reads `report.json`, and builds typed views (`schemas/evaluations.py`). Metrics come from `catalog.CATALOG` by JSON path; a missing path is `available: false`, never 0. Per-case findings are derived from the recorded deterministic checks (errors, false refusal/answer, missing facts, unsupported content, attack success, canary leak, invalid/superseded/unsupported citations, uncited facts, retrieval miss, judge error/flag). Files are served as attachments with repository and home paths redacted. Nothing runs an evaluation.

**MLflow runs (D-056).** `TrackingReader` uses the CLI's tracking configuration. On first use it imports MLflow (`dependency_missing` if absent); a missing local SQLite file is `no_store` and is not opened. It searches the configured experiment only, returns whitelisted tags, the logged parameters, and catalog metrics (`<key>` and `<key>.denominator`), lists and downloads only `reports/report.json|report.md|failures.json` into a temporary directory, and compares two runs (`compare_runs`) with comparability rules. It never writes. The query path (`/query`, `/ingest`, `/documents`, `/health`) does not touch it.

**System status (D-057).** `build_status` calls `RAGPipeline.health()` (vector store count, embedding loaded flag, provider readiness via Ollama `/api/tags` — no generation), validates the dataset (cached), lists reports, and reads the tracking status; Docker and CI are `not_implemented`. The Pipeline view's diagram is static code-path description filled with `/system/status` configuration; it shows no executions because none are recorded.

## 3e. Docker Compose deployment (Stage 6, D-075–D-078)

Two ways to run the same code: the **host flow** (development: `uvicorn` on 8000, Vite on 5173, embedded Qdrant in `qdrant_storage/`, Ollama on `localhost:11434`) and the **Compose flow** below. They use separate data; nothing from the host is mounted into a container. Operating guide: [`deployment/README.md`](../deployment/README.md).

```
 browser ── http://127.0.0.1:8080 ──▶ frontend  Nginx (uid 101): static production build
                                          │       + proxy of /health /ingest /documents /query
                                          │         /evaluations /experiments /system   (same origin)
                                          ▼  http://backend:8000   (Docker DNS, resolved per request)
                                      backend   FastAPI/uvicorn (uid 10001), RAGGUARD_RUNTIME=docker
                                          ├─▶ qdrant   http://qdrant:6333  server mode (QDRANT_URL), uid 1000
                                          ├─▶ Ollama   http://host.docker.internal:11434  (on the HOST)
                                          └─▶ volumes: hf_cache, mlflow (db + artifacts), reports
 one-off:  docker compose run --rm backend python -m app.evaluation.run_evaluation …
           (embedded temporary Qdrant inside that container; the server is never used)
```

- **Browser ↔ API.** The bundle is built with an empty `VITE_API_BASE_URL`, so the client calls its own origin (`client.ts` keeps `""`); Nginx forwards only the route prefixes above. No CORS is involved; download links are relative. Proxy timeouts (330 s) exceed the UI's limits (query 200 s, upload 300 s); Nginx-made failures answer in the API's error shape (`backend_unavailable`, `backend_timeout`). In host development the client keeps its `http://localhost:8000` default.
- **Backend ↔ Qdrant.** `QDRANT_URL=http://qdrant:6333` selects the supported server mode (`is_local = not qdrant_url`); the collection format is the hybrid index created by the code itself. Qdrant is not published to the host. Retrieval quality is unchanged for dense scores; lexical tie-ordering can differ from the embedded store (D-078).
- **Backend ↔ Ollama.** `OLLAMA_BASE_URL` is set from `DOCKER_OLLAMA_BASE_URL` (default `host.docker.internal:11434`); readiness is the existing `/api/tags` check, shown in `/health` and the UI. A missing Ollama or model never makes the container unhealthy — it is reported (`degraded`, `generation_unavailable`, `model_missing`).
- **Embedding model.** Loaded lazily on first ingest or query from the `hf_cache` volume (`HF_HOME`); first use downloads ≈ 90 MB; `HF_HUB_OFFLINE=1` afterwards.
- **MLflow and reports.** `MLFLOW_TRACKING_URI=sqlite:////data/mlflow/mlflow.db` and `MLFLOW_ARTIFACT_ROOT=/data/mlflow/artifacts` share one volume; the API still only reads them (`no_store` until the first tracked evaluation run); `EVALUATION_RESULTS_DIR=/data/reports` is written by the CLI and read by the API. The datasets are inside the image (`/app/evaluation/datasets`; `config.REPO_ROOT` is `/app`).
- **Health.** backend: `GET /health` → 200 (process alive; dependency state in the body); web: `/healthz`; Qdrant: `/readyz`. `depends_on: service_healthy` orders start-up.
- **Hardening.** Non-root users, read-only code, `cap_drop: ALL`, `no-new-privileges`, loopback-only host port, no secrets or data in images (D-077).
- **`/system/status`.** The `containers` component is `healthy` inside this deployment (set by `RAGGUARD_RUNTIME=docker`) and `configured` on the host; `ci` is `configured` since Stage 7 (a workflow exists; the API does not query GitHub).

Not provided: TLS, authentication, scaling or failover, a registry or deployment pipeline (CI only builds the images, §5; U-020).

## 4. Evaluation path

```
Fixed dataset (version-controlled)
   │  question, reference answer, expected sources
   ▼
Index the dataset's source documents (same ingestion pipeline)
   │
   ▼
Run each question through the same retrieval + generation pipeline
   │
   ▼
Compute metrics per case and in aggregate
   ├─ Retrieval success   — were the expected sources retrieved (e.g. hit/recall at k)
   ├─ Answer correctness  — comparison against the reference answer
   ├─ Groundedness        — are answer claims supported by retrieved/cited evidence
   ├─ Fallback behaviour  — does it decline when the answer is not in the documents
   └─ Latency             — per-stage and end-to-end timing
   │
   ▼
Results file (git-ignored) + MLflow run with configuration and dataset version
   │
   ▼
Compare against version-controlled thresholds ─▶ pass / fail
```

- The LLM judge supplements deterministic checks (source matching, reference comparison); its scores are recorded with the judge model and prompt version and are not treated as ground truth.
- Thresholds are defined only after a baseline has been measured (D-012).
- Metric definitions are fixed in D-043 and written into every report. MLflow is implemented (Stage 5). The threshold comparison used as a CI gate is the separate, offline, model-free `quality_gate` (Stage 7, §5): it reuses the same retrieval code but never calls generation or the judge.

## 4a. Implemented evaluation flow (Stage 4)

```
python -m app.evaluation.run_evaluation  (backend/, sequential)
   │
   ├─ load + validate dataset.json and corpus/  ──▶ invalid: exit 2, nothing runs
   │    (schema, labels, IDs, sources exist, facts occur in sources; SHA-256 fingerprint)
   │
   ├─ isolated_store(): new temp dir ─▶ embedded Qdrant, collection ragguard_eval_<run_id>
   │    (QDRANT_URL / QDRANT_LOCAL_PATH / configured collection never opened)
   │
   ├─ RAGPipeline(eval settings, embedder, temp store, configured provider)
   │    └─ ingest() every corpus file once  ──▶ failure: report status "failed"
   │
   ├─ for each case:  retrieve_evidence()  ──▶  all top-k chunks + scores (also below threshold)
   │                  generate_answer()    ──▶  answer | fallback (+ reason) | error (recorded)
   │                  deterministic checks (retrieval, citations, facts, diagnostics,
                    attacks incl. whether the payload reached the evidence, D-060)
   │                  judge (answered cases only, local Ollama, optional)
   │
   ├─ close store, delete temp dir (finally; also on errors)
   │
   ├─ aggregates (D-043, D-050) + offline threshold sweep from recorded max scores
   │
   ├─ evaluation/results/<run_id>/report.json  ──▶ re-validated
   │  evaluation/results/<run_id>/report.md    ──▶ re-rendered from the JSON and compared
   │
   └─ MLflow run in experiment ragguard-evaluation (unless --no-tracking; D-051)
```

- **Scoring is separate from execution (Stage 5).** `run_case` records the outcome, answer, retrieved passages, latency, and judge result; `score_case` derives every deterministic check from those records. `--rescore report.json` re-applies the current evaluator to a saved schema-2 report of the same dataset (fingerprint checked) without model calls, so runs scored by different evaluator versions can be made comparable.

- **Same pipeline, no duplicate logic.** The runner uses the production ingestion, chunking, embedder, `QdrantVectorStore`, evidence rule, prompt, provider, citation mapping, and fallback. `retrieve_evidence` / `generate_answer` are the two halves of `answer()`, exposed so the runner can record every retrieved score and keep retrieval data when generation fails (D-041).
- **Isolation from the live user-data store.** Each run has its own temporary embedded Qdrant directory, so the API (and the developer's `qdrant_storage/`) can keep running; embedded Qdrant's one-process-per-folder lock is never contended. Nothing persists after the run (D-042).
- **Judge.** A second `OllamaProvider` instance (temperature 0, seed, JSON-schema format) built from the same settings; it never replaces deterministic metrics and is not weighted into them (D-044).
- **Run status.** `completed`, `partial` (some case or judge errors, each recorded), or `failed`; CLI exit code 0/1/2. Status describes execution, not quality.

## 5. Release path (implemented in Stage 7, D-079–D-084)

```
pull request to main / push to main / manual run          (no path filters; no secrets)
   │
   ├─ backend-checks      Python 3.13, CPU PyTorch; ruff, ruff format, mypy, pytest
   │                       (0 failures, 0 skipped, exactly 1 strict xfail; no data left behind)
   ├─ frontend-checks     npm ci; typecheck, lint, vitest, build
   └─ dataset-validation  --validate-only per dataset; versions/fingerprints vs the gate file
            │
            ▼
        quality-gate      offline: real embedding model, no generation model, no Ollama/Gemini
            │              measures retrieval, evidence, abstention, injection exposure,
            │              supersession against evaluation/quality_gate.json (fails closed)
            ▼
   ┌── image-build        needs: ALL four jobs, no `if`/`always()`
   │                       docker compose config -q; build backend + frontend images (push: false)
   │                       checks on the images; NO registry, NO deployment
   ▼
   ci-result (always)     reports every job and whether image-build was eligible; fails unless
                          all five succeeded  → the one status to require in branch protection
```

- **Dependencies.** `image-build` lists every check and the gate in `needs` and has no condition, so a failed, cancelled, or skipped prerequisite skips it. `tests/test_ci_workflow.py` asserts this and simulates the graph. A failed gate therefore blocks the build, and nothing downstream exists to publish.
- **The gate (D-079).** `python -m app.evaluation.quality_gate run` ingests each gated dataset into a temporary hybrid index, calls `RAGPipeline.ingest` / `retrieve_evidence`, `check_retrieval`, and `model_text`, and compares counts of questions with the thresholds in `evaluation/quality_gate.json` (D-081). It records the commit, the dataset versions and fingerprints, and the configuration it ran with, and refuses to pass if any of them differs from the file, if a metric is missing or has a changed denominator, or if the measurement is stale. Security metrics are separate checks with zero tolerance. The LLM judge and the full model-based benchmark are intentionally not part of it (reported as "not run").
- **Reporting.** Each job writes to the workflow step summary; the gate adds a Markdown table (metric, measured, threshold, result, failure reasons, what was not run) and uploads `gate_report.json` / `gate_summary.md` (case IDs and numbers only, never passage text) as an artifact.
- **Security of the workflow.** `pull_request` only (never `pull_request_target`), `contents: read`, no secrets, actions pinned to verified commit SHAs, fork pull requests run the same jobs without credentials (D-084).
- **A blocked release does not affect the running deployment.** CI never deploys; the Stage 6 deployment on a developer's machine is untouched by any run. Publishing images or deploying needs a registry and target the owner has not chosen (U-020).
- **CI status in the UI.** The Pipeline view reads the repository's runs from GitHub's public API in the browser (§3b, D-083); the RAGGuard API does not know about GitHub, and the Nginx Content-Security-Policy allows `https://api.github.com` for this.
- The CI gate runs once per qualifying code change, never per user question, and shares retrieval code with the live path.
- **Verified so far:** the same commands locally; the workflow's structure by tests and `actionlint`. **Not yet observed:** a run on GitHub (it needs a push).

## 6. Cross-cutting concerns

- **Configuration:** environment variables loaded via typed settings; `.env.example` documents them with placeholders only.
- **Security:** secrets only in environment/CI secrets; upload validation (type, size); no secrets in the frontend bundle; CORS restricted to configured origins.
- **Observability:** structured logging and per-stage latency recorded with each response. Advanced monitoring is an optional extension.
- **Testing:** unit tests for ingestion/chunking/retrieval logic with fakes for external providers; API tests via httpx (FastAPI `TestClient`) with a fake embedder and fake LLM, each test on its own temporary Qdrant directory and collection; real-model embedding tests run when the model is cached; a real-Ollama test is opt-in (`pytest -m ollama`); evaluation suite as a separate, slower check.

## 7. Optional extensions (not initial requirements)

Kubernetes deployment, canary releases, and advanced monitoring/alerting. These may be added after Stage 8 if documented in `DECISIONS.md`.
