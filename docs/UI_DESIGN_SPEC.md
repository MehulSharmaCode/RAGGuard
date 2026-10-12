# RAGGuard — UI Design Specification

> Stage 1 specification, **implemented in Stage 3** (2026-10-13) for the shell and the Document Workspace; Evaluation, Experiments, and Pipeline views show honest "planned" states until Stages 4–7 provide data. Token values below were the Stage 1 direction; the final, contrast-verified values live in `frontend/src/styles/tokens.css` (D-034). Where the implementation refines this spec, §16 says how and why.

**Governing requirement:** the UI must look like a deliberately designed software product, not a generic AI-generated dashboard.

---

## 1. Product identity

RAGGuard is a precision instrument for document intelligence and AI quality assurance. It should feel closer to a well-made engineering tool — a diff viewer, a lab notebook, a flight-data recorder — than to a chatbot or a marketing dashboard.

The visual language communicates four things:

| Quality | How the UI expresses it |
| --- | --- |
| **Evidence** | Source passages are first-class content, set in a reading typeface, with the exact supporting span highlighted. |
| **Traceability** | Every answer, metric, and verdict links back to where it came from: document/page, run ID, dataset version, commit. |
| **Reliability** | Calm, stable layouts; explicit states; nothing flashes or moves without reason. |
| **Engineering precision** | Hairline rules, tabular numerals, monospaced identifiers, aligned columns, small radii. |

**Signature motif — the highlighter.** The single accent colour behaves like a highlighter pen on paper: it marks evidence spans, the selected citation, retrieved nodes in the pipeline visualization, and keyboard focus. It is never used for decoration or to signal pass/fail.

## 2. Design principles

1. **Evidence before prose.** Show where an answer came from at least as prominently as the answer itself.
2. **Density with hierarchy.** Prefer information-rich, well-aligned layouts (tables, ledgers, timelines) over sparse grids of identical cards. Hierarchy comes from type weight, alignment, and rules — not size alone.
3. **Asymmetry with purpose.** Layouts follow the task: a narrow document column, a primary reading column, a supporting evidence column. Not everything is a centered card.
4. **Honest states.** Every data region has explicit empty, loading, success, partial, and error states written in product language. Missing data is shown as missing, never faked.
5. **Restraint.** One accent, one icon set, few elevation levels, short functional motion.
6. **Explain, don't decorate.** Visual effects — including 3D — exist only when they explain the system.

## 3. Colour

### 3.1 Palette direction (light theme, default)

| Token | Value (direction) | Use |
| --- | --- | --- |
| `--ink-900` | `#17181A` | Primary text, high-emphasis icons, dark surfaces |
| `--ink-700` | `#34363B` | Secondary text |
| `--ink-500` | `#676A71` | Muted text, metadata (must meet 4.5:1 on `--paper-100`) |
| `--ink-300` | `#B4B1A9` | Strong borders, disabled text on dark |
| `--paper-50` | `#FBFAF7` | Raised surfaces (panels, popovers) |
| `--paper-100` | `#F4F1EA` | App background |
| `--paper-200` | `#EAE5DA` | Subtle fills, table row hover, code/mono backgrounds |
| `--paper-300` | `#DCD5C6` | Hairline borders and dividers |
| `--accent-300` | `#F7D667` | Highlight fill behind evidence spans |
| `--accent-500` | `#E9B620` | Selected state, focus ring, retrieved nodes in 3D |
| `--accent-800` | `#7D5C00` | Accent text/links on paper (must meet 4.5:1) |

### 3.2 Semantic status colours

Status colours are distinct from the accent and are **always paired with an icon and a text label** — colour is never the only signal.

| Token | Value (direction) | Meaning | Paired icon (Lucide) |
| --- | --- | --- | --- |
| `--status-pass` | `#2D7350` | Passed / indexed / healthy | `CircleCheck` |
| `--status-fail` | `#B0382C` | Failed / gate blocked / error | `CircleX` |
| `--status-warn` | `#A85A16` | Degraded / below target but not gating / partial | `TriangleAlert` |
| `--status-pending` | `--ink-500` | Queued / running / unknown | `CircleDashed` / `LoaderCircle` |

### 3.3 Dark theme

A dark "ink" theme is defined from the same token names: background `~#141517`, raised surfaces `~#1C1D20`, hairlines `~#2C2E33`, text `~#ECE8DF`. The accent becomes a highlight on ink (`--accent-500` stays recognisable; highlighted spans use a dark text colour on the accent fill). Theme follows `prefers-color-scheme` with a manual override. Both themes must pass the same contrast checks.

### 3.4 Rules

- No gradients except a subtle, functional fade (e.g. scroll-edge shadows). No purple-blue gradients anywhere.
- Accent covers well under 5% of any screen.
- Charts use ink tones for series, accent for the currently selected/compared series, and status colours only for threshold verdicts.

## 4. Typography

| Role | Typeface (planned) | Notes |
| --- | --- | --- |
| Interface | **IBM Plex Sans** | Labels, navigation, body UI text |
| Data & identifiers | **IBM Plex Mono** | Run IDs, commit SHAs, chunk IDs, scores, latencies, config values; tabular numerals |
| Document evidence | **Source Serif 4** | Retrieved passages and quoted excerpts, so evidence reads as *document* text, distinct from UI chrome |

Fonts are self-hosted (no runtime font CDN). Use `font-variant-numeric: tabular-nums` for every number that may change or be compared.

**Scale** (px / line-height): `12/16` (mono labels, small caps metadata) · `13/18` (dense tables) · `14/20` (base UI) · `16/26` (evidence reading text) · `18/26` (section titles) · `22/28` (view title) · `28/34` (reserved: at most one per screen, e.g. a headline verdict).

- Weights: 400 and 500 for UI; 600 sparingly for view titles and verdicts. No ultra-bold display headings.
- Section labels may use 12px mono, uppercase, `letter-spacing: 0.06em`, in `--ink-500`.
- Measure for reading text: 60–75 characters.

## 5. Space, layout, borders, radii, elevation

- **Spacing:** 4px base unit. Scale: 4, 8, 12, 16, 20, 24, 32, 40, 56, 72.
- **Grid:** 12-column grid on wide screens with 24px gutters; primary layouts use fixed-width side columns plus a fluid centre.
- **Borders:** 1px hairlines in `--paper-300` define structure. Prefer rules and alignment over boxed cards.
- **Radii:** `2px` (tags, inputs inner elements), `4px` (inputs, buttons), `6px` (panels, popovers). Nothing pill-shaped except status dots.
- **Elevation:** three levels only — flat (default), raised (popovers, menus: soft 1-layer shadow, e.g. `0 1px 2px rgb(23 24 26 / 0.08), 0 4px 12px rgb(23 24 26 / 0.06)`), and modal (adds scrim). No glow effects. No blur-based glassmorphism.
- **Motion:** 120–200ms, ease-out, for state changes only (expand, select, progress). No bouncing, parallax, or idle animation. All motion respects `prefers-reduced-motion`.

## 6. Iconography

- **Lucide** for all interface icons, at 16px (dense) or 20px (primary controls), stroke width 1.5–1.75, colour inherited from text.
- Icons accompany labels; icon-only buttons require an accessible name and a tooltip.
- **No emoji** anywhere in the interface.
- Suggested mapping: `FileText` (document), `Upload`, `MessageSquareText` (ask), `Quote` (citation), `Layers` (chunks), `Network` (vectors), `ShieldCheck` (quality gate), `GitCommitHorizontal`, `FlaskConical` (experiments), `Gauge` (latency), `History`.

## 7. Component principles

Components live in `frontend/src/components/ui/` (primitives) and `frontend/src/features/*` (feature compositions). Every interactive component defines **default, hover, focus-visible, active, disabled, loading,** and where relevant **selected** and **error** states.

| Component | Principles |
| --- | --- |
| **Button** | Primary (ink fill, paper text), secondary (hairline border), ghost (text only), destructive (fail colour, confirm step). One primary action per region. |
| **Input / textarea** | Hairline border, 4px radius, accent focus ring (2px, offset 2px). Question box supports multi-line and `Enter`/`Shift+Enter` conventions. |
| **Status tag** | Icon + label + status colour on a tinted background; mono text for counts (e.g. `Indexed · 48 chunks`). |
| **Citation marker** | Inline mono superscript tag (`[2]`), focusable; activating it selects the matching evidence item and highlights the supporting span. |
| **Evidence item** | Document name, page, chunk ID, similarity score (mono); excerpt in Source Serif with highlighted span; "Cited" vs "Retrieved, not cited" distinction. |
| **Data table** | Sticky header, right-aligned numerals, sortable columns with `aria-sort`, row expansion for detail, hairline row dividers. |
| **Metric row** | Metric name, value, threshold, delta vs. previous run, verdict, small history sparkline — in a single aligned ledger row, not a card. |
| **Run identifier** | Mono, truncated SHA/ID with copy button and full value in tooltip. |
| **Progress / indexing steps** | Discrete steps (Uploaded → Extracted → Chunked → Embedded → Indexed) rather than an indeterminate spinner when steps are known. |
| **Empty state** | One sentence describing what will appear, one sentence on how to get there, one primary action. A small line illustration at most; no stock art. |
| **Toast / inline alert** | Inline alerts preferred for errors tied to a region; toasts only for transient confirmations. |
| **Demonstration-data label** | A persistent, hatched-border tag reading "Demonstration data — not from a real run" on any region showing sample data. |

## 8. Application shell and screens

### 8.1 Shell

- **Left navigation rail** (≈ 64px collapsed / 216px expanded): Workspace, Evaluation, Experiments, Pipeline. Icon + label; active item marked by an ink bar, not a coloured pill.
- **Top bar:** current collection name, backend connection status (from a real health check), and the latest real gate verdict when available (otherwise nothing — not a placeholder "Passed").
- Content area uses the full width; no centered narrow container for tool screens.

### 8.2 Document Workspace (Stage 3)

Responsibility: upload documents, see indexing status, ask questions, inspect cited evidence.

Asymmetric three-column layout on wide screens:

| Column | Width | Content |
| --- | --- | --- |
| Documents | ~280px | Compact drop zone (`Upload` + "PDF or TXT"), document list with status tag, page count, chunk count, indexed time; per-document actions (remove, re-index). |
| Conversation | fluid | Question/answer thread. Answers show inline citation markers, a per-answer timing strip in mono (`retrieval 142 ms · generation 1.8 s`), and a "Trace this answer" action. Question input pinned to the bottom. |
| Evidence | ~380px | Ranked retrieved passages for the selected answer, cited items first, supporting spans highlighted. |

States:
- **Empty (no documents):** "No documents indexed. Upload a PDF or TXT file — every answer will cite the page it came from." Shows the pipeline overview visualization (§10) as an explanation of what happens next.
- **Indexing:** per-document step progress; the question box is usable for already-indexed documents.
- **Extraction error:** e.g. "`scanned-invoice-0042.pdf` has no text layer. Scanned PDFs aren't supported yet." with a remove action.
- **Safe fallback answer:** visually distinct but not styled as an error — neutral panel with `SearchX` icon: "The indexed documents don't contain enough evidence to answer this." followed by the closest passages, explicitly labelled "Closest passages (below evidence threshold)".
- **Backend unavailable:** inline alert in the conversation column with retry; uploads disabled with explanation.

### 8.3 Evaluation Dashboard (Stage 4)

Responsibility: show the quality of the pipeline on the fixed dataset — retrieval success, answer quality, groundedness, fallback behaviour, latency, failed cases, and history.

- **Run header:** run ID, dataset version, configuration summary, commit, timestamp, overall gate verdict (one of the few places the 28px size may be used).
- **Metric ledger:** one aligned row per metric (value, threshold, delta vs. previous run, verdict, sparkline). LLM-judge-derived metrics are tagged "LLM judge — supplementary".
- **Failed cases table:** question, expected source(s), retrieved source(s), failing metric(s); expanding a row shows reference vs. generated answer side by side, retrieved evidence, and judge rationale (labelled as supplementary).
- **History:** chronological list of runs with verdict and key metrics; selecting two runs opens Experiment Comparison.
- **Empty state (before Stage 4 data exists):** "No evaluation runs yet. Runs appear here after the evaluation suite is executed locally or in CI." No placeholder numbers.

### 8.4 Experiment Comparison (Stage 5)

Responsibility: compare tracked configurations and their results.

- Run selector (two or more runs from MLflow-backed history).
- **Configuration diff:** parameters side by side with only changed values emphasized (chunk size, overlap, top-k, embedding model, LLM model, prompt version, dataset version).
- **Metric deltas:** aligned ledger with absolute and relative change; regressions marked with status colour + icon.
- **Case flips:** list of test cases whose outcome changed between runs (pass → fail, fail → pass).
- Link out to the corresponding MLflow run.

### 8.5 Pipeline Status (Stage 7)

Responsibility: show real CI test and quality-gate outcomes for code changes.

- Recent workflow runs: commit SHA, message, branch/PR, trigger, time.
- Per run, a horizontal step track: **Tests → Evaluation → Quality gate → Image build → Release**, each step with status. Steps that did not run because the gate failed are shown as "Skipped — gate failed", not as failures of their own.
- Gate detail: which thresholds failed, with values, linking to the evaluation run.
- A clear distinction between **"Currently serving"** (last released version) and **"Candidate"** (the change under evaluation), reinforcing that a blocked candidate does not affect the serving version.
- Before integration exists: "CI integration not configured yet." No simulated runs.

## 9. Content and data honesty

- Use realistic, product-specific language: "Indexed · 312 chunks", "Expected source not retrieved in top 5", "Gate blocked: groundedness below threshold".
- Never display fabricated live metrics, evaluation results, or CI statuses in the working application.
- Demonstration data, if ever used (e.g. for Stage 8 demos or design reviews), carries the demonstration-data label (§7) on every affected region.
- Placeholder copy such as "Lorem ipsum" or "Metric 1" is not allowed in shipped UI.

## 10. Purposeful 3D visualization — "Evidence Trace"

### 10.1 Concept

A restrained, interactive scene showing one document's journey through the RAG pipeline, laid out left to right as five stations:

1. **Pages** — thin paper-coloured slabs with hairline edges, slightly fanned; count reflects the document's real page count (capped, with a `+N` label).
2. **Chunks** — each page slices into horizontal strips that slide forward; the overlap between neighbouring chunks is rendered as a darker shared band, making "overlapping chunks" visible.
3. **Vectors** — strips collapse into small ink nodes in a sparse 3D field with faint nearest-neighbour links. Positions come from a deterministic layout, or a 3-component projection of real embeddings if the API exposes one (decided in Stage 3).
4. **Retrieved evidence** — a query marker (accent ring) enters the field; the top-k nodes light up in `--accent-500` with link opacity proportional to similarity; all other nodes dim.
5. **Answer** — retrieved nodes resolve back into strips stacked in an evidence tray; cited strips get an accent tick and connect to citation markers on a final answer slab.

### 10.2 Placement (limited to two places)

- **Workspace empty/first-run state:** an illustrative version explaining what happens to an uploaded file. It shows no numbers, so it cannot be mistaken for real data.
- **"Trace this answer" view:** the same scene bound to a real answer — real page count, chunk count, top-k retrieved chunks, scores, and which were cited.

3D is not used on the Evaluation, Experiments, or Pipeline Status screens.

### 10.3 Interaction

- An HTML stage stepper outside the canvas (Pages · Chunks · Vectors · Retrieval · Answer) drives the scene; it is fully keyboard-operable (arrow keys, `Home`/`End`) and announces the current stage.
- Hovering or focusing a retrieved node (via the stepper's list of retrieved chunks) shows its document, page, and score, and selects the matching evidence item.
- Camera: orthographic or low-FOV perspective with constrained orbit (small yaw range, no free zoom) to keep the composition legible.

### 10.4 Implementation constraints

- Three.js via React Three Fiber, in an isolated module (e.g. `frontend/src/features/chat/trace/` or a dedicated visualization module decided in Stage 3), with no backend logic inside it. It consumes the same typed API data as the 2D UI.
- **Procedural geometry only** (boxes, planes, instanced points, line segments). No stock or downloaded 3D models; `frontend/public/models/` stays empty unless a later recorded decision requires a small original asset.
- Additional helper libraries (e.g. `@react-three/drei`) only if justified and recorded in `DECISIONS.md`.

### 10.5 Reduced motion, accessibility, and fallback

- `prefers-reduced-motion`: no autoplay, no camera movement; the stepper switches between static compositions.
- The canvas is `aria-hidden`; an adjacent text summary (ordered list of the five stages with real counts and retrieved items) carries the same information for assistive technology.
- **Non-3D fallback:** an SVG/2D diagram of the same five stations, used when WebGL is unavailable, on small screens (below `md`), on user preference ("2D view" toggle, remembered locally), or if the 3D module fails to load.

### 10.6 Performance

- Lazy-loaded (`React.lazy` + dynamic import) only when the scene is about to be shown; the rest of the UI never waits for it.
- `frameloop="demand"`; render only during transitions or interaction. Pause when off-screen or the tab is hidden.
- Device pixel ratio capped (≈1.5); instanced meshes; node count capped (≈400); geometries and materials disposed on unmount.
- Target a modest gzipped size for the 3D chunk (budget set and measured in Stage 3).

## 11. Responsive behaviour

Breakpoints (Tailwind defaults): `sm 640`, `md 768`, `lg 1024`, `xl 1280`, `2xl 1536`.

| Range | Workspace | Data views | Navigation |
| --- | --- | --- | --- |
| ≥ `xl` | Three columns | Full tables, side-by-side comparison | Expanded rail |
| `lg` | Documents + conversation; evidence as a toggleable side sheet | Tables with lower-priority columns hidden behind row expansion | Collapsed rail |
| `md` | Conversation primary; documents and evidence as sheets | Same as `lg` | Collapsed rail |
| < `md` | Single column with tabs (Documents · Ask · Evidence); citations open a bottom sheet | Tables become stacked rows; comparison becomes sequential | Top bar with menu |

No horizontal page scrolling at any width ≥ 320px; wide tables scroll inside their own container with a visible edge cue.

## 12. Accessibility

- Target **WCAG 2.2 AA**: text contrast ≥ 4.5:1 (≥ 3:1 for large text and UI component boundaries), in both themes.
- Full keyboard operation; logical focus order; a visible focus ring (`--accent-500`, 2px, 2px offset, with an ink inner edge so it is visible on accent fills).
- Skip link to main content; landmarks (`nav`, `main`, `aside`); headings in order.
- `aria-live="polite"` for indexing progress and answer completion; generated answers are announced once complete, not token by token.
- Status never conveyed by colour alone (icon + text).
- Pointer targets ≥ 24×24px (aim for 32px on primary controls).
- Respect `prefers-reduced-motion` and `prefers-color-scheme`.
- Tables use proper headers, `scope`, and `aria-sort`.

## 13. Performance

- Initial route ships without the 3D module, charts, or comparison views (code-split per view).
- Self-hosted, subset fonts with `font-display: swap`; preload only the primary UI weight.
- Skeletons only for regions whose shape is known; avoid layout shift when data arrives.
- Long lists (documents, runs, failed cases) paginate or virtualize past a reasonable size.
- Performance budgets (bundle size, LCP on a mid-range laptop) are set and measured in Stage 3.

## 14. Prohibited generic patterns

- Purple-blue (or any decorative) gradients, gradient text, glowing borders, neon accents.
- Glassmorphism / heavy backdrop blur as a styling device.
- A screen made of a grid of identical KPI cards with large numbers and icons.
- Oversized hero headings on tool screens; marketing-style landing sections inside the app.
- Decorative emoji, or emoji used as icons.
- Sparkle/"magic" AI iconography for ordinary actions.
- Stock illustrations, stock 3D models, or 3D used as background decoration.
- Chat-bubble-only UI where sources are hidden behind a toggle.
- Fake data, simulated statuses, or placeholder metrics presented as real.
- Inconsistent icon sets, radii, or spacing that bypass the design tokens.

## 15. UI acceptance criteria

The frontend is accepted only when all of the following are verified (not assumed):

1. Design tokens (colour, type, spacing, radii, elevation) are implemented centrally and used consistently; no ad-hoc colours or font sizes.
2. Every screen in §8 implements its stated responsibility against the **real backend**; views whose data sources are not yet integrated show honest empty states.
3. Every data-driven region has loading, empty, success, and error states; the safe fallback answer is visually distinct and clearly worded.
4. Citations are interactive and resolve to the correct document, page, and highlighted span.
5. Layouts work at 360px, 768px, 1024px, and 1440px widths without horizontal page scroll or overlap.
6. Keyboard-only operation is possible for all flows; focus is always visible.
7. Contrast meets §12 in light and dark themes (checked with a tool, results recorded).
8. Reduced-motion preference is honoured; the 3D visualization has a working non-3D fallback and a text equivalent.
9. The 3D module is lazy-loaded and does not delay the initial view.
10. None of the prohibited patterns in §14 are present.
11. Any demonstration data is labelled as such.
12. A visual review against this spec is recorded in `PROGRESS_LOG.md` with screenshots or notes; rendering alone is not completion.

## 16. Stage 3 implementation notes and refinements

Recorded 2026-10-13. The identity above is unchanged; these notes describe how it was realised and where the available API data required a refinement. Decision IDs refer to `DECISIONS.md`.

**Tokens (§3–§5).** Implemented centrally in `frontend/src/styles/tokens.css` and bound to Tailwind with its default palette, font sizes, radii, and shadows removed, so only token utilities exist. Changes from §3.1: `--ink-500` is `#5F6269` and `--status-warn` is `#965012` (the spec values fell below 4.5:1 on `--paper-200`); new `--line-strong` (control borders, ≥ 3:1 on all surfaces) and `--on-accent` (text on accent fills). Dark theme: background `#141517`, raised `#1C1D20`, hairlines `#2C2E33`, text `#ECE8DF`, accent text `#F2C94C`. Both themes are checked by an automated WCAG test and scored 100 for accessibility in Lighthouse (D-034). The theme follows `prefers-color-scheme` with a System / Light / Dark override remembered locally.

**Workspace (§8.2).**
- *Layout:* three columns at ≥ 1280 px; at 1024–1279 px the evidence column becomes a right-hand sheet opened by citations or "Show evidence"; below 1024 px a Documents · Ask · Evidence switcher replaces the sheets described for `md` (D-038).
- *Indexing progress:* the API reports only the final result, so the UI shows an indeterminate "Indexing" state with elapsed time instead of the Uploaded → … → Indexed steps; showing those steps would simulate status (D-038).
- *Document actions:* remove (with inline confirmation) is implemented; "re-index" is not, because original files are not retained (D-025). Documents can be ticked to limit questions to them.
- *Safe fallback:* neutral `SearchX` panel with the backend's fallback text and the real evidence summary (retrieved count, best score, threshold, whether the model was called). "Closest passages (below evidence threshold)" are not shown because the API does not return them.
- *Evidence items:* cited first, then "Supplied to the model, not cited"; document, page, chunk index, and score in mono; excerpt in Source Serif. The API returns whole chunk excerpts, so the selected passage is marked with the accent rule rather than a sub-span highlight (D-037).
- *Citation markers:* `[Sn]` in the answer becomes a focusable marker only when `Sn` is in the response's `sources` (D-037).

**Evidence Trace (§10).**
- *Stations:* four instead of five — Documents · Chunks · Evidence · Answer. "Vectors" is omitted because the API exposes no embedding coordinates and none may be invented (D-036).
- *Encoding:* page tiles use real page counts (TXT files are one tile); chunk strips use real chunk counts and order; evidence nodes follow response rank; chunk-to-evidence link strength is the real cosine score; only cited sources link to the answer. Large documents are drawn scaled and the stage panel says so. Stage overlap bands (§10.1) are not drawn.
- *Interaction:* an HTML tab stepper (arrow keys, Home/End) emphasises one station and shows its real data as text; an "Evidence" list selects nodes and syncs the evidence column. The canvas and SVG are `aria-hidden`.
- *Motion:* no animation loop; the scene renders on demand. With reduced motion the 2D diagram is used rather than static 3D compositions.
- *Fallback:* the 2D SVG renders the same layout and is used without WebGL, below 768 px, with reduced motion, by user choice, while the 3D chunk loads, and if it fails (D-036).
- *Placement:* only the first-run workspace (captioned as an illustration, with no numbers) and "Trace this answer".
- *Performance:* lazy chunk of 242 kB gzip against a 260 kB budget; main bundle 91 kB gzip against a 100 kB budget (D-032). LCP has not been measured yet.
