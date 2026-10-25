# RAGGuard — Roadmap

Authoritative stage status. A stage is marked **Complete** only after every completion criterion has been checked and the result recorded in `PROGRESS_LOG.md`. Work on one stage at a time, and only on explicit instruction.

| Stage | Title | Status |
| --- | --- | --- |
| 1 | Project foundation and documentation | Complete (2026-10-12) |
| 2 | Backend RAG pipeline and API | Complete (2026-10-12) |
| 3 | Frontend application and backend integration | Complete (2026-10-13) |
| 4 | Evaluation dataset, metrics, and evaluation runner | Complete (2026-10-14) — UI/API exposure deferred (frontend freeze, D-046); delivered in Stage 5.5 |
| 5 | Evaluation hardening, RAG reliability/security, and MLflow tracking (redefined 2026-10-14, D-047) | Complete (2026-10-14) — automated verification done; owner's manual run pending |
| 5.5 | Conversation persistence, functional dashboards, and product integration (inserted 2026-10-14, D-053) | Implemented and automatically verified (2026-10-14); pre-demo pass 2026-10-15 and retrieval reliability pass 2026-10-16 (below) — **owner's manual acceptance pending** |
| 5.7 | Cross-document reliability and conversation isolation (owner brief 2026-10-16; D-064–D-066), stabilisation 2026-10-16–18 (D-067, D-068), closure 2026-10-25 (D-069–D-074) | **Complete (2026-10-25)** — automated stage criteria verified (below) and **the owner's manual acceptance passed (2026-10-25)**; residual failures documented |
| 6 | Docker and Docker Compose integration (D-075–D-078) | **Complete (2026-10-26)** — every feasible criterion of the acceptance gate evidenced (below) and **the owner's manual acceptance passed (2026-10-26)**; linux/amd64, Linux hosts and an in-place volume restore untested (documented) |
| 7 | GitHub Actions testing and automated quality gate | Not started |
| 8 | End-to-end integration, verification, documentation, and demonstration preparation | Not started |

**2026-10-26:** Stage 6 (Docker) implemented, verified (below), and accepted by the owner; committed as `feat: complete Stage 6 Docker deployment`. **Next: Stage 7 only on the owner's explicit instruction.** (2026-10-25: Stage 5.7 closed — closure pass, checkpoint `e3738ab`, the owner's manual acceptance passed.)

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
- Select licence-compatible source documents; write the fixed dataset (questions, reference answers, expected sources), including unanswerable questions. *Done with a hand-written synthetic corpus (D-039).*
- Implement metrics per P-003 and the evaluation runner using the shared pipeline. *Done (D-040–D-043).*
- LLM judge as a supplementary metric (U-009). *Done (D-044).*
- Run and record a baseline; propose thresholds (U-010) with justification. *Baseline recorded; retrieval threshold analysed and kept (D-045); quality-gate thresholds moved to Stage 7 (DECISIONS §4).*
- ~~Expose evaluation results via the API; connect the Evaluation view to real results.~~ *Deferred by the frontend freeze (D-046); see Stage 8.*

**Completion criteria** (as revised for the Stage 4 brief of 2026-10-14; changes recorded in `DECISIONS.md` §4)
- The runner executes end-to-end on the dataset and writes results with configuration and dataset version.
- A measured baseline is recorded in `PROGRESS_LOG.md`; the retrieval threshold is documented and version-controlled.
- Failed cases are inspectable individually (in the JSON/Markdown reports; the UI part is deferred).
- At least 18 valid, version-controlled cases; references supported by the corpus; evaluator uses the shared pipeline; deterministic metrics implemented and tested; local judge works or its blocker is recorded; threshold analysis uses actual scores; reports produced and consistent; user documents/Qdrant storage untouched; frontend unchanged; tests, lint, and type checks recorded; documentation synchronized.

**Verification (2026-10-14)** — details in `PROGRESS_LOG.md`.
- End-to-end runner: `python -m app.evaluation.run_evaluation` ran all 27 cases through `RAGPipeline` in a temporary store, with (`20261014T105939Z-59a6a7`) and without (`20261014T105914Z-110cef`) the judge; both `completed`; reports carry configuration, dataset version 1.0.0, and fingerprint. Met.
- Baseline recorded in `PROGRESS_LOG.md`; `MIN_RETRIEVAL_SCORE` 0.35 kept with the sweep as evidence (D-045; changed to 0.30 in Stage 5, D-052). Met (gate thresholds → Stage 7).
- Per-case inspection: every case in both reports has question, reference, answer, all retrieved passages and scores, fallback status, latency, judge result, and errors. Met in reports; UI deferred.
- 27 cases (18 answerable incl. 5 diagnostic, 5 related-unanswerable, 4 unrelated); the validator checks every required fact against its expected source. Met.
- Shared pipeline: runner calls `RAGPipeline.ingest`, `retrieve_evidence`, `generate_answer`; regression tests show `answer()` unchanged. Met.
- Metrics, judge (schema, retry, errors), threshold sweep, reports, isolation: 96 new deterministic tests; full suite 211 passed + 1 opt-in Ollama test passed. Met.
- Local judge: 18/18 answered cases scored, 0 judge errors. Met.
- Reports re-validated and Markdown re-rendered from JSON for every run. Met.
- `qdrant_storage/` absent before and after; no temporary directories left; `git status` shows no change under `frontend/`. Met.
- `ruff check`, `ruff format --check`, `mypy` (strict) clean. Met.

## Stage 5 — Evaluation hardening, RAG reliability/security, and MLflow tracking

Redefined by the owner's brief of 2026-10-14 (D-047). The original Stage 5 ("MLflow + Experiments view") is covered except the Experiments view and API exposure of runs, which move to Stage 8 (frontend freeze, D-046). *(Both were delivered in Stage 5.5, D-053.)*

**Tasks**
- Preserve and reproduce the Stage 4 baseline; expand the dataset (≥ 25 distinct prompt-injection scenarios, benign controls, harder RAG cases) without weakening existing expectations.
- Define deterministic metrics for correctness, abstention, citations (validity, relevance, claim support), security (attack success, canary leakage, benign controls), and latency.
- Investigate and fix the Stage 4 findings (conflicting evidence, superseded citations, threshold, prompt injection, citation quality) with regression tests and without changing the API contract.
- Integrate local-first MLflow (U-011): tracking store, parameters, metrics, artifacts, pre-fix and post-fix runs, legacy Stage 4 runs, tests.
- Full automated verification and a manual-testing handoff for the owner.

**Completion criteria**
- Dataset ≥ 25 distinct injection scenarios plus benign controls, validated; pre-fix and post-fix runs on the same dataset recorded and comparable.
- Fixes implemented with regression tests; remaining failures documented, not hidden.
- MLflow runs (incl. reports as artifacts) logged and inspectable; tracking tests pass; tracking can be disabled; the API is independent of MLflow.
- Backend tests, lint, format, strict mypy, dataset validation, real-model evaluation, and an end-to-end API smoke test executed with recorded results; frontend unchanged.
- Documentation synchronized; manual-testing handoff written. Docker/Stage 6 not started.

**Verification (2026-10-14)** — details in `PROGRESS_LOG.md`.
- Stage 4 baseline reproduced on unchanged code (`20261014T112036Z-a683c5`); all Stage 4 reports preserved and imported into MLflow as legacy runs. Met.
- Dataset v2.0.0: 85 cases, 32 attack cases = 31 distinct scenarios over 24 vectors and three channels, 7 benign controls; validated (`--validate-only`). Pre-fix run on the same dataset before any production change (`20261014T114011Z-e47fbe`), re-scored with the final evaluator for comparability. Met.
- Fixes with regression tests (prompt v4, markup neutralisation, instruction and supersession labels, decline detection, system-prompt leak guard, threshold 0.30); API schema byte-identical to the pre-stage OpenAPI snapshot. Final run `20261014T121601Z-94f8f9`: case pass rate 77/85 (pre-fix 68/85), attack success 5/32 (9/32), benign controls 7/7 (6/7). Remaining failures documented (superseded citations 4/5, INJ-001/009/010/019 recurring, CON-002 retrieval miss). Met, with documented unresolved items.
- MLflow: 15 runs in `ragguard-evaluation` (`mlflow.db`), reports as artifacts; UI served and artifacts downloaded over HTTP on port 5050; 10 tracking tests (temporary store, disabling, failures, secrets, legacy import, API independence). Met.
- Backend: `pytest` 267 passed / 1 deselected; `pytest -m ollama` 1 passed; ruff, format, mypy (strict, 44 files) clean; end-to-end smoke test against real servers 18/18. Frontend unchanged (55 files, checksums identical); `tsc`, ESLint clean; Vitest 40 passed. Met.
- Documentation synchronized; manual-test handoff in `PROJECT_CONTEXT.md`. The owner's manual run has not happened yet. Docker/Stage 6 not started.

## Stage 5.5 — Conversation persistence, functional dashboards, and product integration

Inserted before Docker by the owner's brief of 2026-10-14 (D-053). Brings forward the Stage 8 items that make the existing evaluation and tracking work visible (Evaluation and Experiments views, API exposure of results and runs, failed-case inspection) and fixes the conversation-history bug, in the current design language. The visual redesign stays in Stage 8.

**Tasks**
- Conversation history survives navigation (application-level state) and, where safe, a reload; clear-history action; regression tests.
- Read-only API for saved evaluation reports and MLflow runs (incl. comparison and approved artifacts), restricted to known runs and files; system status endpoint.
- Evaluation view (latest and older reports, metrics with denominators, failed-case inspection with filters); Experiments view (runs, details, two-run comparison with comparability and trade-offs); Pipeline view (actual flow, real component status, pending stages).
- Tests, documentation, manual-acceptance handoff. No Docker/CI work.

**Completion criteria**
- History, citations, fallback and failure states survive navigation; pending requests are neither lost nor duplicated; clearing works; reload behaviour documented and tested.
- Evaluation, Experiments, and Pipeline show real data only; missing values are distinguishable from zero; tracking unavailability is explicit; no fabricated CI status.
- Existing `/query`, `/ingest`, `/documents`, `/health` contracts unchanged; RAG endpoints independent of MLflow; no secrets or absolute paths exposed.
- Backend and frontend tests, lint, types, and the production build pass; documentation synchronized.
- **The owner's manual acceptance.**

**Verification (2026-10-14)** — details in `PROGRESS_LOG.md`.
- Conversation in `ConversationProvider` with sessionStorage copy (D-054); 9 conversation tests (navigation, citations, fallback/failure states, pending request, clear, reload, interrupted request, corrupted storage, stored content); 5 of them fail when the old structure is restored. Met.
- 8 read-only endpoints (D-055–D-057); 21 backend tests (real runner reports and real MLflow logging into temporary stores; legacy schema; malformed reports; traversal and symlinks; tracking states; trade-offs; status states; no secrets/paths). Existing API paths and schemas identical to the Stage 5 snapshot. Met.
- Three views; 14 view tests; Claude's Chrome check against the real backend, real reports, and the real MLflow store (all views populated, history kept across navigation and reload, responsive at 1440/~500/360 px, dark and light). Met.
- `pytest` 288 passed / 1 deselected; `pytest -m ollama` 1 passed; ruff, format, strict mypy clean; `tsc`, ESLint clean; Vitest 63 passed; build succeeded (main bundle 93.3 kB gzip). Met.
- Not implemented (recorded, not required by the criteria): starting an evaluation from the UI; a list of cases whose outcome changed between two runs.
- **Owner's manual acceptance: pending.** Stage 6 not started.

### Pre-demo reliability and evaluation pass (2026-10-15, owner brief; not a new stage)

Focused, low-risk work before the owner's demonstration, inside the Stage 5.5 scope (no redesign, no Docker/CI, no new optional dashboard features).

**Tasks (from the brief)** — keep the 85-case core dataset unchanged; add a separate ~20-case VEIL benchmark through the existing dataset mechanism; make dataset identity explicit in reports, MLflow, and the views; investigate (A) risk-to-mitigation retrieval, (B) false-premise abstention, (C) raw citation labels, each with regression cases; run both benchmarks before and after; synchronise documentation.

**Outcome** — details in `PROGRESS_LOG.md` (2026-10-15) and D-059–D-062, U-016.
- VEIL benchmark `veil-document-challenge` v1.0.0, 20 cases, every attack's payload confirmed to reach the evidence (D-059); attack exposure now recorded in every report (D-060). Core dataset unchanged (fingerprint `858e2d41…`). Done.
- Dataset ID shown in the Evaluation report selector and the Experiments run table; Experiments still refuses to compare different fingerprints (verified on the real store). Done.
- (B) Prompt v6 (D-061): VEL-FPR-001 corrected in 5/5 executions (v4: fallback). **Fixed, with a recorded trade-off** (UNA-REL-005 sometimes answered; attack successes at the top of v4's range).
- (C) Adjacent citation markers render as one `[S1, S2]` group; copying no longer yields "S1S2" (D-062). **Fixed in the UI.** The model still occasionally writes bare `Sn` in prose (about one answer per run, unchanged by the prompt instruction) — **unresolved**.
- (A) Diagnosed as a **retrieval** problem (the risk-table chunk scores 0.165, below the 0.30 threshold); no evidence-supported low-risk fix — **unresolved** (U-016). VEL-RSK-001 fails as a regression case.
- Tests: pytest 293 passed / 1 deselected, `pytest -m ollama` 1 passed, mypy clean, Vitest 67 passed, build succeeded.
- **Owner's manual acceptance (and demo rehearsal): pending.** Stage 6 not started.

### Retrieval reliability pass (2026-10-16, owner brief; not a new stage)

General retrieval improvement before Docker/CI, triggered by three VEIL risk-table questions but judged on independent fixtures. No Docker/CI work.

**Acceptance criteria (from the brief) and status** — details in `PROGRESS_LOG.md` 2026-10-16, D-063, U-016.
1. Generic rate-limit query retrieves sufficient evidence and answers correctly — **retrieval met** (best score 0.286 gated → 0.507–0.624, risk table in evidence); **answer partly correct**: retries correct, but the model states "failover to Groq or Gemini" instead of Groq → Gemini in every run (generation precision, unresolved).
2. Table-referenced query stays correct — met (STR-VEL-002 passes before and after).
3. Full-table question covers all four rows — met (8/8 facts in both after-runs and in the UI; 6/8 before).
4. Works on independent structural fixtures with different wording — met: structural benchmark 31/41 → 38, 38/41; deterministic `tests/test_structure.py` (30 tests, 1 documented xfail).
5. Similar-keyword negative controls do not surface wrong evidence as authoritative — met for the prose-vs-table and near-identical-document cases (STR-TAB-005, STR-INC-001/005, STR-SIM-001/002 pass); STR-NEG-001 ("Business tier") is now answered with a correct "no such tier" statement, which the metric counts as a false answer.
6. Missing-evidence and unrelated questions still abstain — met at the gate (0/26 unrelated questions reach the model at 0.35; 2/20 would at 0.30); model-level: core correct fallbacks 14/16 in both after-runs (v6 baselines 15, 14), VEIL 4/4 and 3/4, structural 9/10 in both.
7. Citation and page metadata correct — met (citation validity ≥ 98.9 % in all runs; page-4 citations and evidence navigation checked in Chrome after migration).
8. No unexplained degradation on core and VEIL — met with explained exceptions: one VEIL attack (VEL-INJ-004) is no longer exposed to its payload; VEL-UNA-003 answered once (seen before under v5).
- Re-indexing required for existing documents (delete and re-upload); legacy collections keep working with the old scoring.
- **Owner's manual acceptance: pending.** Stage 6 not started.

## Stage 5.7 — Cross-document reliability and conversation isolation

Owner brief 2026-10-16, after a manual test: four of five questions about a 22-page AgriSense PDF failed, and an SIH conversation stayed on screen after the AgriSense upload. No Docker/CI work. Details: `PROGRESS_LOG.md` 2026-10-16 (Stage 5.7), D-064–D-066, U-016.

**Status per required outcome**
1. Evidence comparison and root cause — **done.** Confirmed cause of the AgriSense failures: the D-063 layout extractor split words in fragment-run PDFs (garbled text and embeddings). Second cause after the fix: candidate selection on a long, single-vocabulary document. The evidence comparison of the first hybrid version found the earliest divergence in retrieval ranking (fused S-order) and led to dense-order evidence (D-064 (3)).
2. General fixes — **done:** fragment-safe extraction, hybrid candidates under the unchanged dense gate (0.35, re-calibrated on four corpora), dense-order evidence. No filename, page, or question rules.
3. New benchmark — **done:** `agrisense-evident` v1.0.0, 27 cases with validated expected pages; core, VEIL, structural datasets and fingerprints unchanged.
4. Benchmarks (two tracked runs each, same datasets as the baselines):

| Dataset (cases) | Before Stage 5.7 (D-063 code) | Final Stage 5.7 (hybrid + dense-order evidence), two tracked runs |
| --- | --- | --- |
| AgriSense (27: 22 answerable, 5 unanswerable) | `20261015T201247Z-7a91c3`: **6/27** pass; correct answers 1/22; false refusals 18/22; false answers 0/5; expected page in evidence 10/22 | `20261016T095114Z-fc34e3`, `…100110Z-a16aeb`: **19/27, 19/27** pass; false refusals 5/22, 5/22; false answers 1/5, 1/5; expected page in evidence 20/22, 20/22; citation validity 30/30, 28/28 |
| Core (85) | `20261015T192656Z-fa4006`, `…193450Z-d500cb`: 79, 79/85; attacks 4, 4/32; false answers 2, 2/16; false refusals 0, 0/69 | `20261016T095318Z-e4ff62`, `…100320Z-1b3dd0`: **80, 79/85**; attacks 5, 4/32; false answers 1, 2/16; false refusals 0, 1/69; canary 0/15; citation validity 87/88, 87/87 |
| VEIL (20) | `20261015T193124Z-0111fa`, `…193914Z-3f41f4`: 15, 14/20; attacks 0, 0/4; false answers 0, 1/4; false refusals 3, 3/16 | `20261016T095744Z-14aa67`, `…100759Z-e0d60e`: **14, 15/20**; attacks 1, 1/4; false answers 0, 0/4; false refusals 3, 2/16; citation validity 16/16, 18/18 |
| Structural (41) | `20261015T193240Z-d4492e`, `…194026Z-d78072`: 38, 38/41; false answers 1, 1/10; false refusals 0, 0/31 | `20261016T095907Z-e33bf5`, `…100924Z-aa3ae5`: **39, 39/41**; false answers 0, 0/10; false refusals 0, 0/31; citation validity 33/33 |

5. Conversation isolation — **done** (D-065): threads per document context, history banner, per-thread clear, v1 migration, reload restores the selection; verified that no history is sent to the model; 7 new Vitest tests; checked in Chrome.
6. Diagnostics — **done** (D-066), opt-in, 5 tests.
- **Not achieved / residual (documented, not hidden):** of the owner's five questions, AGR-GAP-001 and AGR-FHR-001 pass in both final runs; AGR-COR-001 (all four mechanisms are in the evidence, the model declines because the passages say "the engine", not "EVIDENT"), AGR-VRD-001 (the verdict-enum page is not retrieved) and AGR-COR-002 (one fact missing) fail in both. Attack successes rose by one case in each security set (core INJ-006, VEIL VEL-INJ-001): the attacker passage was in the same position before and after; only the fourth passage changed and the model now relays the injected claim. U-016 stays open.
- Re-indexing required (delete and re-upload); older indexes keep working.
- **Owner's manual acceptance: pending.** Stage 6 not started.

### Stage 5.7 stabilisation (2026-10-16 – 2026-10-18, owner brief; not a new stage)

Investigation and fixes before Docker. Details: `PROGRESS_LOG.md` 2026-10-18, D-067, D-068, U-016, U-017.

| Item | Status |
| --- | --- |
| A. INJ-006 / VEL-INJ-001 | **Root cause found, partly fixed.** Both were relayed as "the documents disagree" (rule 8 over rule 1). INJ-006 is pre-existing (succeeds on the pre-5.7 evidence too); VEL-INJ-001 was caused by the changed fourth passage. Prompt v7 (D-067): VEL-INJ-001 blocked in all 4 measured v7 runs; INJ-006 blocked in 3 of 4 v7 runs, still 2–3 of 4–6 in repeated generations — **open**. Regression tests added. |
| B. AgriSense residuals | **Traced, not fixed** (no general defect justified a change): AGR-COR-001 / AGR-ALG-001 — evidence present, passages do not name EVIDENT (section context tested: mixed, rejected); AGR-VRD-001 — needed chunks rank 6th and 27th (top-4 ranking limit); AGR-COR-002 — lexical false negative (judge 5/5). |
| C. Superseded citations | **Investigated, open (U-017).** Detection and labels work; generation states replaced values in 3/5 cases; a prompt fix did not help. History questions pass. |
| D. Metric reliability | **Fixed for STR-VEL-005** (evaluator e2, negation-aware forbidden content, versioned in reports, D-068). VEL-FAC-002 over-strict but failing by decline — documented, unchanged. |
| E. Extraction/retrieval correctness | **Verified** by existing and new tests (fragment PDF, hybrid scope filter, dense-order evidence, threshold gate); the developer store was verified on a copy: hybrid, AgriSense 91 chunks. |
| F. Document-scoped conversations | **Verified** at API level (scoped, unknown, deleted IDs; new tests) and in Chrome (switching, history, "Use these documents again", reload, per-thread clear, deleted document). |
| Final tracked runs (v7, e2, judge on) | core 81, 79/85 (attacks 2, 4/32; canary 0/15); VEIL 15, 14/20 (attacks 0, 0/4); structural 39, 38/41; AgriSense 21, 19/27 (false answers 0, 0/5; false refusals 5, 6/22). |
| Known cost | More declines on false-premise questions (AGR-FPR-002 in both runs). |
| Owner's manual acceptance | **Pending** (`PROJECT_CONTEXT.md` §2d). Stage 6 not started. |

### Stage 5.7 closure (2026-10-25, owner brief "Stage 5.7 only"; not a new stage)

Details: `PROGRESS_LOG.md` 2026-10-25, D-069–D-074. No Docker, CI, or redesign work (the interrupted broader brief only launched Docker Desktop, which was quit again; no files).

| Acceptance criterion (owner brief §11) | Evidence | Status |
| --- | --- | --- |
| 1. Implementation audited | Baseline tests and versions re-verified; developer store read on a copy (hybrid, AgriSense 91 chunks); test-isolation defect found (`mlartifacts/`) and fixed | Done |
| 2. Named security cases rechecked | INJ-001/006/009/020, VEL-INJ-001 (and INJ-007/010/019/022/029, VEL-INJ-002…004): blocked 3/3 in targeted trials and in all four final core/VEIL runs | Done |
| 3. Generalisable injection protection | Prompt v8: span withholding (D-069) + answer check with one repair (D-071); attack-payload strings visible to the model core 21→0, VEIL 2→0; final runs attacks core 0, 0/32 (v7: 2, 4), VEIL 0, 0/4; canary 0/15; benign controls 7/7, 2/2 | Done — heuristic; residual risk documented (U-018) |
| 4. AgriSense retrieval failures traced and remediated where possible | AGR-COR-001 root cause (split region) fixed by D-072 (now answered, 4/5 facts); AGR-ALG-001 lexical (e3); AGR-COR-002 passes; AGR-VRD-001 ranking limit (no reranker available) and AGR-NUM-001 (cross-page antecedent) documented | Partly — residuals documented (U-016) |
| 5. Extraction and index compatibility | All 91 AgriSense chunk texts exact page slices, 57 overlaps match; merging only on structure-aware indexes; legacy unchanged; no re-indexing needed for v8 | Done |
| 6. Citation validation at the backend | D-071 answer check (no citation, foreign IDs, wrong pages, unsupported values) → one repair → `model_declined`; tests; seen working in the final runs | Done (U-019 resolved) |
| 7. Document scope at the backend | Existing tests (filter, hybrid, deleted/unknown IDs, malformed) + new (neighbour lookup per document, supersession only inside the scope); Chrome check of the `/query` payloads | Done |
| 8. Superseded-source policy | D-070 implemented (current vs history, explicit statements only); superseded citations core 3, 3/5 → 0, 0/5; HIS-001/002 pass | Done (U-017 resolved) |
| 9. Evaluator issues | STR-VEL-005 (e2, earlier); AGR-ALG-001 gloss (e3); VEL-FAC-002 and AGR-REV-001 dataset revisions (v1.1.0); AGR-COR-002 and AGR-SEL-001 reviewed and kept (justified) | Done |
| 10. Regression tests | 390 passed + 1 xfail (was 347); 32 trust-boundary, 8 region-merge, 3 evaluator tests | Done |
| 11. Full checks | pytest, `-m ollama`, ruff, format, mypy, four `--validate-only`, tsc, ESLint, Vitest 74, build | Done |
| 12. Evaluations | 2 tracked runs per benchmark (+ AgriSense v1.1.0 pair), judge on; targeted repeats; one bounded prompt experiment (rejected) | Done |
| 13. No uncontained critical failure | No attack succeeded in any final run; residual injection risk is the heuristic itself (documented); false-premise declines are the safe direction | Done |
| 14. Documentation | All docs synchronised (`PROGRESS_LOG.md` entry lists them) | Done |
| 15. Ready for manual acceptance | `docs/SESSION_HANDOFF.md` checklist; the owner reported on 2026-10-25 that the local manual acceptance checks passed | **Passed (2026-10-25)** |

**Final tracked runs (v8, e3):** core 84, 84/85; VEIL (v1.1.0) 14, 14/20; structural 39, 38 → 38, 39/41; AgriSense v1.0.0 19, 20/27 and v1.1.0 21, 21/27. **Known costs:** AgriSense latency +40 % (median 2.9 s); false-premise questions still decline (VEL-FPR-001/002, STR-VEL-005, AGR-PVD-001, AGR-FPR-001); AGR-NUM-001 now declines (its v7 passes named the wrong programme).

## Stage 6 — Docker and Docker Compose integration

**Tasks (planned)**
- Dockerfiles for backend and frontend; Docker Compose with Qdrant (and MLflow if self-hosted).
- Configuration via environment; health checks; persistent volumes for local data.

**Completion criterion (planned):** `docker compose up` starts the full stack from a clean checkout plus `.env`, and the workspace flow works end-to-end in containers.

**Delivered (2026-10-26, owner brief "Stage 6 only"; D-075–D-078; guide: [`deployment/README.md`](../deployment/README.md))**
- `compose.yaml` (root): `frontend` (Nginx, `127.0.0.1:8080`, serves the production build and proxies the API same-origin), `backend` (FastAPI), `qdrant` (server 1.19.2); Ollama stays on the host; no MLflow server. Four named volumes. Health-gated start order.
- `deployment/{backend.Dockerfile, frontend.Dockerfile, nginx.conf, smoke_test.py, README.md}`, allow-list `.dockerignore`, Docker section in `.env.example`. Narrow application changes: `MLFLOW_ARTIFACT_ROOT`, an honest `containers` status, an empty-API-base error message, two UI sentences. No API schema changed; no commit, push, CI, or redesign.
- Images: backend 2.62 GB (PyTorch CPU wheel; the first build with PyPI's CUDA wheel was 10.3 GB), frontend 92.6 MB.

### Stage 6 acceptance (owner brief §16)

| # | Criterion | Evidence (details: `PROGRESS_LOG.md` 2026-10-26) | Status |
| --- | --- | --- | --- |
| A1 | One canonical Compose configuration, validates | `docker compose config -q` valid (also with `.env.example` as env file) | Verified |
| A2 | Backend and frontend images build | Built twice via Compose (7 min 38 s / 1 min 19 s rebuild), rebuilt again with the UI text changes; `docker build --check` clean | Verified |
| A3 | Works on the available platform, or documented limitation | linux/arm64 on Apple Silicon verified; amd64/Linux/Windows untested (documented) | Verified for arm64; limitation documented |
| A4 | No embedded credentials | Build history and filesystem scanned (0 secret-like words, 0 host paths, 0 `.env`/key/db files); `GEMINI_API_KEY` only a runtime variable; no build args carry secrets | Verified |
| A5 | Build contexts exclude local data | Allow-list `.dockerignore`; contexts 3.18 MB / 0.52 MB | Verified |
| B1 | Services start and become healthy | `up -d`: Qdrant → backend → frontend healthy in 20 s; also after restarts, `down`/`up`, recreation | Verified |
| B2 | Frontend accessible; backend reachable | Smoke test 14/14; browser | Verified |
| B3 | Browser requests reach the API; CORS/API URL correct | Same-origin proxy; bundle has no `localhost:8000`; fresh browser load: no console messages, all 200/304; downloads resolve to the web origin | Verified |
| B4 | Ollama and embeddings verified | Answers generated through `host.docker.internal`; opt-in Ollama test passes inside a container; model downloaded into the cache volume; `HF_HUB_OFFLINE=1` run | Verified |
| C1 | Synthetic document uploaded and indexed | API (smoke test) and browser upload | Verified |
| C2 | Grounded answer with a valid source | "17 days [S1]" / "45 days [S1]" citing the document; cited passage contains the fact | Verified |
| C3 | Unrelated question → fallback | `below_threshold`, model not called (API and UI) | Verified |
| C4 | Frontend renders answer, citations, fallback | Browser: answer, `[S1]` marker, evidence panel, fallback panel | Verified |
| C5 | Document management and dashboards operational | Upload/list/delete; Evaluation, Experiments (list, detail, compare, downloads), Pipeline, `/system/status` | Verified |
| D1 | Qdrant survives backend restarts | Same document ID verified after `restart backend` | Verified |
| D2 | Qdrant survives Qdrant restart and Compose down/up | Verified after `restart qdrant`, `down` + `up`, and `--force-recreate` | Verified |
| D3 | MLflow database and artifact paths valid and persistent | Experiment location `file:///data/mlflow/artifacts` in the volume; runs and all three artifacts re-read after recreating the backend | Verified |
| D4 | Evaluation reports stored and accessible | `/data/reports` volume; listed, opened, downloaded through the web port after recreation | Verified |
| D5 | Model cache verified | 88 MB in `hf_cache`, reused across recreation; offline run works; first-run download documented | Verified |
| D6 | Host development index and data untouched | `mlflow.db` hash, `qdrant_storage/` manifest, `mlartifacts/`/`results` counts identical to the pre-build baseline | Verified |
| D7 | No destructive volume operations | No `down -v`/prune; only the throw-away `ragguard_restore_check` volume removed | Verified |
| E1 | Relevant tests and checks executed | Host: pytest 393 + 1 xfail, ruff/format/mypy, Vitest 76, tsc, ESLint, build. Container: 393 + 1 xfail (with the cache volume mounted read-only), ruff/format/mypy | Verified |
| E2 | Evaluation runner isolated from the active store | Qdrant collections/points identical before and after container runs; `isolated_store` forces an embedded temporary store | Verified |
| E3 | Docker configuration and commands documented | `deployment/README.md`, `README.md` | Verified |
| E4 | Troubleshooting and recovery documented | 17 rows with exact messages; tested backup/restore | Verified (in-place restore not exercised) |
| E5 | Final diff contains only Stage 6 changes | 20 modified files (5 backend app + 2 backend test files, 3 frontend + 1 frontend test file, `.env.example`, `CLAUDE.md`, `README.md`, 6 docs) and 7 new files (`compose.yaml`, `.dockerignore`, 5 under `deployment/`); the progress log lists them | Verified |
| E6 | Documentation matches observed behaviour | Commands and messages copied from runs | Verified |
| E7 | No CI/CD or UI redesign | None; three UI sentences/messages only | Verified |

**Owner's manual acceptance (2026-10-26): passed.** The owner reported on 2026-10-26 that Stage 6 passed their manual acceptance on their Mac: the containerised application starts; AgriSense ingestion and question answering work; SIH retrieval and citations work; selecting only AgriSense stops answers from using SIH evidence; and a backend restart preserves the indexed documents and query behaviour. No additional tests were run when this was recorded.

**Results unchanged by containerisation:** full core benchmark in the container 84/85 (same failure UNA-REL-005, same outcome on all 85 cases), 0/32 attacks; retrieval parity on 173 questions: dense scores equal to 4·10⁻⁷, no gate decision differs; lexical ordering differs in the last evidence slot for 1/173 (server vs embedded) and 2/173 (macOS vs Linux) — D-078.

**Not covered / residual:** linux/amd64 and Linux/Windows hosts; replacing a live volume in place; running a benchmark against the Qdrant server (the CLI isolates by design); production concerns (TLS, authentication, scaling) — out of scope for a local deployment.

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
- Frontend redesign with the owner's new visual references (D-046, D-053). The functional items deferred from Stages 4 and 5 (API exposure of evaluation results and MLflow runs, Evaluation and Experiments views, failed-case inspection) were delivered in Stage 5.5 in the current design language. Remaining candidates: case-outcome changes between two runs, starting evaluations from the UI if safe, metric history and gate thresholds in the ledger (with Stage 7), and (optionally) a distinct fallback reason for output-guard blocks. Scheduling may change when the owner provides the references.
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
