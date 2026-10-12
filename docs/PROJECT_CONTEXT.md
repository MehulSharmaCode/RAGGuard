# RAGGuard — Project Context

Concise current-state reference. For stage details see [`ROADMAP.md`](ROADMAP.md); for decisions see [`DECISIONS.md`](DECISIONS.md); for history see [`PROGRESS_LOG.md`](PROGRESS_LOG.md).

_Last updated: 2026-10-13 (end-of-day checkpoint after Stage 3)._

## Purpose

RAGGuard is a document-based Retrieval-Augmented Generation (RAG) assistant with automated answer-quality evaluation and a CI/CD quality gate. Users upload PDF/TXT documents, ask questions, and receive evidence-based answers with document/page references, or a safe fallback when evidence is insufficient. An offline evaluation suite and a CI/CD quality gate measure each proposed change and block releases that fall below documented quality requirements.

## Current stage

**Stage 3 — Frontend application and backend integration: complete (2026-10-13).** Stages 1–2 are also complete. Stage 4 (evaluation dataset and metrics) has not started and awaits explicit instruction.

Repository root: `/Users/mehulsharma/Desktop/Developer/RAGGuard`, branch `main`, local Git only: **no commits and no remote yet — all work is untracked files on disk** (see "Next Session Handoff").

## Implemented vs. planned

| Stage | Area | Status | Verified by |
| --- | --- | --- | --- |
| 1 | Project structure, architecture, design specification, persistent documentation | Complete (2026-10-12) | Structure/ignore/secret checks (`PROGRESS_LOG.md`) |
| 2 | FastAPI backend: PDF/TXT ingestion, local Sentence Transformers embeddings, Qdrant retrieval, Ollama `qwen3.5:9b` (default) with optional Gemini, source citations, insufficient-evidence fallback | Complete and tested (2026-10-12) | 115 pytest tests; ruff + mypy strict; opt-in real-Ollama test; live API smoke test |
| 3 | React + TypeScript + Vite + Tailwind frontend: document management, question answering, evidence inspection, 3D Evidence Trace with 2D/accessible fallbacks | Complete and tested (2026-10-13) | 40 Vitest tests; strict `tsc`; ESLint; production build; Chrome end-to-end test against the real backend and model; Lighthouse accessibility 100 (light and dark) |
| 4 | Evaluation dataset, deterministic retrieval/fallback metrics, local LLM-as-judge, threshold analysis, JSON/Markdown reports | **Next — not started** (`backend/app/evaluation/` and `evaluation/datasets/` are empty) | — |
| 5 | MLflow experiment tracking | Planned | — |
| 6 | Docker and Docker Compose | Planned | — |
| 7 | GitHub Actions and the automated release-quality gate | Planned | — |
| 8 | End-to-end verification and demonstration preparation | Planned | — |

Blocked: nothing. Planned-but-visible: the Evaluation, Experiments, and Pipeline views exist in the UI only as honest "planned" placeholders with no data.

Last checkpoint verification (2026-10-13, no code changes since Stage 3 completion): backend `pytest` 115 passed / 1 deselected, `ruff` and `mypy` clean; frontend `tsc -b`, ESLint clean, Vitest 40 passed.

## Backend (implemented)

- **Endpoints:** `POST /ingest`, `POST /query`, `GET /health`, `GET /documents`, `DELETE /documents/{document_id}` (D-029). Contract in `backend/app/schemas/`; flows in `ARCHITECTURE.md` §3a.
- **Orchestration:** `backend/app/pipeline.py` (`RAGPipeline`) — the single pipeline the Stage 4 evaluation runner must reuse (D-028).
- **Modules:** `core/` (settings, errors, logging), `ingestion/` (validation, pypdf/TXT extraction, token-aware chunking), `embeddings/` (local Sentence Transformers), `retrieval/` (Qdrant store, evidence rule), `generation/` (provider protocol, Ollama, Gemini, factory, prompts), `api/routes/`.
- **Generation:** Ollama `qwen3.5:9b` by default, local, `think: false` (D-019). Gemini optional via `google-genai`, never default, no failover (D-020).
- **Embeddings / storage:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, cosine) (D-021); Qdrant embedded local persistent mode at `qdrant_storage/` unless `QDRANT_URL` is set (D-027).
- **Defaults (provisional, tuned in Stage 4):** chunk 180 tokens / overlap 30, top-k 4, upload limit 10 MB, `MIN_RETRIEVAL_SCORE` 0.35 (D-023–D-025).
- **Fallback:** no retrieved chunk ≥ threshold → fallback without an LLM call; the model can also decline (`INSUFFICIENT_EVIDENCE`) → fallback (D-024).
- **Tests:** `backend/tests/` — 115 deterministic tests (fake embedder + fake LLM, temporary Qdrant per test; real-model embedding tests when the model is cached) + 1 opt-in real-Ollama test (`pytest -m ollama`).

## Frontend (implemented)

- **Screens:** application shell (nav rail / mobile menu, top bar with real backend status, model, collection, theme switch); **Document Workspace** (upload, document list with scope selection and confirmed removal, question thread, evidence column); **Evidence Trace** ("Trace this answer", plus a labelled first-run illustration); **Evaluation, Experiments, Pipeline** are honest "planned" views with no data.
- **Structure:** `src/app` (composition, routing, health), `src/lib/api` (the only HTTP code, typed and runtime-validated), `src/types/api.ts` (mirrors backend schemas), `src/components/ui` (primitives), `src/features/documents`, `src/features/chat` (+ `trace/`), `src/styles` (tokens). See `ARCHITECTURE.md` §2 and §3b.
- **Integration:** all five endpoints (`GET /health`, `GET /documents`, `POST /ingest`, `DELETE /documents/{id}`, `POST /query` with optional `document_ids`). Base URL `VITE_API_BASE_URL` (default `http://localhost:8000`), documented in `frontend/.env.example`.
- **Design:** tokens in `src/styles/tokens.css` (light + dark, contrast-tested), self-hosted IBM Plex Sans/Mono and Source Serif 4, Lucide icons (D-030–D-038, `UI_DESIGN_SPEC.md` §16).
- **3D:** three.js + React Three Fiber in a lazy chunk; 2D SVG fallback for no WebGL, reduced motion, < 768 px, user preference, loading, or failure.
- **Tests:** `frontend/src/test/` — 40 Vitest + React Testing Library tests with mocked HTTP (no backend or LLM needed).

## Configuration

All settings come from environment variables / root `.env` via `backend/app/core/config.py`; every variable is documented with defaults in [`.env.example`](../.env.example). Key variables: `GENERATION_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `EMBEDDING_MODEL`, `QDRANT_URL`, `QDRANT_LOCAL_PATH`, `QDRANT_COLLECTION_NAME`, `CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `DEFAULT_TOP_K`, `MAX_UPLOAD_SIZE_MB`, `MIN_RETRIEVAL_SCORE`.

Toolchain: Python 3.13, `backend/.venv`, exact pins in `backend/requirements.txt` / `requirements-dev.txt`, ruff + mypy (strict) + pytest configured in `backend/pyproject.toml` (D-026). Frontend: Node 24 / npm 11 with `frontend/package-lock.json`; scripts `dev`, `build`, `typecheck`, `lint`, `test` (D-030). The only frontend variable is the public `VITE_API_BASE_URL`; no secrets belong in `VITE_*`.

## Technology stack

**Confirmed:** React 19, TypeScript 6 (strict), Vite 8, Tailwind CSS 4, Lucide, three.js + React Three Fiber (limited), Vitest + React Testing Library · Python 3.13, FastAPI, Pydantic, pydantic-settings · Ollama (`qwen3.5:9b`) with optional Gemini (`google-genai`) · Sentence Transformers (`all-MiniLM-L6-v2`) · Qdrant · pypdf · pytest, httpx, Python evaluation scripts, MLflow · Docker, Docker Compose, GitHub Actions, Git.

**Undecided:** evaluation dataset and judge (U-008, U-009), thresholds (U-010), MLflow storage (U-011), CI access to models, triggers, registry/deployment target, pipeline-view data source (U-012–U-015). Full list in `DECISIONS.md` §3.

## System boundaries

- **In scope:** PDF/TXT ingestion, retrieval-grounded answers with citations and safe fallback, offline evaluation on a fixed dataset, MLflow tracking, containerized local stack, CI quality gate, and a purpose-built UI.
- **Out of scope (initially):** other file formats, OCR of scanned PDFs, password-protected PDFs, non-UTF-8 text files, user accounts/multi-tenancy, Kubernetes, canary deployment, advanced monitoring (optional extensions).
- **External services:** Ollama (local, default) or Gemini (hosted, optional). The embedding model runs in-process; it is downloaded once to the Hugging Face cache on first use. Qdrant runs embedded or as a server.

## Known limitations

- `MIN_RETRIEVAL_SCORE` = 0.35 is provisional, chosen from a handful of manual measurements: answerable questions scored 0.66–0.88, unrelated ones 0.06–0.27, and related-but-unanswerable ones 0.31–0.68 (the last group is why the model-decline step exists). It has not been measured on an evaluation dataset; similarity does not prove an answer is correct.
- Prompt-injection text in documents was not followed in the smoke test, but `qwen3.5:9b` sometimes *mentions* the ignored instruction in an "Interpretation:" sentence despite being told not to.
- Embedded local Qdrant allows one process per storage folder: do not run two API processes (or the API and another script) on the same `QDRANT_LOCAL_PATH`.
- `GET /documents` scans all chunk payloads; fine for development-scale collections, not optimized for large ones.
- Original uploaded files are not retained (D-025); re-indexing requires re-uploading.
- The UI and the Evidence Trace display what the backend returns; they do not fix the provisional evidence threshold or the imperfect prompt-injection behaviour. A trace explains the evidence path, it does not prove an answer correct.
- Conversations live in browser memory only and are lost on reload; there are no accounts.
- Upload progress is indeterminate: the API reports only the final result. One file per upload.
- Citations resolve to the whole retrieved passage; the API provides no sub-span for highlighting.
- Fallback answers show an evidence summary but no "closest passages", because the API does not return them.
- The 3D chunk is ~242 kB gzip (three.js is not tree-shakeable under R3F). LCP has not been measured.
- `prefers-reduced-motion` handling is covered by unit tests; it was not toggled in a real browser (the DevTools tooling used could not emulate it).

## Folder responsibilities

| Path | Responsibility |
| --- | --- |
| `frontend/` | React + TypeScript SPA (see "Frontend" above). `features/evaluation` and `features/experiments` are reserved and empty; `public/models` stays empty (procedural geometry only) |
| `backend/app/` | FastAPI service (see "Backend" above); `evaluation/` and `tracking/` packages are empty until Stages 4–5 |
| `backend/tests/` | pytest + httpx tests |
| `evaluation/datasets/` | Fixed, version-controlled evaluation dataset (Stage 4) |
| `deployment/` | Deployment and container configuration (Stage 6+) |
| `docs/` | Project documentation (this file and siblings) |
| `.github/workflows/` | CI workflows (Stage 7) |

## Outstanding work

Stages 4–8 as defined in `ROADMAP.md`.

## Known blockers

None.

## Next action

Stage 4 — automated evaluation dataset and quality metrics, on explicit instruction only. Resolve U-008 (dataset sources and size) and U-009 (LLM-judge setup) first; the runner must call `RAGPipeline` (D-028).

## Next Session Handoff

_Written 2026-10-13 at the end-of-day checkpoint. Read this first in a fresh session; it is consistent with `ROADMAP.md` and the last `PROGRESS_LOG.md` entry._

**1. Current stage.** Stages 1–3 are complete; the last verified completion is Stage 3 (2026-10-13). Stage 4 has **not** started. All project files exist only as **uncommitted, untracked files** on branch `main` (no commits, no remote). Do not delete, reset, or stash them; committing happens only when the developer asks.

**2. Architecture facts to preserve.**
- One RAG pipeline: `backend/app/pipeline.py` (`RAGPipeline`) serves the live API and must be reused, not duplicated, by the Stage 4 evaluation runner (D-008, D-028). Evaluation never runs per user query.
- Generation: Ollama `qwen3.5:9b` by default, `think: false`, no automatic failover; Gemini optional and never used by ordinary tests (D-019, D-020).
- Embeddings `sentence-transformers/all-MiniLM-L6-v2` (384-dim, cosine); Qdrant embedded local mode at `qdrant_storage/` unless `QDRANT_URL` is set (D-021, D-027).
- Citations come only from retrieved metadata; insufficient evidence returns the fallback without calling the LLM, or after the model declines (D-010, D-024).
- The LLM judge is supplementary, never the sole source of truth; thresholds only after a measured baseline, stored in version control (D-011, D-012).
- Frontend: one typed API client in `frontend/src/lib/api/`; design tokens in `frontend/src/styles/tokens.css`; no fabricated metrics or statuses; 3D only in the first-run illustration and "Trace this answer" (D-013–D-015, D-030–D-038).

**3. Known issues and unresolved decisions.**
- `MIN_RETRIEVAL_SCORE` 0.35 is provisional (about 20 manual questions; never measured on a dataset).
- Prompt-injection robustness is imperfect: injected instructions were not followed in testing, but `qwen3.5:9b` sometimes mentions them.
- Embedded local Qdrant allows one process per storage folder; tests and smoke tests must use a temporary `QDRANT_LOCAL_PATH`.
- Scanned/image-only PDFs (no OCR), password-protected PDFs, and non-UTF-8 TXT are unsupported.
- Conversations are in-memory only; LCP not measured; reduced motion not toggled in a real browser (unit-tested only).
- npm 11 reports that `fsevents`' optional install script is not approved; left for the developer.
- Open decisions: U-008 (dataset sources/size), U-009 (judge model, prompt, weighting; direction "local judge", P-009), U-010 (thresholds), U-011–U-015 (later stages).

**4. Next task: Stage 4 — Evaluation dataset, metrics, and evaluation runner** (only when explicitly requested). Scope per `ROADMAP.md` Stage 4 and P-003/P-009: a fixed, licence-compatible, version-controlled dataset including unanswerable questions; deterministic retrieval and fallback metrics; a local LLM judge as a supplementary metric; a measured baseline and threshold analysis; reproducible JSON and Markdown reports under `evaluation/results/`. Acceptance criteria (`ROADMAP.md`):
- the runner executes end-to-end on the dataset through `RAGPipeline` and writes results with configuration and dataset version;
- a measured baseline is recorded in `PROGRESS_LOG.md`, and thresholds are documented and version-controlled;
- failed cases are inspectable individually in the UI.
Resolve U-008 and U-009 at the start of the stage and record them in `DECISIONS.md`.

**5. Read first tomorrow:** `CLAUDE.md` → this file → `docs/ROADMAP.md` (Stage 4) → `docs/DECISIONS.md` (P-003, P-004, P-005, P-009, U-008–U-010) → the last two entries of `docs/PROGRESS_LOG.md` → `docs/ARCHITECTURE.md` §4 → `backend/app/pipeline.py` and `backend/app/schemas/query.py`. Read `docs/UI_DESIGN_SPEC.md` §8.3 before touching the Evaluation view.

**6. Scope rule.** Implement Stage 4 only when explicitly requested. Do not begin Stage 5 (MLflow) or any later stage automatically.
