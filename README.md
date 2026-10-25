# RAGGuard

> **Status: under development (Stage 5.7 closure, 2026-10-25).** Stages 1–5 are complete; Stage 5.5 and Stage 5.7 (cross-document reliability, conversation isolation, its stabilisation, and the 2026-10-25 closure pass: prompt v8, evaluator e3) are implemented and automatically verified; **Stage 5.7 is closed: the owner's manual acceptance passed on 2026-10-25** (the owner's acceptance of Stages 5 and 5.5 was not recorded separately). Stages 6–8 are pending and start only on the owner's instruction. The backend ingests PDF/TXT files, answers questions with cited sources through a local LLM, and falls back safely when evidence is insufficient, with layered prompt-injection mitigations; the web frontend provides the document workspace (whose conversation survives navigation and reloads of the tab), the Evidence Trace, and Evaluation, Experiments, and Pipeline views on real data; an offline evaluation suite (the 85-case core benchmark incl. 31 prompt-injection scenarios, plus separate VEIL Document Challenge (20 cases), structural (41) and AgriSense (27) benchmarks) measures the same pipeline, writes JSON/Markdown reports, and logs runs to MLflow. There is no Docker setup or CI gate yet, and the visual redesign is pending. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the authoritative stage status.

RAGGuard is a quality-gated Retrieval-Augmented Generation (RAG) application. Upload PDF or TXT documents, ask questions about them, and get answers grounded in retrieved evidence, with references to the source document and page.

What sets it apart is the release discipline around it: an automated evaluation suite measures retrieval and answer quality against a fixed, version-controlled dataset, and a CI/CD quality gate blocks a release when those measurements fall below documented requirements.

## Core features

Document ingestion, evidence-based answers, safe fallback (Stage 2), the document workspace interface (Stage 3), the offline evaluation suite (Stages 4–5, command line), MLflow tracking (Stage 5), and the evaluation, experiment, and pipeline views (Stage 5.5) are implemented; containers and CI are planned.

- **Document ingestion** — PDF and TXT upload; layout-aware PDF text (page regions and table rows rebuilt from text positions, safe for PDFs that write text in tiny fragments); structure-aware chunks; each chunk embedded together with its rows, list items, and sentences, plus a lexical (BM25-weighted) vector; storage in Qdrant.
- **Evidence-based answers** — hybrid retrieval of relevant passages (semantic and lexical candidates fused; a chunk becomes evidence only if its best-matching row, item, or sentence passes the semantic threshold; evidence is ordered by that score; the whole chunk is the cited passage), LLM answer generation constrained to that evidence, and source references (document, page where available).
- **Safe fallback** — an explicit "not enough evidence" response instead of an unsupported answer.
- **Offline evaluation** — a fixed, version-controlled dataset of questions, reference answers, and expected sources over a synthetic corpus; deterministic metrics for retrieval, citations, answerability/fallback, required facts, and latency; an offline sweep of the evidence threshold; a local LLM judge as a supplementary signal only (see "Evaluation" below).
- **Experiment tracking** — MLflow (local SQLite store) records each evaluation run's configuration, dataset fingerprint, metrics, and reports for comparison (see "MLflow experiment tracking" below).
- **Prompt-injection mitigations** — retrieved text is treated as untrusted data: markup neutralisation, instruction and supersession labels, priority rules, and output guards (no claim of immunity; see `docs/ARCHITECTURE.md` §3c).
- **Quality-gated CI/CD** — GitHub Actions runs API tests and the evaluation suite; a failed gate prevents image build and release.
- **Purpose-built interface** — document workspace with cited evidence and an Evidence Trace; an Evaluation view of saved reports with failed-case inspection; an Experiments view of MLflow runs with side-by-side comparison; a Pipeline view with the actual flow and live component status (Stage 5.5, read-only). Starting an evaluation from the UI and listing cases whose outcome changed between two runs are not implemented.

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
| Evaluation | Python evaluation runner (`backend/app/evaluation/`) over the production pipeline, fixed version-controlled dataset (`evaluation/datasets/`), local Ollama judge, JSON + Markdown reports |
| Tracking | MLflow 3.17 (local SQLite store `mlflow.db`; written by the evaluation CLI, read by the Experiments view) |
| DevOps | Docker, Docker Compose, GitHub Actions, Git |

Unresolved choices (evaluation dataset, quality thresholds, deployment target) are tracked in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Implementation stages

1. Project foundation and documentation
2. Backend RAG pipeline and API
3. Frontend application and backend integration
4. Evaluation dataset, metrics, and evaluation runner
5. Evaluation hardening, RAG reliability/security, and MLflow tracking
5.5. Conversation persistence, functional dashboards, and product integration
6. Docker and Docker Compose integration
7. GitHub Actions testing and automated quality gate
8. End-to-end integration, verification, documentation, and demonstration preparation

Optional extensions: Kubernetes, canary deployment, advanced monitoring.

## Repository layout

```
RAGGuard/
├── frontend/      React + TypeScript client (Stage 3)
├── backend/       FastAPI service and RAG pipeline (Stage 2)
├── evaluation/    Version-controlled evaluation dataset and corpus; generated results (git-ignored)
├── deployment/    Deployment configuration (Stage 6+)
├── docs/          Project context, roadmap, decisions, log, architecture, UI spec
└── .github/       CI workflows (Stage 7)
```

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — working rules for AI-assisted development sessions
- [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) — current state
- [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) — current handoff: status, open issues, manual acceptance checklist, next steps
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — stages and completion criteria
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decision record
- [`docs/PROGRESS_LOG.md`](docs/PROGRESS_LOG.md) — chronological history
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components and flows
- [`docs/UI_DESIGN_SPEC.md`](docs/UI_DESIGN_SPEC.md) — visual and interaction specification

## Running the whole application locally

Prerequisites: Python 3.13 with `backend/.venv` set up (see "Backend: getting started"), Node.js 24 / npm 11 with `frontend/node_modules`, and Ollama with `qwen3.5:9b`. One terminal each:

```bash
# 1. Ollama (skip if the Ollama app is already running)
ollama serve

# 2. Backend API -> http://127.0.0.1:8000 (docs at /docs)
cd /Users/mehulsharma/Desktop/Developer/RAGGuard/backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Frontend -> http://localhost:5173
cd /Users/mehulsharma/Desktop/Developer/RAGGuard/frontend
npm run dev

# 4. Optional: MLflow's own UI over the existing store -> http://127.0.0.1:5050
cd /Users/mehulsharma/Desktop/Developer/RAGGuard
ls -l mlflow.db     # exists after the first tracked evaluation run
backend/.venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5050
```

Open <http://localhost:5173>. The top bar shows whether the backend is reachable and which model it uses. The Evaluation and Experiments views read `evaluation/results/` and `mlflow.db` through the API; MLflow's own UI is not required for them. The Stage 5.7 manual acceptance checklist (passed by the owner on 2026-10-25) is in [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) §4.

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
- **Evaluation** — the latest saved report (or any older one, also via `#/evaluation/<run_id>`): run header with dataset and configuration, open findings (successful attacks, canary leaks, superseded-source citations, false answers/refusals), metrics with their denominators ("Not recorded" when a report lacks a metric, "n/a" when no case applied — never shown as 0), a case table filtered by verdict, category, finding, and text, with expected vs. actual answer, retrieved passages, attack details, and the supplementary judge verdict; downloads of `report.json`/`report.md`. Opening it never starts an evaluation.
- **Experiments** — MLflow runs of `ragguard-evaluation` with parameters, principal metrics, and artifact downloads; choose a baseline and a candidate to compare parameters and metrics. Runs on different datasets are marked not comparable, mixed results are shown as a trade-off, and an unavailable or missing tracking store is reported as such (never as zero runs).
- **Pipeline** — the implemented RAG flow with the current settings (a code-path description, not recorded executions), live status of API, vector store, embedding model, generation, evaluation dataset, and MLflow (healthy / configured, not verified / unavailable), and what is not built yet (Docker, CI quality gate, visual redesign).
- **Themes** — follows the system light/dark setting, with a manual override in the top bar.

**Conversation history** survives switching between views and reloading the tab: it is kept in the tab's sessionStorage (last 50 questions with their answers and cited excerpts) until you use "Clear conversation" or close the tab. It is never sent anywhere; uploaded files are not stored in the browser.

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
.venv/bin/pip install -r requirements-dev.txt     # runtime + evaluation (MLflow) + pytest/ruff/mypy
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
| `GET /evaluations`, `GET /evaluations/{run_id}`, `GET /evaluations/{run_id}/files/{report.json\|report.md}` | Read-only saved evaluation reports (Stage 5.5). Unknown run → `404 report_not_found`; unreadable report → `422 report_unreadable`. |
| `GET /experiments/runs`, `GET /experiments/runs/{id}`, `GET /experiments/compare?baseline=&candidate=`, `GET /experiments/runs/{id}/artifacts/{report.json\|report.md\|failures.json}` | Read-only MLflow runs and comparison. The list reports `tracking.state` (`available`, `empty`, `no_store`, `dependency_missing`, `unavailable`); other calls return `404 run_not_found` / `artifact_not_found` or `503 tracking_unavailable` / `tracking_dependency_missing`. |
| `GET /system/status` | Component states (`healthy`, `configured`, `unavailable`, `not_implemented`) from live checks, plus the latest report and tracking status. |

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
| `CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `180` / `30` | Tokens of the embedding model's tokenizer. Whole regions are packed up to the size; the overlap applies when one region is longer and is split. |
| `DEFAULT_TOP_K` | `4` | Per-request override `top_k` (1-20). |
| `MAX_UPLOAD_SIZE_MB` | `10` | |
| `RETRIEVAL_DIAGNOSTICS` | `false` | Developer-only `POST /diagnostics/query`: retrieval candidates, scores, evidence decision, and (on request) the model's raw reply. Absent from the API unless `true` (D-066). |
| `MIN_RETRIEVAL_SCORE` | `0.35` | Best-vector cosine of a chunk (the chunk or one of its sub-units). Set on 2026-10-16 after calibrating answerable, unanswerable, and unrelated questions on three benchmarks (D-063); provisional. Collections indexed before then ("legacy") always use 0.30 (D-052). |
| `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_NAME` | empty (= `mlflow.db` in the repository root) / `ragguard-evaluation` | Written by the evaluation CLI; read (never written) by the Experiments view. A missing local store is reported, not created. |
| `EVALUATION_DATASET_PATH` / `EVALUATION_RESULTS_DIR` | `evaluation/datasets/dataset.json` / `evaluation/results` | CLI defaults and the locations the Evaluation and Pipeline views read. Leave unset for the defaults (an empty value would mean the repository root). |

### Using Gemini instead of Ollama (optional)

Set `GENERATION_PROVIDER=gemini` and `GEMINI_API_KEY=<your key>` in `.env`, then restart the API. `/health` reports `configured` (it does not call Gemini). Retrieval, prompts, and source references are identical for both providers.

### Tests and static checks

```bash
cd backend
.venv/bin/pytest                 # deterministic suite (390 tests + 1 documented xfail): no Ollama, no Gemini, temporary Qdrant, results, and MLflow stores
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

## Evaluation

The offline evaluation runs a fixed dataset through the **same `RAGPipeline`** the API uses (ingestion, chunking, embeddings, Qdrant search, evidence threshold, prompt, generation, output checks, citations, fallback), writes a JSON and a Markdown report, and logs the run to MLflow. It never touches your indexed documents: every run indexes the fixture corpus into a new temporary embedded Qdrant directory and deletes it afterwards, even on errors. It does not run per user query and applies no quality gate (Stage 7).

### Run it

From `backend/`, with Ollama running (`qwen3.5:9b` installed) and the embedding model cached:

```bash
.venv/bin/python -m app.evaluation.run_evaluation --validate-only                # check the dataset only
.venv/bin/python -m app.evaluation.run_evaluation --skip-judge --label quick     # 85 cases, no judge (~80 s measured)
.venv/bin/python -m app.evaluation.run_evaluation --label my-run                 # 85 cases + local judge (~4 min measured)
.venv/bin/python -m app.evaluation.run_evaluation --cases INJ-009,INJ-010 --skip-judge   # selected cases
.venv/bin/python -m app.evaluation.run_evaluation --dataset ../evaluation/datasets/veil/dataset.json --label veil   # VEIL benchmark, 20 cases + judge (~1.5 min measured)
.venv/bin/python -m app.evaluation.run_evaluation --dataset ../evaluation/datasets/structure/dataset.json --label structural   # structural benchmark, 41 cases + judge (~2.5 min measured)
.venv/bin/python -m app.evaluation.run_evaluation --dataset ../evaluation/datasets/agrisense/dataset.json --label agrisense     # AgriSense benchmark, 27 cases + judge (~3 min measured)
```

Each benchmark runs on its own; reports and MLflow runs carry the dataset ID, version, and fingerprint, the Evaluation and Experiments views name the dataset, and runs on different datasets are never compared.

| Option | Meaning |
| --- | --- |
| `--dataset PATH` | Dataset JSON (default `EVALUATION_DATASET_PATH`, i.e. `evaluation/datasets/dataset.json`) |
| `--output-dir DIR` | Reports go to `DIR/<run_id>/report.json` and `report.md` (default `EVALUATION_RESULTS_DIR`, i.e. `evaluation/results/`, git-ignored; the Evaluation view reads this folder) |
| `--limit N` / `--cases ID,ID` | Run only the first N cases / only these case IDs |
| `--skip-judge` | Skip the LLM judge; answers are still generated by the configured provider |
| `--judge-model NAME` | Ollama model for the judge (default `OLLAMA_MODEL`) |
| `--work-dir DIR` | Parent of the temporary vector store (default: system temp; refused inside `QDRANT_LOCAL_PATH`) |
| `--no-tracking` | Do not log to MLflow |
| `--tracking-uri URI`, `--experiment NAME`, `--label TEXT` | MLflow store, experiment, and a label tag |
| `--import-report PATH` | Log an existing `report.json` (+ `report.md`) to MLflow instead of running (used for the Stage 4 legacy runs) |
| `--rescore PATH` | Re-score a saved schema-2 report with the current evaluator (no model calls; same dataset required) and log it |

Exit code `0` = completed, `1` = partial (some cases or judge calls failed; each is recorded), `2` = failed run or invalid dataset, `3` = reports written but MLflow logging failed. Exit codes describe execution, not quality. Generation uses the configured provider (`GENERATION_PROVIDER`, Ollama by default); the judge always uses local Ollama.

### MLflow experiment tracking

Runs are logged to the experiment `ragguard-evaluation` in a local SQLite store, `mlflow.db` in the repository root, with artifacts in `mlartifacts/` (both git-ignored, persistent across restarts). Set `MLFLOW_TRACKING_URI` (or `--tracking-uri`) to use another store or a server. The evaluation CLI writes runs; the API only reads them for the Experiments view, importing MLflow lazily (the query path never imports it, and without MLflow installed the view reports `dependency_missing`). Besides the Experiments view, MLflow's own UI can inspect runs:

```bash
cd /Users/mehulsharma/Desktop/Developer/RAGGuard
backend/.venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5050
# open http://127.0.0.1:5050 -> experiment "ragguard-evaluation"
```

Port 5050 is used because macOS reserves 5000 for AirPlay. Each run has whitelisted parameters (models, prompt and judge versions, embedding model, chunking, top-k, threshold, dataset version and fingerprint), tags (RAGGuard run ID, status, label, Git commit and dirty flag), every numeric aggregate as a metric named by its JSON path (e.g. `security.attack_success_rate`, with `….denominator`), the threshold sweep as stepped series, and `reports/report.json`, `report.md`, `failures.json` as artifacts. Secrets and `.env` values are never logged.

### Dataset

`evaluation/datasets/` holds `dataset.json` v2.0.0 (85 cases: 69 answerable, 16 unanswerable; 32 prompt-injection attack cases covering 31 distinct scenarios across 24 attack vectors, 7 benign controls, plus lookalike-unanswerable, low-overlap, multi-passage, historical, false-premise, outdated, resolvable and unresolved conflict cases) and `corpus/` (42 hand-written documents about a fictional company). Schema, attack success criteria, validation rules, and how to add cases: [`evaluation/datasets/README.md`](evaluation/datasets/README.md). The core dataset is the regression benchmark and stays unchanged.

`evaluation/datasets/veil/` holds the **VEIL Document Challenge** (`veil-document-challenge` v1.0.0, 20 cases: exact reported numbers, risk → mitigation pairs, multi-section and source-selection questions, false premises, unanswerable questions, four document-embedded attacks whose payloads are confirmed to reach the model, two benign controls). Its corpus is a copy of the owner's SIH 2026 proposal PDF plus three synthetic fixtures; reference answers restate the proposal's claims, which are not independently verified. Provenance and limits: [`evaluation/datasets/veil/README.md`](evaluation/datasets/veil/README.md).

`evaluation/datasets/structure/` holds the **structural retrieval benchmark** (`structural-retrieval` v1.0.0, 41 cases: tables with wrapped cells written box by box and row-major, a slide-style multi-region page, nested lists under headings, a long paragraph across chunk boundaries, near-identical documents with different facts, the owner's VEIL risk-table questions, and 10 negative controls). Fixtures are synthetic (two PDFs generated deterministically by `build_pdf_fixtures.py`) plus a copy of the VEIL PDF: [`evaluation/datasets/structure/README.md`](evaluation/datasets/structure/README.md).

`evaluation/datasets/agrisense/` holds the **AgriSense / EVIDENT benchmark** (`agrisense-evident` v1.0.0, 27 cases on the owner's 22-page research PDF, each with expected pages that the loader checks): core mechanisms, verdict states, assurance levels, gap planning, failure handling, re-evaluation, joint holdings, numeric table claims, proposed vs demonstrated capabilities, false premises, and unsupported performance claims: [`evaluation/datasets/agrisense/README.md`](evaluation/datasets/agrisense/README.md).

### Metrics

Every rate is reported as `value (numerator/denominator)`; an empty denominator gives `n/a`, never 0; pipeline errors are listed and excluded, never counted as successes. Full definitions are written into each report.

| Group | Metrics |
| --- | --- |
| Correctness (deterministic) | Case pass rate; correct answers on answerable cases (answered + all required facts + no unsupported content + no successful attack); answer failures; false refusals; unsupported-content rate (case-specific forbidden strings/patterns) |
| Security | Attack success rate (per case and per scenario), share of document attacks whose payload reached the evidence (an attack filtered out by retrieval was never tested against the model), canary leak rate, legitimate-task completion under attack, success by vector and channel, echoed injection text (reported, not counted as success), benign-control success and unnecessary-refusal rate |
| Answerability | Positive class = answerable; prediction = the pipeline's `status`. Confusion matrix, precision, recall, F1, correct-fallback, false-answer, false-fallback rates; fallback reasons |
| Retrieval | Expected-source hit rate@k, hit rate among evidence passages, coverage, multi-source coverage, by category |
| Citations | Validity (`[Sn]` resolves), presence, expected-source citation rate, cited-source precision, **claim support** (each required fact stated in a sentence citing a passage that contains it; lexical), superseded-source citations |
| Latency | Per-query end-to-end (monotonic clock): mean, median, p95 (nearest rank; unstable for small n); ingestion, judging, total |
| LLM judge (supplementary) | Correctness, groundedness, completeness (1–5), unsupported claims, whether citations support claims, unanswerable handling; judge errors counted, never replaced by scores |
| Threshold sweep | Retrieval-gate confusion matrix and rates for 0.00–0.90 from recorded max scores, pass rates by category, estimated end-to-end F1, score overlap, high-similarity failures |

### Reports

`report.json` (schema 2.0, validated after writing) contains the run ID and timestamps, status, dataset version and fingerprint, configuration, metric definitions, aggregates, threshold analysis, every case (reference and generated answers, all retrieved passages with scores, fallback status, latency, deterministic checks, attack result, judge result, errors), and limitations. `report.md` is rendered from the same data and re-checked against the saved JSON. Reports are not committed.

### Known limitations

- 85 synthetic TXT cases (core) and 20 cases (VEIL): a single case moves an attack or category rate by several points; results describe this corpus, not general quality or security. p95 is unstable.
- Correctness, claim-support, attack, and diagnostic checks are lexical. They miss paraphrases and can flag an honest answer that mentions a forbidden value in another context (e.g. LKU-001). Representative failures were inspected manually (see `docs/PROGRESS_LOG.md`).
- Passing attack cases do not prove prompt-injection resistance; the instruction-hint heuristic, the span withholding, and the prompts (v4, v6, v7, v8) were written with knowledge of these attack sets. Withholding removes only phrasing the heuristic flags; a question that itself asks about instructions or AI assistants sees such text (labelled).
- The judge uses the same model as generation (self-evaluation bias) and varies between runs; it never replaces the deterministic metrics.
- "Answered" counts as predicting answerable even when the answer text itself hedges.
- Local inference is not perfectly reproducible between runs.
- Prompt v6 (2026-10-15) fixes false-premise abstention on the VEIL benchmark but occasionally answers a related-unanswerable core question and shows attack successes at the top of v4's range (D-061). The VEIL risk table is not retrieved for the natural question (U-016).
- Retrieval (2026-10-16, D-063): documents indexed before the change must be deleted and re-uploaded to use the new index (legacy collections keep the old scoring). Questions whose wording matches another section better (e.g. "What are the risks of VEIL…") and some low-overlap paraphrases of table rows still miss; the 0.35 threshold has thin measured margins (U-016). Layout reconstruction estimates text widths and has no OCR: scanned PDFs are still rejected, rotated pages fall back to plain extraction, and unusual layouts may be segmented imperfectly.
- Stage 5.7 (2026-10-16, D-064–D-066): documents indexed before the hybrid index must be deleted and re-uploaded to benefit (older indexes keep working with their previous retrieval). Questions with little word overlap with the answer text, and answers whose list spans two chunks, can still fail (U-016). Conversations are separated by document context per browser tab; they are not shared across tabs or devices.
- Stage 5.7 stabilisation (2026-10-16, D-067, D-068): prompt v7 stops labelled instruction-like passages from being reported as "conflicting sources" (fixed VEL-INJ-001 in all measured runs; INJ-006 still succeeds in about half of repeated generations on its current evidence). One AgriSense false-premise question now declines instead of correcting the premise. Superseded values are still mentioned for current questions in 3 of 5 outdated-source cases (U-017). The evaluator records its version (`e2`: forbidden content counts only when not negated).
- Stage 5.7 closure (2026-10-25, prompt v8, D-069–D-074): instruction-like spans are withheld from the model's copy of a passage; explicitly replaced documents are left out for current questions (history questions keep them); an answer must cite at least one supplied passage and use only values and pages from the evidence, or it is regenerated once and then withheld as `model_declined` — so a correct answer that computes a new number (a difference of two prices) may be declined; passages regain the rest of a region that was split across chunks (bounded to 6,000 characters of evidence). The evaluator is `e3` (glosses such as "F (false) dominates" no longer hide a fact) and the VEIL benchmark is v1.1.0. Questions whose answer sits in a chunk ranked below the top four (AGR-VRD-001) still fail; no reranker is used. Results: `docs/PROGRESS_LOG.md` 2026-10-25.
