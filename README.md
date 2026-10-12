# RAGGuard

> **Status: under development.** Stages 1–3 are complete: the backend ingests PDF/TXT files, answers questions with cited sources through a local LLM, and falls back safely when evidence is insufficient; the web frontend provides the document workspace, cited evidence, and the Evidence Trace. There is no evaluation suite, experiment tracking, or CI gate yet. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the authoritative stage status.

RAGGuard is a quality-gated Retrieval-Augmented Generation (RAG) application. Upload PDF or TXT documents, ask questions about them, and get answers grounded in retrieved evidence, with references to the source document and page.

What sets it apart is the release discipline around it: an automated evaluation suite measures retrieval and answer quality against a fixed, version-controlled dataset, and a CI/CD quality gate blocks a release when those measurements fall below documented requirements.

## Core features

Document ingestion, evidence-based answers, safe fallback (Stage 2), and the document workspace interface (Stage 3) are implemented; evaluation, tracking, and CI are planned.

- **Document ingestion** — PDF and TXT upload, text extraction, overlapping chunking, embedding, and storage in Qdrant.
- **Evidence-based answers** — retrieval of relevant passages, LLM answer generation constrained to that evidence, and source references (document, page where available).
- **Safe fallback** — an explicit "not enough evidence" response instead of an unsupported answer.
- **Offline evaluation** — a fixed dataset of questions, reference answers, and expected sources; metrics for retrieval success, answer correctness, groundedness, and latency. An LLM judge is used as a supplementary signal only.
- **Experiment tracking** — MLflow records evaluation runs, model/prompt configuration, parameters, metrics, and artifacts for comparison.
- **Quality-gated CI/CD** — GitHub Actions runs API tests and the evaluation suite; a failed gate prevents image build and release.
- **Purpose-built interface** — document workspace with cited evidence and an Evidence Trace (implemented); evaluation dashboard, experiment comparison, and pipeline status views (planned; shown as "planned" with no data until then).

## High-level architecture

```
                    ┌──────────────────────── Live query path ────────────────────────┐
  React frontend ──▶│ FastAPI ─▶ retrieval (Qdrant) ─▶ generation (LLM) ─▶ cited answer │
                    └─────────────────────────────────────────────────────────────────┘
                    ┌──────────────────────── Evaluation path ────────────────────────┐
  fixed dataset ───▶│ same RAG pipeline ─▶ metrics ─▶ results + MLflow run            │
                    └─────────────────────────────────────────────────────────────────┘
                    ┌───────────────────────── Release path ──────────────────────────┐
  code change ─────▶│ GitHub Actions ─▶ tests + evaluation gate ─▶ image build/release │
                    └─────────────────────────────────────────────────────────────────┘
```

The evaluation suite evaluates proposed application changes; it does not run on every user query. A blocked release leaves the currently deployed version running. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Technology stack

| Area | Technology |
| --- | --- |
| Frontend | React 19, TypeScript 6 (strict), Vite 8, Tailwind CSS 4, Lucide icons, three.js + React Three Fiber (Evidence Trace only), Vitest + React Testing Library |
| Backend | Python 3.13, FastAPI, Pydantic, pydantic-settings, pypdf |
| Vector store | Qdrant (embedded local mode for development, or a server via `QDRANT_URL`) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, local |
| LLM | Ollama `qwen3.5:9b`, local (default); Google Gemini via `google-genai` (optional) |
| Evaluation | Python evaluation scripts, pytest, httpx, fixed version-controlled dataset |
| Tracking | MLflow |
| DevOps | Docker, Docker Compose, GitHub Actions, Git |

Unresolved choices (evaluation dataset, quality thresholds, deployment target) are tracked in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Implementation stages

1. Project foundation and documentation
2. Backend RAG pipeline and API
3. Frontend application and backend integration
4. Evaluation dataset, metrics, and evaluation runner
5. MLflow experiment tracking and result comparison
6. Docker and Docker Compose integration
7. GitHub Actions testing and automated quality gate
8. End-to-end integration, verification, documentation, and demonstration preparation

Optional extensions: Kubernetes, canary deployment, advanced monitoring.

## Repository layout

```
RAGGuard/
├── frontend/      React + TypeScript client (Stage 3)
├── backend/       FastAPI service and RAG pipeline (Stage 2)
├── evaluation/    Version-controlled evaluation datasets (Stage 4)
├── deployment/    Deployment configuration (Stage 6+)
├── docs/          Project context, roadmap, decisions, log, architecture, UI spec
└── .github/       CI workflows (Stage 7)
```

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — working rules for AI-assisted development sessions
- [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) — current state
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — stages and completion criteria
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decision record
- [`docs/PROGRESS_LOG.md`](docs/PROGRESS_LOG.md) — chronological history
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components and flows
- [`docs/UI_DESIGN_SPEC.md`](docs/UI_DESIGN_SPEC.md) — visual and interaction specification

## Running the whole application locally

1. Start the backend (see "Backend: getting started" below): `cd backend && .venv/bin/uvicorn app.main:app --port 8000`.
2. Start the frontend (see "Frontend: getting started"): `cd frontend && npm run dev`.
3. Open <http://localhost:5173>. The top bar shows whether the backend is reachable and which model it uses.

## Frontend: getting started

### Prerequisites

Node.js 24 and npm 11 (verified versions). The backend should be running for anything beyond the empty/unreachable states.

### Setup and run

```bash
cd frontend
npm ci                          # installs exactly what package-lock.json records
cp .env.example .env.local      # optional; only needed to change the API URL
npm run dev                     # http://localhost:5173
```

| Command | Purpose |
| --- | --- |
| `npm run dev` | Development server on port 5173 |
| `npm run build` | Strict type check (`tsc -b`) and production build into `frontend/dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run typecheck` | TypeScript only |
| `npm run lint` | ESLint |
| `npm test` | Vitest + React Testing Library (HTTP is mocked; no backend or LLM needed) |

### Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL of the backend. Defined in `frontend/.env.example`. |

Every `VITE_*` variable is compiled into the browser bundle and is public. Never put API keys (Gemini or other), credentials, or backend secrets there; the Gemini key belongs only in the backend's root `.env`.

The backend allows browser requests from `http://localhost:5173` and `http://127.0.0.1:5173` by default. If you serve the frontend from another origin, add it to `CORS_ALLOWED_ORIGINS` in the root `.env`.

### What the interface does

- **Document workspace** — drop or choose one PDF/TXT file at a time (the size limit comes from the backend); the document appears as indexed only after the backend confirms it. The list shows type, pages, chunk count, and indexing time; documents can be removed after confirmation, and ticked to limit questions to them.
- **Questions** — Enter asks, Shift+Enter adds a line. Answers show citation markers (`S1`, `S2`) that open the exact passage in the evidence column with document, page, chunk, and similarity score; cited passages come first. A timing strip shows embedding, retrieval, and generation time and the model used.
- **Not enough evidence** — shown as a neutral panel that explains why (e.g. best score below the threshold; whether the model was called). A failed request is shown separately as an error with Retry.
- **Trace this answer** — the Evidence Trace draws the real path for one answer: documents and pages → chunks → evidence supplied to the model → which of them the answer cites. Use the stage tabs (arrow keys, Home/End) and the evidence list to inspect each item. It uses 3D (three.js) when WebGL is available and falls back to a 2D diagram on small screens, with reduced motion, without WebGL, or on request ("Show 2D view"). It explains the evidence path; it does not prove an answer is correct.
- **Evaluation, Experiments, Pipeline** — listed in the navigation as planned (Stages 4, 5, 7) and show no data until those stages exist.
- **Themes** — follows the system light/dark setting, with a manual override in the top bar.

Conversations are kept only in the browser tab's memory and disappear on reload.

## Backend: getting started

### Prerequisites

- Python 3.13 (verified; the pinned dependencies are what was tested with it).
- [Ollama](https://ollama.com) running locally with the model installed: `ollama list` should show `qwen3.5:9b`. If it is missing: `ollama pull qwen3.5:9b` (RAGGuard never downloads LLMs itself).
- Network access once, for the first download of the embedding model (~90 MB, into the Hugging Face cache, `~/.cache/huggingface`). It happens automatically on the first ingest or query.
- No Qdrant server is needed: by default Qdrant runs embedded and stores data in `qdrant_storage/` (git-ignored).
- No API key is needed unless you opt into Gemini.

### Setup

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # runtime + pytest/ruff/mypy
cp ../.env.example ../.env                         # optional; defaults work without it
```

### Run the API

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Interactive API docs: <http://127.0.0.1:8000/docs>.

```bash
curl -s localhost:8000/health
curl -s -F "file=@/path/to/handbook.pdf" localhost:8000/ingest
curl -s -H 'content-type: application/json' \
     -d '{"question": "How many days of annual leave do employees get?"}' localhost:8000/query
```

### Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /ingest` | Upload one `.pdf` or UTF-8 `.txt` file (multipart field `file`). Extracts text (with PDF page numbers), chunks, embeds, and indexes it. Returns `201` with `document_id`, `filename`, `file_type`, `total_pages`, `chunk_count`, `status: "indexed"`. |
| `POST /query` | Body: `{"question": str, "document_ids"?: [uuid], "top_k"?: 1-20}`. Returns `answer`, `status` (`answered` / `insufficient_evidence`), `fallback_reason`, `sources` (source ID, filename, page, excerpt, score, `cited`), an evidence summary, provider/model, and latency per stage. |
| `GET /health` | Always `200` while the API is up. `status` is `ok` or `degraded`; `generation_ready` and per-component status (vector store, embedding model, generation provider). Never makes a generation call. |
| `GET /documents` | Indexed documents with chunk counts. |
| `DELETE /documents/{document_id}` | Removes a document's chunks from the index. |

Errors are JSON: `{"error": {"code": "...", "message": "..."}}` — e.g. `415 unsupported_file`, `413 file_too_large`, `422 empty_document` / `extraction_failed` / `validation_error`, `503 generation_unavailable`, `429 generation_rate_limited`, `500 generation_not_configured`.

**Insufficient evidence.** If no retrieved passage reaches `MIN_RETRIEVAL_SCORE`, the API returns a fixed fallback answer *without calling the LLM*. If evidence passes the threshold but the model judges that it does not answer the question, the same fallback is returned with `fallback_reason: "model_declined"`.

### Configuration

Settings are read from environment variables or the root `.env`. All variables, with defaults, are documented in [`.env.example`](.env.example).

| Variable | Default | Notes |
| --- | --- | --- |
| `GENERATION_PROVIDER` | `ollama` | `ollama` or `gemini`. No automatic failover. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `qwen3.5:9b` | |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | empty / `gemini-2.5-flash` | Only used when `GENERATION_PROVIDER=gemini`. Keep the key in `.env` only. |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Changing it requires a new collection. |
| `QDRANT_URL` | empty | Empty: embedded local storage. Set to use a Qdrant server. |
| `QDRANT_LOCAL_PATH` / `QDRANT_COLLECTION_NAME` | `qdrant_storage` / `ragguard_chunks` | Relative paths resolve from the repository root. |
| `CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `180` / `30` | Tokens of the embedding model's tokenizer. |
| `DEFAULT_TOP_K` | `4` | Per-request override `top_k` (1-20). |
| `MAX_UPLOAD_SIZE_MB` | `10` | |
| `MIN_RETRIEVAL_SCORE` | `0.35` | Cosine similarity; provisional until Stage 4 measurement. |

### Using Gemini instead of Ollama (optional)

Set `GENERATION_PROVIDER=gemini` and `GEMINI_API_KEY=<your key>` in `.env`, then restart the API. `/health` reports `configured` (it does not call Gemini). Retrieval, prompts, and source references are identical for both providers.

### Tests and static checks

```bash
cd backend
.venv/bin/pytest                 # deterministic suite: no Ollama, no Gemini, temporary Qdrant
.venv/bin/pytest -m ollama       # opt-in: one real end-to-end query through local Ollama
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
```

The embedding-model tests in `tests/test_embeddings_model.py` are skipped (with a reason) if the model is not yet in the local cache; they never download it.

### Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `/health` shows generation `unavailable`; queries return `503 generation_unavailable` | Ollama is not running or `OLLAMA_BASE_URL` is wrong. Start it (`ollama serve` or the Ollama app). |
| Generation status `model_missing` | `OLLAMA_MODEL` is not installed. Check `ollama list`; pull it explicitly if you intend to use it. |
| `504 generation_timeout` | The model took longer than `OLLAMA_TIMEOUT_SECONDS` (first request after idle includes model load). Retry or raise the timeout. |
| `500 generation_not_configured` | `GENERATION_PROVIDER=gemini` without `GEMINI_API_KEY`, or Gemini rejected the key/model. |
| `503 embedding_unavailable` on first ingest/query | The embedding model could not be downloaded or loaded. Check network access for the first download. |
| `503 vector_store_unavailable`, log mentions the storage folder is already accessed | Embedded Qdrant allows one process per folder. Stop the other API process/script, or use a different `QDRANT_LOCAL_PATH`. |
| Frontend top bar says "Backend unreachable" while the API is running | `VITE_API_BASE_URL` points elsewhere, or the page's origin is not in `CORS_ALLOWED_ORIGINS` (check the browser console for a CORS error). |
| `500 configuration_error` mentioning dimensions | The collection was created with a different embedding model. Use a new `QDRANT_COLLECTION_NAME` or switch back. |
| Every question returns `insufficient_evidence` | Nothing indexed, `document_ids` filter excludes the relevant file, or `MIN_RETRIEVAL_SCORE` is too strict. Check `evidence.max_score` in the response. |
| `422 empty_document` for a PDF | The PDF has no extractable text (scanned/image-only); OCR is not supported. |
