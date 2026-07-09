import json
import subprocess
from pathlib import Path

from ai_factory.cli import main


def _load_run_dir(state_dir: Path) -> Path:
    run_dirs = list((state_dir / "runs").iterdir())
    assert len(run_dirs) == 1
    return run_dirs[0]


def _load_metadata(run_dir: Path) -> dict:
    return json.loads((run_dir / "metadata.json").read_text())


# --- Manual Mode (`--backend manual`, the default) --------------------------------


def test_manual_is_the_default_backend(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = main(["run", str(git_repo), "some task", "--state-dir", str(state_dir)])

    assert exit_code == 0
    metadata = _load_metadata(_load_run_dir(state_dir))
    assert metadata["backend"] == "manual"


def test_manual_mode_prepares_bundles_and_prints_intended_paths(
    git_repo: Path, tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"

    exit_code = main(
        ["run", str(git_repo), "some task", "--backend", "manual", "--state-dir", str(state_dir)]
    )

    assert exit_code == 0
    run_dir = _load_run_dir(state_dir)
    metadata = _load_metadata(run_dir)

    assert (run_dir / "profile.json").exists()
    assert (run_dir / "bundles" / "plan-system.md").exists()
    assert (run_dir / "bundles" / "plan-user.md").exists()
    assert (run_dir / "bundles" / "plan-combined.md").exists()

    output = capsys.readouterr().out
    assert metadata["run_id"] in output
    assert f"factory/{metadata['run_id']}" in output
    assert str(state_dir) in output
    assert "worktree" in output


def test_manual_mode_creates_no_branch_or_worktree(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = main(
        ["run", str(git_repo), "some task", "--backend", "manual", "--state-dir", str(state_dir)]
    )

    assert exit_code == 0
    run_dir = _load_run_dir(state_dir)
    metadata = _load_metadata(run_dir)

    assert not (run_dir / "worktree").exists()
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert "factory/" not in branches
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert str(run_dir) not in worktrees
    assert metadata["branch"] is None
    assert metadata["worktree_path"] is None


def test_manual_mode_phases_are_not_executed(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    main(["run", str(git_repo), "some task", "--backend", "manual", "--state-dir", str(state_dir)])

    metadata = _load_metadata(_load_run_dir(state_dir))
    for phase in ("plan", "implement", "verify", "review"):
        assert metadata["phases"][phase]["status"] == "not_executed"
    assert metadata["outcome"] == "planned"
    assert "manual mode" in metadata["outcome_reason"].lower()


def test_manual_mode_works_against_a_non_git_folder(tmp_path: Path) -> None:
    target = tmp_path / "not-a-repo"
    target.mkdir()
    (target / "README.md").write_text("hello\n")
    state_dir = tmp_path / "state"

    exit_code = main(
        ["run", str(target), "some task", "--backend", "manual", "--state-dir", str(state_dir)]
    )

    assert exit_code == 0
    run_dir = _load_run_dir(state_dir)
    metadata = _load_metadata(run_dir)
    assert metadata["phases"]["plan"]["status"] == "not_executed"
    assert not (target / ".git").exists()


def test_manual_mode_never_touches_the_target(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = main(
        [
            "run",
            str(git_repo),
            "fix a bug that requires editing the README",
            "--backend",
            "manual",
            "--state-dir",
            str(state_dir),
        ]
    )

    assert exit_code == 0
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert status.strip() == ""


# --- Staged phase commands: `plan` then `implement` --------------------------------


def _run_plan(target: Path, state_dir: Path, task: str, backend: str = "fake") -> str:
    exit_code = main(
        ["plan", str(target), task, "--backend", backend, "--state-dir", str(state_dir)]
    )
    assert exit_code == 0
    run_dir = _load_run_dir(state_dir)
    return run_dir.name


def test_staged_plan_runs_only_plan_and_stops(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")

    metadata = _load_metadata(_load_run_dir(state_dir))
    assert metadata["run_id"] == run_id
    assert metadata["phases"]["plan"]["status"] == "succeeded"
    assert metadata["phases"]["implement"]["status"] == "not_executed"
    assert metadata["phases"]["verify"]["status"] == "not_executed"
    assert metadata["outcome"] == "planned"

    # The plan phase's own worktree/branch DO exist -- staged driving is a real,
    # git-isolated Run, unlike Manual Mode.
    run_dir = _load_run_dir(state_dir)
    assert (run_dir / "worktree").exists()
    assert (run_dir / "plan.md").exists()


def test_staged_implement_continues_the_same_run(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")

    exit_code = main(["implement", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 0
    run_dir = _load_run_dir(state_dir)
    assert run_dir.name == run_id
    metadata = _load_metadata(run_dir)
    assert metadata["phases"]["implement"]["status"] == "succeeded"
    assert metadata["outcome"] in ("implemented_verified", "implemented_degraded")


def test_staged_implement_refuses_before_plan_succeeds(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    # A `run` with the fake backend produces a fully-automated Run whose plan
    # succeeded and implement already ran -- implement should refuse to re-run.
    exit_code = main(
        [
            "run",
            str(git_repo),
            "fix a small localized bug",
            "--backend",
            "fake",
            "--state-dir",
            str(state_dir),
        ]
    )
    assert exit_code == 0
    run_id = _load_run_dir(state_dir).name

    exit_code = main(["implement", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1


def test_staged_review_runs_after_implement(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")
    assert main(["implement", run_id, "--state-dir", str(state_dir)]) == 0

    exit_code = main(["review", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 0
    metadata = _load_metadata(_load_run_dir(state_dir))
    assert metadata["phases"]["review"]["status"] == "succeeded"


def test_manual_backend_cannot_drive_staged_phases(git_repo: Path, tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"

    # "manual" creates no worktree/branch, so `plan` refuses it -- staged
    # driving requires a real, worktree-creating backend (config layering,
    # issue 09, means the preset registry is no longer a fixed CLI `choices`
    # list, so this is now a runtime RunError rather than an argparse error).
    exit_code = main(
        [
            "plan",
            str(git_repo),
            "fix a small localized bug",
            "--backend",
            "manual",
            "--state-dir",
            str(state_dir),
        ]
    )

    assert exit_code == 1
    assert "cannot drive staged phases" in capsys.readouterr().err
