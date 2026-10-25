# CLAUDE.md — Working Rules for RAGGuard

RAGGuard is a quality-gated Retrieval-Augmented Generation (RAG) application. Users upload PDF/TXT documents and ask questions; answers are grounded in retrieved evidence and cite their sources. Its defining feature is an offline evaluation suite and CI/CD quality gate that blocks releases when measured quality falls below documented requirements.

These rules are mandatory for every Claude Code session working in this repository.

## Before starting any work

1. Read, in this order:
   - `CLAUDE.md` (this file)
   - `docs/SESSION_HANDOFF.md` — the current handoff (status, open issues, manual acceptance, next steps)
   - `docs/PROJECT_CONTEXT.md` — concise current state
   - `docs/ROADMAP.md` — stage status and completion criteria
   - `docs/DECISIONS.md` — confirmed, planned, and unresolved decisions
   - the most recent entries of `docs/PROGRESS_LOG.md`
2. When the work touches system design, also read `docs/ARCHITECTURE.md`.
3. When the work touches the frontend, also read `docs/UI_DESIGN_SPEC.md` in full.

## Mandatory working rules

1. **Stage discipline.** Work only on the explicitly requested stage and respect its completion criteria in `docs/ROADMAP.md`. Do not begin the next stage without explicit instruction.
2. **No silent scope changes.** Do not expand scope, change an approved technology, or contradict the documented architecture. If a change is genuinely needed, stop, explain why, and record it in `docs/DECISIONS.md` (under "Changes to previous decisions") once approved.
3. **Inspect before editing.** Read existing code before changing it. Preserve working functionality and avoid unnecessary rewrites.
4. **Synchronize documentation after every implementation prompt or stage.** Review `docs/PROJECT_CONTEXT.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`, and `docs/PROGRESS_LOG.md`. Record meaningful changes; when a document was reviewed and needs no substantive update, say so explicitly in the progress log entry.
5. **Record what actually happened.** Each progress log entry lists the files changed, commands run, verification results, failures, blockers, unresolved decisions, and the next recommended action.
6. **No unverified claims.** Never claim a test, build, or check passed unless it was actually executed and succeeded. If something was skipped, say so.
7. **Completion criteria are checked, not assumed.** Do not mark a stage complete until each of its completion criteria has been verified.
8. **Minimal, maintainable code.** Keep the implementation small, typed where appropriate (Python type hints + Pydantic, TypeScript strict mode), secure, and consistent with existing code.
9. **No secrets in Git.** Never place credentials, real API keys, personal data, or machine-specific secrets in tracked files. Use `.env` (ignored) and document new variables in `.env.example` with placeholder values only. Do not read real credential files unless strictly necessary.
10. **One source of truth per kind of information.**
    - `PROJECT_CONTEXT.md` — concise current-state reference
    - `ROADMAP.md` — stage status and completion criteria
    - `DECISIONS.md` — decision record
    - `PROGRESS_LOG.md` — chronological history (append-only; never rewrite or invent past entries)
    Avoid conflicting copies of the same information; link instead of duplicating.
11. **Git hygiene.** Do not add remotes, commit, or push unless explicitly asked.
12. **Isolated verification.** Automated tests must not call Gemini or require a running Ollama (the real-Ollama test is opt-in: `pytest -m ollama`) or an MLflow server (use a temporary SQLite tracking URI). Smoke tests and scripts use a temporary `QDRANT_LOCAL_PATH` and collection, never the developer's `qdrant_storage/`; embedded Qdrant allows only one process per storage folder. Real evaluation runs log to the local `mlflow.db`; never log secrets or `.env` values to MLflow (parameters are whitelisted in `backend/app/tracking/mlflow_tracking.py`). The API's dashboard endpoints only read the tracking store and `evaluation/results/` (`tracking/reader.py`, `evaluation/results.py`): never write to, delete from, or create a store from the API, never import MLflow on the query path, and never return secrets, unwhitelisted tags, or absolute paths. Dashboard tests use temporary results directories and tracking stores.
13. **Frontend scope (D-046, amended by D-053).** Stage 5.5 lifted the freeze for functional integration: the conversation provider and the Evaluation, Experiments, and Pipeline views exist and may be maintained or fixed in the **current** design language (tokens, shell, Evidence Trace, themes, accessibility). The larger **visual redesign** — new visual direction, restyling, new screens beyond these views, or new frontend dependencies — stays deferred until the owner supplies visual references and asks for it. Backend work must keep the frontend operational, and the frontend must show only real data.

## Architecture invariants

- The **live query path** (user question → retrieval → generation → cited answer or safe fallback) and the **evaluation path** (fixed dataset → pipeline → metrics) share the same RAG pipeline code. Evaluation never runs per user query.
- The evaluation runner (`backend/app/evaluation/`) calls `RAGPipeline.ingest` / `retrieve_evidence` / `generate_answer` and indexes its corpus only into a temporary Qdrant store it creates and deletes; it never re-implements retrieval or generation and never opens the application's store.
- The **release path** (code change → GitHub Actions → tests + evaluation gate → image build/release) blocks *new* releases on failure; it must not take down the currently healthy deployment.
- Answers must cite sources (document and page where available). When evidence is insufficient, return the documented safe fallback instead of guessing.
- An LLM judge is a supplementary evaluator, never the sole source of truth.
- Retrieved documents and user questions are untrusted input. Keep the layered prompt-injection mitigations (`ARCHITECTURE.md` §3c, D-049, D-069, D-071 — including span withholding and the answer check with at most one repair); do not remove a layer or claim immunity based on passing synthetic tests. An answer is returned as grounded only if it passes the answer check; supersession is decided only from explicit replacement statements inside the selected documents (D-070). Keep the `/query` response contract unchanged unless the frontend is changed with it (its validator accepts only the three existing `fallback_reason` values).
- Quality thresholds are set only after a measured baseline exists, and live in version control.
- Deterministic checks are versioned (`EVALUATOR_VERSION` in `backend/app/evaluation/metrics.py`, D-068): any change to how a case is scored bumps it and is described with a re-scoring comparison; earlier reports are never rewritten, and a benchmark's content changes only with a version bump.
- Retrieval improvements stay general (D-063): no rules tied to a filename, document, page, heading, or question, and no forced inclusion of a passage. The retrieval threshold only has meaning for one score definition — any change to extraction, chunking, sub-units, the index, or the embedding model requires re-calibrating `MIN_RETRIEVAL_SCORE` on answerable, unanswerable, and unrelated questions of all four benchmarks (core, VEIL, structural, AgriSense). Lexical (hybrid) retrieval may only choose among chunks whose dense score passes the gate, and evidence is presented in dense-score order (D-064); region merging (D-072) may extend a passage's text but never changes scores, order, the gate, or the passage count. Never drop or silently replace an indexed collection that holds documents; older index formats must keep working until the owner re-uploads.
- Conversations are scoped to a document context (D-065): never show a thread as belonging to documents it was not held with, never delete a thread without the user's confirmation, and never send conversation history to the backend without an explicit, scoped design. The retrieval diagnostics endpoint (D-066) stays opt-in, read-only, and absent from the API by default.
- The **Docker deployment** (`compose.yaml`, `deployment/`; D-075–D-078): the browser talks only to the Nginx origin, which proxies the API (the bundle is built with an empty `VITE_API_BASE_URL`); the stack has its own Qdrant volume and never mounts or migrates the host's `qdrant_storage/`, `mlflow.db`, `mlartifacts/`, or `evaluation/results/`; evaluations in a container keep the embedded temporary store (never the Qdrant server); Compose passes an explicit allow-list of variables, never the host `.env` wholesale; images hold no data, secrets, or model weights; Ollama stays on the host. Never run `docker compose down -v`, `docker volume prune`, `docker system prune`, or any command that removes a data volume; use `docker compose down`. Do not start Docker Desktop on the owner's behalf; ask. Container smoke tests use only a synthetic document that they delete by its returned ID.
- The **CI quality gate** (D-079 to D-084, `.github/workflows/ragguard-ci.yml`) is offline and deterministic: it runs retrieval, evidence, security-exposure and supersession checks with the real embedding model and never a generation model, Ollama, Gemini, or a secret. Its thresholds live only in `evaluation/quality_gate.json` (`python -m app.evaluation.quality_gate`); they come from measured baselines, are never lowered to get a run green, and a change to a dataset, the retrieval configuration, the prompt, or the evaluator is re-measured and recorded (D-081). The gate fails closed and an LLM judge never decides it.
- In the workflow, `image-build` must `needs:` every check and the gate with the default success condition (no `always()`); images are built with `push: false` only: no registry login, release, or deployment without the owner's explicit request (U-020). Permissions stay `contents: read`, there is no `pull_request_target` and no secret, third-party actions stay pinned to verified commit SHAs, and skipped tests count as failures. Hosted runs are never claimed as passed until a run actually exists.
- The Pipeline view reads GitHub's public API anonymously (D-083): never add a GitHub token to the frontend, bundle, or workflow.
- Frontend, 3D assets, and visualization code stay separate from backend logic.

## UI quality requirement (non-negotiable)

**The UI must look like a deliberately designed software product, not a generic AI-generated dashboard.** RAGGuard is a precision-oriented document intelligence and AI quality-assurance tool; the interface should communicate evidence, traceability, reliability, and engineering precision.

- Follow `docs/UI_DESIGN_SPEC.md` for palette, typography, components, layout, 3D usage, accessibility, and prohibited patterns.
- No purple-blue gradients, heavy glassmorphism, neon effects, decorative emoji, oversized headings on every screen, or repetitive card-grid dashboard templates.
- Use Lucide icons for interface controls; never substitute emoji.
- Three.js / React Three Fiber is reserved for the specified pipeline visualization, with reduced-motion support, keyboard access, and a non-3D fallback.
- Never fabricate live metrics, evaluation results, or CI statuses. Any sample data must be visibly labelled as demonstration data.
- A UI is not complete because a page renders. It is complete when it meets the acceptance criteria in `docs/UI_DESIGN_SPEC.md`, is responsive and accessible, and is connected to real backend functionality.
