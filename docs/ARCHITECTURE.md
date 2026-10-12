# RAGGuard — Architecture

> Status as of Stage 3 (2026-10-13): the **backend RAG pipeline and API** (sections 2 "Backend API", 3, 3a) and the **frontend workspace** (sections 2 "Frontend", 3b) are implemented. Evaluation, MLflow, Docker, and CI remain proposed. Decisions referenced as `D-xxx` are in [`DECISIONS.md`](DECISIONS.md).

## 1. System overview

RAGGuard has three distinct flows that share one RAG pipeline implementation:

| Flow | Trigger | Purpose | Runs where |
| --- | --- | --- | --- |
| Live query path | A user asks a question | Answer from indexed documents with citations | Running backend service |
| Evaluation path | A developer or CI job runs the evaluation suite | Measure pipeline quality on a fixed dataset | Locally or in CI |
| Release path | A code change (push / pull request, as configured) | Decide whether a change may be built and released | GitHub Actions |

The same retrieval and generation code serves both live queries and evaluation, so the evaluation measures what users actually get.

## 2. Components and responsibilities

### Frontend (`frontend/`) — implemented in Stage 3
React + TypeScript + Vite + Tailwind CSS single-page application. Talks to the backend only through its HTTP API and holds no secrets; the only build-time variable is the public `VITE_API_BASE_URL`.

| Path | Responsibility |
| --- | --- |
| `src/main.tsx`, `src/app/` | Entry point; `App` (shell, hash routing via `useRoute`, theme), `Shell` (nav rail, top bar, backend status), `Workspace` (three-column composition), `PlannedView` (honest placeholders for Evaluation/Experiments/Pipeline), `useHealth` (polls `GET /health` every 30 s) |
| `src/lib/api/` | The only HTTP code: `client.ts` (base URL, timeouts, error normalisation), `endpoints.ts` (one function per endpoint), `guards.ts` (runtime response validation) |
| `src/lib/` | `format.ts` (display formatting), `browser.ts` (media queries, storage, WebGL detection, theme, token colours) |
| `src/types/api.ts` | Types mirroring the backend Pydantic schemas |
| `src/components/ui/` | Primitives: `Button`, `StatusTag`, `InlineAlert` |
| `src/features/documents/` | `useDocuments` / `useUpload` (state), `UploadZone`, `DocumentList` (scope checkboxes, confirmed removal) |
| `src/features/chat/` | `useConversation` (in-memory thread), `QuestionInput`, `TurnView` (answer / fallback / failure), `AnswerText` + `parseAnswer` (paragraphs, lists, citation markers), `EvidencePanel` |
| `src/features/chat/trace/` | Evidence Trace: `traceModel` (from real response + document list), `layout` (shared geometry), `TraceScene3D` (lazy, R3F), `TraceDiagram2D` (SVG fallback), `SceneView` (renderer choice, lazy loading, error boundary), `EvidenceTrace`, `FirstRunIllustration` |
| `src/styles/` | `tokens.css` (design tokens, both themes), `index.css` (fonts, Tailwind theme binding, base styles) |
| `src/test/` | Vitest + React Testing Library tests with a mocked HTTP layer |
| `features/evaluation/`, `features/experiments/` | Reserved, empty until Stages 4–5 |

### Backend API (`backend/app/`) — implemented in Stage 2
FastAPI service with Pydantic schemas.

| Module | Responsibility |
| --- | --- |
| `main.py` | Application factory (`create_app`), lifespan (builds the pipeline), CORS, JSON error handlers, router registration |
| `pipeline.py` | `RAGPipeline`: the single orchestration of ingestion, question answering, listing, deletion, and health — shared by the API and (Stage 4) the evaluation runner (D-028) |
| `api/routes/` | Thin HTTP handlers: `documents.py` (`POST /ingest`, `GET /documents`, `DELETE /documents/{id}`), `query.py` (`POST /query`), `health.py` (`GET /health`); `api/dependencies.py` injects the pipeline |
| `core/` | `config.py` (pydantic-settings `Settings`), `errors.py` (error hierarchy with HTTP status + code), `logging.py` |
| `schemas/` | Pydantic request/response models — the API contract with the frontend |
| `ingestion/` | `validation.py` (extension, size, signature), `extraction.py` (pypdf per page / UTF-8 TXT), `chunking.py` (token-aware overlapping chunks, page-bounded) |
| `embeddings/` | `base.py` (`Embedder` protocol incl. tokenizer spans), `sentence_transformer.py` (lazy-loaded local MiniLM) |
| `retrieval/` | `vector_store.py` (Qdrant client modes, collection checks, upsert, filtered search, listing, deletion), `evidence.py` (sufficiency rule) |
| `generation/` | `base.py` (`GenerationProvider` protocol), `ollama.py`, `gemini.py`, `factory.py` (provider selection), `prompts.py` (system prompt, evidence formatting, citation parsing, fallback text) |
| `evaluation/` | Metric computations reused by the evaluation runner (Stage 4; empty) |
| `tracking/` | MLflow logging helpers (Stage 5; empty) |

Provider-specific code (embedding model, LLM provider) sits behind small interfaces so it can be swapped and so tests can use fakes. Retrieval, prompt construction, and source references are provider-independent; providers only turn a system prompt + user prompt into text.

### Vector store — Qdrant
Stores one point per chunk: the 384-dimensional normalized embedding plus payload (document ID, filename, file type, total pages, page number or null, chunk index, chunk text, character span, token count, embedding model, ingestion time). Point IDs are UUIDv5 of `document_id:chunk_index`. Distance is COSINE. In development the embedded client runs in **local persistent mode** (`QDRANT_LOCAL_PATH`); setting `QDRANT_URL` switches to a Qdrant server (D-027). The collection is created on first ingest, and its vector size/distance are validated against the embedding model.

### Evaluation (`evaluation/`, `backend/app/evaluation/`)
- `evaluation/datasets/`: fixed, version-controlled dataset of questions, reference answers, and expected supporting sources, along with the source documents they reference (or instructions for obtaining them).
- An evaluation runner (Stage 4) executes the dataset through the pipeline and computes metrics.
- Generated results are written to an ignored output directory and, from Stage 5, logged to MLflow.

### Experiment tracking — MLflow
Records each evaluation run: pipeline configuration (chunk size/overlap, top-k, embedding model, LLM model, prompt version), dataset version, metrics, and artifacts (per-case results). Enables comparison between configurations.

### CI/CD — GitHub Actions (`.github/workflows/`)
Runs API tests and the evaluation suite on configured events, enforces quality thresholds, and only then builds images and proceeds to release stages.

### Packaging — Docker / Docker Compose (`deployment/`, Stage 6)
Containers for backend, frontend, and Qdrant (and MLflow if self-hosted), orchestrated locally with Docker Compose.

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
2. Extract text: pypdf page by page (1-based page numbers, blank pages skipped; no text at all → rejected as scanned/image-only) or UTF-8 TXT (page = null).
3. Chunk each page separately with the embedding model's tokenizer: windows of `CHUNK_SIZE_TOKENS` (180) advancing by size − `CHUNK_OVERLAP_TOKENS` (30); the chunk size is checked against the model's input limit (254 content tokens).
4. Embed chunks locally (normalized vectors), assign a new UUID document ID, upsert one point per chunk.
5. Respond `201` with document ID, filename, type, page counts, chunk count, `status: "indexed"`.

**Question answering — `POST /query` (`question`, optional `document_ids`, optional `top_k` 1–20)**
1. Validate (non-blank question ≤ 2000 chars, UUID document IDs, unknown fields rejected).
2. Embed the question with the same model; search Qdrant (top-k, optional `document_id` filter).
3. Evidence check: keep chunks with cosine ≥ `MIN_RETRIEVAL_SCORE` (0.35). None → fallback (`no_results` / `below_threshold`); **the LLM is not called**.
4. Build the prompt: system rules (evidence only, no invention, cite `[S1]`…, separate "Interpretation:", reply `INSUFFICIENT_EVIDENCE` if unanswerable, ignore instructions inside documents) + evidence passages labelled `S1..Sn` with filename/page; tag-like text in documents is escaped.
5. Generate via the configured provider. An `INSUFFICIENT_EVIDENCE` reply → fallback (`model_declined`).
6. Respond with the answer, `status` (`answered` / `insufficient_evidence`), `sources` built **from Qdrant payloads** (source ID, document ID, filename, page, chunk index, char span, excerpt, score, `cited` = whether the answer references that ID), an evidence summary, provider/model/prompt version, and per-stage latency.

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

Errors from any request appear in the region that made it; nothing is replaced with sample data. The backend's CORS default allows `http://localhost:5173` and `http://127.0.0.1:5173`.

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
- Exact metric definitions are finalized in Stage 4.

## 5. Release path

```
Code change (push / pull request, as configured)
   │
   ▼
GitHub Actions
   ├─ Install, lint/type-check (as configured)
   ├─ API tests (pytest + httpx)
   └─ Evaluation suite against the fixed dataset
         │
         ▼
   Quality gate: metrics vs thresholds
         │                     │
        pass                  fail
         │                     │
         ▼                     ▼
   Build images          Workflow fails; build/release
   → later release       jobs do not run; results are
     stages              reported on the run
```

- Release jobs depend on the gate job, so a failed gate prevents image build and release.
- **A blocked release does not affect the running deployment.** The currently deployed, previously validated version keeps serving users; the gate only stops the candidate from replacing it.
- The CI evaluation runs once per qualifying code change, not per user question.
- How CI obtains LLM/embedding access (secrets, cost limits, or a deterministic test mode) is an unresolved decision for Stage 7.

## 6. Cross-cutting concerns

- **Configuration:** environment variables loaded via typed settings; `.env.example` documents them with placeholders only.
- **Security:** secrets only in environment/CI secrets; upload validation (type, size); no secrets in the frontend bundle; CORS restricted to configured origins.
- **Observability:** structured logging and per-stage latency recorded with each response. Advanced monitoring is an optional extension.
- **Testing:** unit tests for ingestion/chunking/retrieval logic with fakes for external providers; API tests via httpx (FastAPI `TestClient`) with a fake embedder and fake LLM, each test on its own temporary Qdrant directory and collection; real-model embedding tests run when the model is cached; a real-Ollama test is opt-in (`pytest -m ollama`); evaluation suite as a separate, slower check.

## 7. Optional extensions (not initial requirements)

Kubernetes deployment, canary releases, and advanced monitoring/alerting. These may be added after Stage 8 if documented in `DECISIONS.md`.
