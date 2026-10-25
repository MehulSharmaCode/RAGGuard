"""Final status of the RAGGuard CI workflow (Stage 7, D-080).

Standard library only: this job runs on a bare runner. It reads the `needs` context of the
`ci-result` job, writes a Markdown summary (including whether the image build was *eligible*
to run), and exits non-zero unless every job succeeded. A skipped, cancelled, or failed job is
never reported as success: `ci-result` is the one status to require in branch protection.

    NEEDS_JSON='{"backend-checks": {"result": "success"}, ...}' python3 .github/scripts/ci_result.py
"""

from __future__ import annotations

import json
import os
import sys

# Jobs that must succeed before an image may be built (the workflow's `image-build` needs).
PREREQUISITES = ("backend-checks", "frontend-checks", "dataset-validation", "quality-gate")
IMAGE_BUILD = "image-build"
MEANING = {
    "success": "passed",
    "failure": "FAILED",
    "cancelled": "CANCELLED (not a pass)",
    "skipped": "skipped (not run, not a pass)",
}


def summarise(needs: dict[str, dict[str, str]], commit: str = "unknown") -> tuple[str, bool]:
    """Markdown summary and overall success for the `needs` context of the ci-result job."""
    results = {
        job: needs.get(job, {}).get("result", "missing") for job in (*PREREQUISITES, IMAGE_BUILD)
    }
    eligible = all(results[job] == "success" for job in PREREQUISITES)
    passed = eligible and results[IMAGE_BUILD] == "success"
    lines = [
        f"## RAGGuard CI: {'PASSED' if passed else 'FAILED'}",
        "",
        f"- Commit: `{commit}`",
        f"- Image build eligible: **{'yes' if eligible else 'no'}** "
        "(requires every check and the quality gate to have passed)",
        "- Images are built to validate the Stage 6 configuration only: nothing is pushed to a "
        "registry and nothing is deployed.",
        "",
        "| Job | Result |",
        "| --- | --- |",
    ]
    for job, result in results.items():
        lines.append(f"| {job} | {MEANING.get(result, result)} |")
    if not eligible:
        blockers = [job for job in PREREQUISITES if results[job] != "success"]
        lines += ["", f"Image build did not run because of: {', '.join(blockers)}."]
    return "\n".join(lines) + "\n", passed


def main() -> int:
    raw = os.environ.get("NEEDS_JSON", "")
    try:
        needs = json.loads(raw)
        if not isinstance(needs, dict):
            raise ValueError("NEEDS_JSON is not an object")
    except ValueError as exc:
        print(f"ERROR: unusable NEEDS_JSON ({exc}); failing closed", file=sys.stderr)
        return 1
    text, passed = summarise(needs, os.environ.get("GITHUB_SHA", "unknown"))
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
