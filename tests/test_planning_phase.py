import json
import subprocess
from pathlib import Path

from ai_factory import prompt_builder, safety
from ai_factory.cli import main
from ai_factory.prompts import PLAN_HEADINGS, missing_plan_headings


def _run(
    target: Path,
    state_dir: Path,
    backend: str = "fake",
    task: str = "add a fake change",
) -> int:
    return main(
        [
            "run",
            str(target),
            task,
            "--backend",
            backend,
            "--state-dir",
            str(state_dir),
        ]
    )


def _load_run_dir(state_dir: Path) -> Path:
    run_dirs = list((state_dir / "runs").iterdir())
    assert len(run_dirs) == 1
    return run_dirs[0]


def _load_run_metadata(state_dir: Path) -> dict:
    return json.loads((_load_run_dir(state_dir) / "metadata.json").read_text())


# --- plan.md contract -----------------------------------------------------------


def test_plan_phase_produces_plan_md_with_expected_headings(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 0
    run_dir = _load_run_dir(state_dir)
    plan_text = (run_dir / "plan.md").read_text()
    for heading in PLAN_HEADINGS:
        assert heading in plan_text

    metadata = _load_run_metadata(state_dir)
    assert metadata["phases"]["plan"]["status"] == "succeeded"
    assert metadata["phases"]["plan"]["plan_quality"] == "ok"
    assert metadata["phases"]["plan"]["missing_headings"] == []


def test_missing_plan_headings_flagged_degraded() -> None:
    incomplete_plan = f"{PLAN_HEADINGS[0]}\n\nonly the first section\n"
    missing = missing_plan_headings(incomplete_plan)

    assert missing == list(PLAN_HEADINGS[1:])


# --- Prompt Bundles --------------------------------------------------------------


def test_bundles_written_as_system_user_combined(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 0
    bundle_dir = _load_run_dir(state_dir) / "bundles"
    for phase in ("plan", "implement"):
        assert (bundle_dir / f"{phase}-system.md").is_file()
        assert (bundle_dir / f"{phase}-user.md").is_file()
        assert (bundle_dir / f"{phase}-combined.md").is_file()

    plan_system = (bundle_dir / "plan-system.md").read_text()
    assert "Planning Agent" in plan_system
    assert "read-only" in plan_system
    assert "Authority hierarchy" in plan_system

    plan_combined = (bundle_dir / "plan-combined.md").read_text()
    plan_user = (bundle_dir / "plan-user.md").read_text()
    assert plan_system in plan_combined
    assert plan_user in plan_combined


def test_repository_instructions_surfaced_and_secret_redacted(
    git_repo: Path, tmp_path: Path
) -> None:
    (git_repo / "AGENTS.md").write_text(
        "Follow these conventions.\n\napi_key: sk-super-secret-value\n"
    )
    subprocess.run(["git", "add", "AGENTS.md"], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add AGENTS.md"], cwd=git_repo, check=True, capture_output=True
    )
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 0
    plan_user = (_load_run_dir(state_dir) / "bundles" / "plan-user.md").read_text()
    assert "AGENTS.md" in plan_user
    assert "Follow these conventions." in plan_user
    assert "sk-super-secret-value" not in plan_user
    assert "[REDACTED]" in plan_user


# --- Read-only enforcement -> Contract Violation ---------------------------------


def test_plan_phase_mutation_yields_contract_violation_and_halts(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir, backend="fake-readonly-violator")

    assert exit_code == 1
    run_dir = _load_run_dir(state_dir)
    metadata = _load_run_metadata(state_dir)

    assert metadata["outcome"] == "contract_violation"
    assert metadata["phases"]["plan"]["status"] == "contract_violation"
    assert metadata["phases"]["implement"]["status"] == "not_executed"
    assert metadata["phases"]["verify"]["status"] == "not_executed"

    assert (run_dir / "contract-violation.patch").is_file()
    violation_patch = (run_dir / "contract-violation.patch").read_text()
    assert "FAKE_AGENT_PLAN_VIOLATION.md" in violation_patch

    violation_files = (run_dir / "contract-violation-files.txt").read_text()
    assert "FAKE_AGENT_PLAN_VIOLATION.md" in violation_files

    report_text = (run_dir / "report.md").read_text()
    assert "Contract Violation" in report_text

    # The target repo's own working tree is never touched by any of this.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, capture_output=True, text=True
    ).stdout
    assert status == ""


# --- Deterministic user-prompt assembly ------------------------------------------


def test_user_prompt_assembly_is_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    profile = {
        "ecosystem": "python",
        "degraded": False,
        "commands": {"test": {"command": "pytest", "source": "inferred", "confidence": "medium"}},
        "instructions": [],
    }

    first = prompt_builder.build_user_prompt("plan", "do the thing", profile, repo)
    second = prompt_builder.build_user_prompt("plan", "do the thing", profile, repo)

    assert first == second
    assert "do the thing" in first
    assert "pytest" in first
    assert "a.py" in first


def test_redact_secrets_is_deterministic_and_strips_common_secret_shapes() -> None:
    text = "api_key: sk-abc123\ntoken=deadbeef\nnothing secret here\n"
    first = safety.redact_secrets(text)
    second = safety.redact_secrets(text)

    assert first == second
    assert "sk-abc123" not in first
    assert "deadbeef" not in first
    assert "nothing secret here" in first
