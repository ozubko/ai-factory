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


def _run_plan(target: Path, state_dir: Path, task: str) -> str:
    exit_code = main(
        ["plan", str(target), task, "--backend", "fake", "--state-dir", str(state_dir)]
    )
    assert exit_code == 0
    return _load_run_dir(state_dir).name


def _leave_untracked_marker(worktree_path: Path) -> None:
    """Simulates a crash mid read-write Phase: an agent edited the worktree
    but the Factory never got to commit or persist metadata for it."""
    (worktree_path / "INTERRUPTED_PARTIAL_CHANGE.md").write_text("partial work\n")


def test_resume_continues_a_planned_run_to_implement(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")

    exit_code = main(["resume", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 0
    metadata = _load_metadata(_load_run_dir(state_dir))
    assert metadata["phases"]["implement"]["status"] == "succeeded"
    assert metadata["outcome"] in ("implemented_verified", "implemented_degraded")


def test_resume_refuses_partial_readwrite_phase_without_discard(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")
    run_dir = _load_run_dir(state_dir)
    worktree_path = run_dir / "worktree"
    _leave_untracked_marker(worktree_path)

    exit_code = main(["resume", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    # Metadata is untouched -- implement never ran -- and the marker survives.
    metadata = _load_metadata(run_dir)
    assert metadata["phases"]["implement"]["status"] == "not_executed"
    assert (worktree_path / "INTERRUPTED_PARTIAL_CHANGE.md").exists()
    # The target's own working tree was never touched.
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, capture_output=True, text=True
    ).stdout.strip() == ""


def test_resume_discard_phase_changes_resets_worktree_and_proceeds(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")
    run_dir = _load_run_dir(state_dir)
    worktree_path = run_dir / "worktree"
    _leave_untracked_marker(worktree_path)

    exit_code = main(
        ["resume", run_id, "--state-dir", str(state_dir), "--discard-phase-changes"]
    )

    assert exit_code == 0
    assert not (worktree_path / "INTERRUPTED_PARTIAL_CHANGE.md").exists()
    metadata = _load_metadata(run_dir)
    assert metadata["phases"]["implement"]["status"] == "succeeded"
    assert metadata["outcome"] in ("implemented_verified", "implemented_degraded")
    # The target's own working tree was never touched.
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, capture_output=True, text=True
    ).stdout.strip() == ""


def test_resume_review_is_idempotent_without_discard_flag(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = _run_plan(git_repo, state_dir, "fix a small localized bug")
    assert main(["implement", run_id, "--state-dir", str(state_dir)]) == 0
    run_dir = _load_run_dir(state_dir)
    worktree_path = run_dir / "worktree"
    _leave_untracked_marker(worktree_path)

    exit_code = main(["resume", run_id, "--state-dir", str(state_dir), "--review"])

    assert exit_code == 0
    assert not (worktree_path / "INTERRUPTED_PARTIAL_CHANGE.md").exists()
    metadata = _load_metadata(run_dir)
    assert metadata["phases"]["review"]["status"] == "succeeded"


def test_resume_refuses_when_nothing_left(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
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

    exit_code = main(["resume", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1


def test_resume_refuses_unknown_run_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    exit_code = main(["resume", "does-not-exist", "--state-dir", str(state_dir)])

    assert exit_code == 1
