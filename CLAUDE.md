# CLAUDE.md — Working Rules for RAGGuard

RAGGuard is a quality-gated Retrieval-Augmented Generation (RAG) application. Users upload PDF/TXT documents and ask questions; answers are grounded in retrieved evidence and cite their sources. Its defining feature is an offline evaluation suite and CI/CD quality gate that blocks releases when measured quality falls below documented requirements.

These rules are mandatory for every Claude Code session working in this repository.

## Before starting any work

1. Read, in this order:
   - `CLAUDE.md` (this file)
   - `docs/PROJECT_CONTEXT.md` — concise current state, including its "Next Session Handoff" section
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
12. **Isolated verification.** Automated tests must not call Gemini or require a running Ollama (the real-Ollama test is opt-in: `pytest -m ollama`). Smoke tests and scripts use a temporary `QDRANT_LOCAL_PATH` and collection, never the developer's `qdrant_storage/`; embedded Qdrant allows only one process per storage folder.

## Architecture invariants

- The **live query path** (user question → retrieval → generation → cited answer or safe fallback) and the **evaluation path** (fixed dataset → pipeline → metrics) share the same RAG pipeline code. Evaluation never runs per user query.
- The **release path** (code change → GitHub Actions → tests + evaluation gate → image build/release) blocks *new* releases on failure; it must not take down the currently healthy deployment.
- Answers must cite sources (document and page where available). When evidence is insufficient, return the documented safe fallback instead of guessing.
- An LLM judge is a supplementary evaluator, never the sole source of truth.
- Quality thresholds are set only after a measured baseline exists, and live in version control.
- Frontend, 3D assets, and visualization code stay separate from backend logic.

## UI quality requirement (non-negotiable)

**The UI must look like a deliberately designed software product, not a generic AI-generated dashboard.** RAGGuard is a precision-oriented document intelligence and AI quality-assurance tool; the interface should communicate evidence, traceability, reliability, and engineering precision.

- Follow `docs/UI_DESIGN_SPEC.md` for palette, typography, components, layout, 3D usage, accessibility, and prohibited patterns.
- No purple-blue gradients, heavy glassmorphism, neon effects, decorative emoji, oversized headings on every screen, or repetitive card-grid dashboard templates.
- Use Lucide icons for interface controls; never substitute emoji.
- Three.js / React Three Fiber is reserved for the specified pipeline visualization, with reduced-motion support, keyboard access, and a non-3D fallback.
- Never fabricate live metrics, evaluation results, or CI statuses. Any sample data must be visibly labelled as demonstration data.
- A UI is not complete because a page renders. It is complete when it meets the acceptance criteria in `docs/UI_DESIGN_SPEC.md`, is responsive and accessible, and is connected to real backend functionality.
