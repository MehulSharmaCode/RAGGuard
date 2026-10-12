# RAGGuard — Roadmap

Authoritative stage status. A stage is marked **Complete** only after every completion criterion has been checked and the result recorded in `PROGRESS_LOG.md`. Work on one stage at a time, and only on explicit instruction.

| Stage | Title | Status |
| --- | --- | --- |
| 1 | Project foundation and documentation | Complete (2026-10-12) |
| 2 | Backend RAG pipeline and API | Complete (2026-10-12) |
| 3 | Frontend application and backend integration | Complete (2026-10-13) |
| 4 | Evaluation dataset, metrics, and evaluation runner | Not started |
| 5 | MLflow experiment tracking and result comparison | Not started |
| 6 | Docker and Docker Compose integration | Not started |
| 7 | GitHub Actions testing and automated quality gate | Not started |
| 8 | End-to-end integration, verification, documentation, and demonstration preparation | Not started |

---

## Stage 1 — Project foundation and documentation

**Tasks**
- Create the project root and directory structure with placeholders (`.gitkeep`, `__init__.py`).
- Initialize a local Git repository (no remote, commit, or push).
- Write `README.md`, `CLAUDE.md`, `.gitignore`, `.env.example`.
- Write `docs/PROJECT_CONTEXT.md`, `ROADMAP.md`, `DECISIONS.md`, `PROGRESS_LOG.md`, `ARCHITECTURE.md`, `UI_DESIGN_SPEC.md`.

**Completion criteria**
- All required directories and documentation files exist at the correct project root.
- No unrelated files outside the project root were modified.
- `.gitignore` covers secrets, Python/Node artifacts, caches, logs, generated evaluation output, and local tracking data, and does not ignore `evaluation/datasets/`.
- `.env.example` contains only placeholders and comments.
- Documentation is consistent on architecture, stack, status, and stage numbering.
- No application functionality, dependency installation, Dockerfiles, or workflows were created.

## Stage 2 — Backend RAG pipeline and API

**Tasks**
- Resolve U-001 to U-007 (backend-related) and record them in `DECISIONS.md`.
- Typed settings from environment; FastAPI app with health endpoint.
- Ingestion: PDF/TXT extraction with page tracking, upload validation, overlapping chunking with metadata.
- Embeddings behind an interface; Qdrant collection management and upsert.
- Retrieval with similarity search and an evidence-sufficiency check.
- Generation: evidence-constrained prompt, LLM call, citation mapping, safe fallback.
- Endpoints for document upload, document listing/status, deletion, and querying.
- pytest + httpx tests using fakes for external providers.

**Completion criteria**
- A PDF and a TXT file can be uploaded, indexed in Qdrant, and listed with status.
- A question about indexed content returns an answer with document/page references.
- A question with no supporting evidence returns the safe fallback.
- Tests execute and pass locally; the commands and results are recorded.
- No secrets in tracked files; new variables documented in `.env.example`.

**Verification (2026-10-12)** — each criterion checked; details and commands in `PROGRESS_LOG.md`.
- Upload/index/list: PDF and TXT ingested into Qdrant and listed via `GET /documents`, in API tests and against the running server. Met.
- Cited answer: real `qwen3.5:9b` answers through the running API cited the correct document and PDF page (e.g. `handbook.pdf` p. 2 and p. 3). Met.
- Safe fallback: unrelated questions returned the fallback without calling the LLM (`below_threshold`, `no_results`); related-but-unanswerable questions returned it via `model_declined`. Met.
- Tests: `pytest` — 114 passed, plus 1 opt-in real-Ollama test passed separately (`pytest -m ollama`); ruff and mypy (strict) clean. Met.
- Secrets: secret-pattern scan found only obvious test placeholders; `.env.example` documents all new variables with placeholder/default values. Met.

## Stage 3 — Frontend application and backend integration

**Tasks**
- Initialize the Vite + React + TypeScript + Tailwind app; implement design tokens from `UI_DESIGN_SPEC.md`.
- Application shell, navigation, and the Document Workspace (upload, indexed documents, Q&A, cited sources) wired to the Stage 2 API.
- Evaluation, Experiments, and Pipeline views built with honest empty states ("no evaluation runs yet") until their data sources exist in Stages 4–7. No fabricated metrics.
- Pipeline visualization (3D with reduced-motion and non-3D fallback), lazy-loaded.

**Completion criteria**
- The workspace works end-to-end against the real backend: upload, status, ask, read cited evidence, see fallback.
- Loading, empty, success, and error states exist for every data-driven component.
- The UI meets the acceptance criteria in `UI_DESIGN_SPEC.md` §15 (responsive, keyboard-accessible, contrast, reduced motion, no prohibited patterns).
- Type-check and build succeed; commands and results recorded.

**Verification (2026-10-13)** — details in `PROGRESS_LOG.md`.
- End-to-end in Chrome against the real backend and `qwen3.5:9b`: PDF and TXT uploaded and listed, questions answered with citations resolving to the right document and page, cross-document answer, fallback shown, Evidence Trace (3D and 2D) inspected, document deleted and list matched the server. Met.
- States: loading, empty, success, and error states exist for health, document list, upload, delete, query, evidence, and trace, and are covered by tests (including backend unreachable, generation unavailable, rejected upload, failed request vs. fallback). Met.
- `UI_DESIGN_SPEC.md` §15: tokens central (Tailwind defaults removed); real backend for the workspace and honest planned views for the rest; no horizontal overflow at 360/768/1024/1440 px; keyboard operation (skip link, tab stepper with arrows/Home/End, native controls) and visible focus; contrast checked by an automated test and Lighthouse (accessibility 100 in light and dark); reduced motion and no-WebGL use the 2D trace (tested); 3D chunk lazy-loaded; no prohibited patterns; illustration labelled. Citation markers resolve to document, page, and passage; sub-span highlighting is not possible with the API's data (recorded in `UI_DESIGN_SPEC.md` §16, D-037). Met with that recorded refinement.
- `tsc -b` (strict), ESLint, Vitest (40 tests), and `vite build` pass; backend regression suite passes (115). Met.

## Stage 4 — Evaluation dataset, metrics, and evaluation runner

**Tasks**
- Select licence-compatible source documents; write the fixed dataset (questions, reference answers, expected sources), including unanswerable questions.
- Implement metrics per P-003 and the evaluation runner using the shared pipeline.
- LLM judge as a supplementary metric (U-009).
- Run and record a baseline; propose thresholds (U-010) with justification.
- Expose evaluation results via the API; connect the Evaluation view to real results.

**Completion criteria**
- The runner executes end-to-end on the dataset and writes results with configuration and dataset version.
- A measured baseline is recorded in `PROGRESS_LOG.md`; thresholds are documented and version-controlled.
- Failed cases are inspectable individually in the UI.

## Stage 5 — MLflow experiment tracking and result comparison

**Tasks**
- Resolve U-011; log evaluation runs to MLflow with parameters, configuration, dataset version, metrics, and per-case artifacts.
- Expose run history and comparison through the API; connect the Experiments view.

**Completion criteria**
- At least two real runs with different configurations are logged and comparable in MLflow and in the Experiments view.

## Stage 6 — Docker and Docker Compose integration

**Tasks**
- Dockerfiles for backend and frontend; Docker Compose with Qdrant (and MLflow if self-hosted).
- Configuration via environment; health checks; persistent volumes for local data.

**Completion criteria**
- `docker compose up` starts the full stack from a clean checkout plus `.env`, and the workspace flow works end-to-end in containers.

## Stage 7 — GitHub Actions testing and automated quality gate

**Tasks**
- Resolve U-012, U-013, U-014.
- Workflow: install, lint/type-check, API tests, evaluation suite, quality gate, then image build (and further release stages, as configured) dependent on the gate.
- Report gate results on the workflow run; connect the Pipeline view to real CI data (U-015).

**Completion criteria**
- A passing change proceeds to image build.
- A deliberately degraded change fails the gate and the build/release jobs do not run.
- Both outcomes are demonstrated and recorded.

## Stage 8 — End-to-end integration, verification, documentation, and demonstration preparation

**Tasks**
- Full end-to-end verification across all paths (live query, evaluation, release).
- UI review against `UI_DESIGN_SPEC.md` acceptance criteria.
- Final documentation: setup, usage, architecture, limitations.
- Demonstration script and any demonstration data, clearly labelled as such.

**Completion criteria**
- All three flows verified and recorded; documentation matches the delivered system; known limitations listed.

---

## Optional extensions (not scheduled)

- Kubernetes deployment
- Canary deployment
- Advanced monitoring and alerting

These require a recorded decision in `DECISIONS.md` before work begins.
