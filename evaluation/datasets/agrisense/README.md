# AgriSense / EVIDENT benchmark

A fourth, separate evaluation dataset (`agrisense-evident`, **v1.1.0**, 27 cases: 22 answerable, 5 unanswerable; v1.0.0 until 2026-10-25, see "Version history"), added in Stage 5.7 (2026-10-16) after the owner's manual test of a long technical PDF failed. Same schema, evaluator, report format, CLI, and MLflow experiment as the core, VEIL, and structural datasets, which stay unchanged.

```bash
cd backend
.venv/bin/python -m app.evaluation.run_evaluation --dataset ../evaluation/datasets/agrisense/dataset.json --validate-only
.venv/bin/python -m app.evaluation.run_evaluation --dataset ../evaluation/datasets/agrisense/dataset.json --label agrisense   # ~3 min with judge
```

## Corpus and provenance

| File | Origin |
| --- | --- |
| `AgriSense_ Research Synthesis, Selected Core Invention, and Roadmap.pdf` | Byte-for-byte copy (made with the owner's approval on 2026-10-16) of the 22-page PDF the owner uploaded during the manual test; SHA-256 `5a2d66d4af8034ccdde9882a049079df2d7cf9ea5a3c79196445feebf3935c71`. |

It is the owner's research synthesis. Reference answers restate what the document says (claims, plans, hypotheses); they are not independently verified facts. The PDF writes text in kerned fragments of one to a few characters, which is what exposed the Stage 5.7 extraction defect (D-064).

## Expected pages

Every case lists `expected_pages` (filename → 1-based pages). The loader checks that each required fact occurs on those pages, and reports record `retrieval.expected_page_hit` / `expected_page_hit_rate` (an evidence passage comes from an expected page). This is the meaningful retrieval check for a single long document, where "expected source retrieved" is always true.

## Cases (v1.1.0: 27)

| IDs | What they test | Pages |
| --- | --- | --- |
| AGR-COR-001 | The owner's failing question 1: what EVIDENT is and its four mechanisms (two parts, three pages) | 1, 2, 12 |
| AGR-VRD-001 | Failing question 2: all seven verdict states (enum names; little word overlap with the question) | 12, 16 |
| AGR-GAP-001 | Failing question 3: what the gap planner computes and its costs | 12, 16 |
| AGR-FHR-001 | Failing question 4: four failure-handling rules | 14 |
| AGR-COR-002 | The question that already worked (problem statement) | 12 |
| AGR-ASR-001 | Assurance levels A0–A3 | 15 |
| AGR-REV-001, -002 | Rule-version propagation; events that trigger revalidation | 14, 17 |
| AGR-JNT-001, -002 | Joint-holding share arithmetic (no equal-split default); consent gate | 14, 17 |
| AGR-NUM-001…003 | Numbers and table comparisons (Bharat-VISTAAR, ULI lenders, MSKVY rent) | 2, 8, 9 |
| AGR-SEL-001, AGR-MUL-001 | Architecture selection; rejected ideas across distant pages | 4, 12, 21 |
| AGR-PVD-001 | Proposed vs demonstrated: real-world impact is explicitly not claimed | 20, 22 |
| AGR-FPR-001, -002 | False premises: automatic submission; unknown treated as eligible | 13, 14, 16 |
| AGR-OVL-001, -002 | Overlapping terminology (application states vs verdict states); conflicting survival thresholds | 9, 18 |
| AGR-ALG-001, AGR-GAP-002 | Formal composition rule; gap-planning complexity and ILP | 16 |
| AGR-UNA-001…005 | Unsupported performance claim, lookalike measurement (browser vs Android proving time), absent usage and price figures, unrelated question | — |

Questions and expectations were written from the document before any run of the changed pipeline. Two accepted spellings were added before the first run because the source text breaks phrases across lines (`AGR-REV-001` uses "affected" instead of "never overwrite"; `AGR-REV-002` accepts "withdrawal").

## Results (Stage 5.7)

| Run | Code | Pass | False refusals | False answers | Expected page in evidence |
| --- | --- | --- | --- | --- | --- |
| `20261015T201247Z-7a91c3` | before (D-063 extractor, sub-unit index; reconstructed in a scratch copy) | 6/27 | 18/22 | 0/5 | 10/22 |
| `20261016T095114Z-fc34e3` | final (fragment-safe extraction, hybrid candidates, dense-order evidence) | 19/27 | 5/22 | 1/5 | 20/22 |
| `20261016T100110Z-a16aeb` | same, repeat | 19/27 | 5/22 | 1/5 | 20/22 |
| `20261016T114446Z-e92a3c` | stabilisation: prompt v7, evaluator e2 (D-067, D-068) | 21/27 | 5/22 | 0/5 | 20/22 |
| `20261016T115450Z-9b86b3` | same, repeat | 19/27 | 6/22 | 0/5 | 20/22 |

Failing in both final runs: AGR-COR-001 and AGR-ALG-001 (evidence present; the model will not attribute passages that say "the engine" / "AgriSense" to EVIDENT), AGR-VRD-001 and AGR-REV-001 (expected page not retrieved), AGR-COR-002 and AGR-SEL-001 (one required fact missing), AGR-PVD-001 (declines instead of stating that impact is not demonstrated), AGR-FPR-001 (the model rejects the false premise, citing "EVIDENT never claims sanction", in the raw replies, but the run records a `model_declined` fallback — the decline marker or an output guard; not distinguished in the report), AGR-UNA-002 (answers with the browser measurement for an Android question).

Under prompt v7 (2026-10-16 stabilisation): AGR-UNA-002 is now declined correctly in both runs; AGR-FPR-002 (false premise "unknown treated as eligible") declines in both runs instead of correcting the premise (v7 trade-off, D-067); AGR-ALG-001 and AGR-COR-002 pass in one of two runs. Traced residuals (no production change justified): AGR-COR-001 / AGR-ALG-001 — the needed passages are in the evidence but never name EVIDENT (the section heading sits in an earlier chunk; showing section headings was tested and rejected: COR-001 stopped declining but stayed incomplete, ALG-001 declined more); AGR-VRD-001 — both chunks that list all seven states pass the gate but rank 6th and 27th, outside the top 4; AGR-COR-002 — answers say "when rules or evidence change", which the lexical alternatives do not cover (judge 5/5; candidate for a versioned v1.1.0 revision, not changed).

## Version history

- **v1.1.0 (2026-10-25, D-074):** AGR-REV-001's fact "notify on verdict change" also accepts "notifies" (answers wrote "notifies the user only if the verdict changes"). Of 7 stored answered AGR-REV-001 answers, 2 change from "fact missing" to "fact found". No other case, file, page, or expected answer changed. Fingerprint `d05ee764…` → `963e3cd4…`; results on v1.0.0 and v1.1.0 are compared only with this qualification.
- **v1.0.0 (2026-10-16):** initial 27 cases.

## Limitations

- Single document, 27 cases: one case moves the pass rate by 3.7 points.
- Lexical fact checks: a correct paraphrase can be missed, and naming every enum value is required for AGR-VRD-001.
- Several answers depend on a list that spans a chunk boundary (page 12); complete answers need more than one chunk.
