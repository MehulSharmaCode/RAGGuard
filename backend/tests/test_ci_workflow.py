"""The CI workflow's design is tested, because a hosted run cannot be executed locally (Stage 7).

These tests parse .github/workflows/ragguard-ci.yml and check what must hold for the quality gate
to mean something: image building depends on every check and on the gate, nothing can bypass
that, nothing is published or deployed, permissions are minimal, third-party actions are pinned
to commits, and every command and path the workflow uses exists. They do not prove that GitHub
runs the workflow: that is verified by a hosted run.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.evaluation.quality_gate import GATE_FILE, load_config

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ragguard-ci.yml"
COMPOSITE = REPO / ".github" / "actions" / "setup-backend" / "action.yml"
SCRIPT = REPO / ".github" / "scripts" / "ci_result.py"

PREREQUISITES = ["backend-checks", "frontend-checks", "dataset-validation", "quality-gate"]


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return workflow["jobs"]  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def ci_result() -> Any:
    spec = importlib.util.spec_from_file_location("ci_result", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_result"] = module
    spec.loader.exec_module(module)
    return module


def code(path: Path) -> str:
    """The file's text without YAML comments (comments may name what the workflow avoids)."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in path.read_text().splitlines())


def all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    composite = yaml.safe_load(COMPOSITE.read_text(encoding="utf-8"))
    return [s for j in workflow["jobs"].values() for s in j["steps"]] + composite["runs"]["steps"]


def needs(job: dict[str, Any]) -> list[str]:
    value = job.get("needs", [])
    return [value] if isinstance(value, str) else list(value)


# --- triggers, permissions, concurrency -------------------------------------------------------
def test_triggers_are_pull_request_push_to_main_and_manual(workflow: dict[str, Any]) -> None:
    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML reads `on` as True
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["pull_request"]["branches"] == ["main"]
    assert triggers["push"]["branches"] == ["main"]
    for trigger in ("pull_request", "push"):
        assert "paths" not in triggers[trigger] and "paths-ignore" not in triggers[trigger], (
            "no path filter: any change can affect a release"
        )


def test_no_privileged_pull_request_target_and_no_secrets(workflow: dict[str, Any]) -> None:
    text = code(WORKFLOW) + code(COMPOSITE)
    assert "pull_request_target" not in text
    assert "secrets." not in text and "GITHUB_TOKEN" not in text
    assert "workflow_run" not in text


def test_permissions_are_read_only(workflow: dict[str, Any], jobs: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in jobs.values()), "no job widens the token"


def test_concurrency_cancels_only_superseded_pull_request_runs(workflow: dict[str, Any]) -> None:
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    group = concurrency["group"]
    assert "github.sha" in group and "pull_request.number" in group


# --- the dependency graph -----------------------------------------------------------------------
def test_the_expected_jobs_exist(jobs: dict[str, Any]) -> None:
    assert set(jobs) == {*PREREQUISITES, "image-build", "ci-result"}


def test_image_build_depends_on_every_check_and_on_the_gate(jobs: dict[str, Any]) -> None:
    assert sorted(needs(jobs["image-build"])) == sorted(PREREQUISITES)
    assert needs(jobs["quality-gate"]) == ["dataset-validation"]


def test_image_build_has_no_condition_that_could_bypass_its_dependencies(
    jobs: dict[str, Any],
) -> None:
    assert "if" not in jobs["image-build"], "the default condition is success() of all needs"
    for name, job in jobs.items():
        if name != "ci-result":
            condition = str(job.get("if", ""))
            assert "always()" not in condition and "failure()" not in condition, name
    assert "continue-on-error" not in code(WORKFLOW)


def test_ci_result_reports_but_builds_nothing(jobs: dict[str, Any]) -> None:
    job = jobs["ci-result"]
    assert job["if"] == "${{ always() }}"
    assert sorted(needs(job)) == sorted([*PREREQUISITES, "image-build"])
    commands = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "docker" not in commands and "build" not in commands.lower().replace("image-build", "")


def simulate(jobs: dict[str, Any], outcome: dict[str, str]) -> dict[str, str]:
    """GitHub's rule for a job without `if`: it runs only if every `needs` job succeeded."""
    result: dict[str, str] = {}
    remaining = dict(jobs)
    while remaining:
        for name, job in list(remaining.items()):
            if any(n in remaining for n in needs(job)):
                continue
            del remaining[name]
            if name == "ci-result":
                result[name] = "runs"
            elif all(result[n] == "success" for n in needs(job)):
                result[name] = outcome.get(name, "success")
            else:
                result[name] = "skipped"
    return result


@pytest.mark.parametrize("failing", [*PREREQUISITES])
@pytest.mark.parametrize("how", ["failure", "cancelled", "skipped"])
def test_a_failed_required_job_prevents_the_image_build(
    jobs: dict[str, Any], failing: str, how: str
) -> None:
    result = simulate(jobs, {failing: how})
    assert result["image-build"] == "skipped"


def test_when_everything_passes_the_image_build_runs(jobs: dict[str, Any]) -> None:
    assert simulate(jobs, {}) == {
        **{n: "success" for n in PREREQUISITES},
        "image-build": "success",
        "ci-result": "runs",
    }


def test_a_failed_gate_upstream_also_blocks_via_the_dataset_job(jobs: dict[str, Any]) -> None:
    result = simulate(jobs, {"dataset-validation": "failure"})
    assert result["quality-gate"] == "skipped" and result["image-build"] == "skipped"


# --- nothing is published or deployed ----------------------------------------------------------
def test_images_are_built_but_neither_pushed_nor_deployed(workflow: dict[str, Any]) -> None:
    builds = [
        s
        for s in all_steps(workflow)
        if str(s.get("uses", "")).startswith("docker/build-push-action")
    ]
    assert len(builds) == 2
    for step in builds:
        assert step["with"]["push"] is False and step["with"]["load"] is True
    text = code(WORKFLOW).lower()
    for forbidden in (
        "docker login",
        "docker push",
        "ghcr.io",
        "registry",
        "kubectl",
        "deploy:",
        "gh release",
        "packages: write",
    ):
        assert forbidden not in text, forbidden


def test_third_party_actions_are_pinned_to_commits(workflow: dict[str, Any]) -> None:
    for step in all_steps(workflow):
        uses = step.get("uses")
        if uses is None or uses.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses), uses
    for path in (WORKFLOW, COMPOSITE):
        for line in path.read_text().splitlines():
            if "uses:" in line and "./" not in line:
                assert re.search(r"# v\d+\.\d+\.\d+$", line.strip()), (
                    f"version comment missing: {line.strip()}"
                )


def test_the_workflow_uses_no_unexpected_environment_secrets(workflow: dict[str, Any]) -> None:
    for step in all_steps(workflow):
        for key in step.get("env") or {}:
            assert not re.search(r"KEY|TOKEN|SECRET|PASSWORD", key), key
    assert set(workflow["env"]) == {
        "TOKENIZERS_PARALLELISM",
        "HF_HUB_DISABLE_TELEMETRY",
        "EMBEDDING_MODEL",
    }


# --- commands and paths exist ---------------------------------------------------------------------
def test_files_referenced_by_the_workflow_exist(
    workflow: dict[str, Any], jobs: dict[str, Any]
) -> None:
    assert SCRIPT.is_file() and COMPOSITE.is_file()
    for step in all_steps(workflow):
        if "docker/build-push-action" in str(step.get("uses", "")):
            assert (REPO / step["with"]["file"]).is_file()
    text = WORKFLOW.read_text() + COMPOSITE.read_text()
    for requirement in re.findall(r"requirements(?:-[a-z]+)?\.txt", text):
        assert (REPO / "backend" / requirement).is_file(), requirement
    assert (REPO / "frontend" / "package-lock.json").is_file()


def test_npm_scripts_used_exist() -> None:
    scripts = json.loads((REPO / "frontend" / "package.json").read_text())["scripts"]
    used = re.findall(r"npm run (\w+)", WORKFLOW.read_text())
    assert set(used) == {"typecheck", "lint", "test", "build"}
    assert set(used) <= set(scripts)


def test_python_modules_used_exist() -> None:
    modules = set(re.findall(r"python -m ([\w.]+)", WORKFLOW.read_text()))
    assert modules == {"app.evaluation.quality_gate", "app.evaluation.run_evaluation"}
    for module in modules:
        assert importlib.util.find_spec(module) is not None, module


def test_quality_gate_subcommands_used_exist() -> None:
    from app.evaluation.quality_gate import build_parser

    parser = build_parser()
    for command in set(
        re.findall(
            r"quality_gate (run|junit|validate-datasets|list-datasets)", WORKFLOW.read_text()
        )
    ):
        assert (
            parser.parse_args([command, "x"] if command == "junit" else [command]).command
            == command
        )


def test_dataset_paths_come_from_the_gate_file_not_the_workflow() -> None:
    text = WORKFLOW.read_text()
    assert "evaluation/datasets" not in text and "quality_gate list-datasets" in text


def test_the_workflow_embedding_model_is_the_one_the_gate_expects(workflow: dict[str, Any]) -> None:
    assert (
        workflow["env"]["EMBEDDING_MODEL"] == load_config(GATE_FILE).configuration.embedding_model
    )


def test_the_expected_xfail_count_matches_the_tests() -> None:
    declared = sum(
        len(re.findall(r"pytest\.mark\.xfail\(", p.read_text()))
        for p in (REPO / "backend" / "tests").glob("test_*.py")
        if p.name != "test_ci_workflow.py"
    )
    assert declared == 1
    assert "--expected-xfail 1" in WORKFLOW.read_text().replace("\n", " ")
    assert "--max-skipped 0" in WORKFLOW.read_text().replace("\n", " ")


def test_the_image_builds_match_compose(workflow: dict[str, Any]) -> None:
    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    steps = {
        s["with"]["tags"].split(":")[0]: s["with"]
        for s in all_steps(workflow)
        if "docker/build-push-action" in str(s.get("uses", ""))
    }
    for service, tag in (("backend", "ragguard-backend"), ("frontend", "ragguard-frontend")):
        build = compose["services"][service]["build"]
        assert steps[tag]["file"] == build["dockerfile"]
        assert steps[tag]["target"] == build["target"]
        assert steps[tag]["context"] == build["context"]


def test_each_job_has_a_timeout(jobs: dict[str, Any]) -> None:
    assert all(isinstance(job.get("timeout-minutes"), int) for job in jobs.values())


# --- the final status script ----------------------------------------------------------------------
def needs_json(**results: str) -> dict[str, dict[str, str]]:
    base = {name: "success" for name in [*PREREQUISITES, "image-build"]}
    base.update(results)
    return {name: {"result": result} for name, result in base.items()}


def test_ci_result_passes_only_when_every_job_succeeded(ci_result: Any) -> None:
    text, passed = ci_result.summarise(needs_json(), "abc123")
    assert passed and "PASSED" in text and "Image build eligible: **yes**" in text
    assert "nothing is pushed" in text


@pytest.mark.parametrize("failing", PREREQUISITES)
def test_ci_result_fails_and_says_why_the_image_build_did_not_run(
    ci_result: Any, failing: str
) -> None:
    text, passed = ci_result.summarise(needs_json(**{failing: "failure", "image-build": "skipped"}))
    assert not passed and "FAILED" in text
    assert "Image build eligible: **no**" in text and f"because of: {failing}" in text


@pytest.mark.parametrize("result", ["cancelled", "skipped", "failure", "missing-value"])
def test_ci_result_never_reads_a_non_success_as_success(ci_result: Any, result: str) -> None:
    for job in [*PREREQUISITES, "image-build"]:
        assert not ci_result.summarise(needs_json(**{job: result}))[1]


def test_a_failed_image_build_after_a_passing_gate_fails_the_workflow(ci_result: Any) -> None:
    text, passed = ci_result.summarise(needs_json(**{"image-build": "failure"}))
    assert not passed and "Image build eligible: **yes**" in text and "FAILED" in text


def test_ci_result_fails_closed_on_missing_jobs_and_bad_input(
    ci_result: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert not ci_result.summarise({})[1]
    monkeypatch.setenv("NEEDS_JSON", "not json")
    assert ci_result.main() == 1
    monkeypatch.setenv("NEEDS_JSON", "[]")
    assert ci_result.main() == 1
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs_json()))
    assert ci_result.main() == 0 and "PASSED" in summary.read_text()
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs_json(**{"quality-gate": "failure"})))
    assert ci_result.main() == 1
