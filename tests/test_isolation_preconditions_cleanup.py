import json
import subprocess
from pathlib import Path

import pytest

from ai_factory.cli import main


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _run(target: Path, state_dir: Path, task: str = "add a fake change") -> int:
    return main(
        [
            "run",
            str(target),
            task,
            "--backend",
            "fake",
            "--state-dir",
            str(state_dir),
        ]
    )


# --- Preconditions ---------------------------------------------------------


def test_run_refuses_on_repo_with_no_commits(tmp_path: Path) -> None:
    target = tmp_path / "no-commits-repo"
    target.mkdir()
    _git(["init"], cwd=target)
    state_dir = tmp_path / "state"

    exit_code = _run(target, state_dir)

    assert exit_code == 1
    assert not (state_dir / "runs").exists()


def test_run_refuses_on_dirty_working_tree(git_repo: Path, tmp_path: Path) -> None:
    (git_repo / "README.md").write_text("dirty\n")
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 1
    assert not (state_dir / "runs").exists()
    # No stash/reset/copy side effects: the dirty change is still there, untouched.
    assert (git_repo / "README.md").read_text() == "dirty\n"


def test_run_refuses_on_untracked_file(git_repo: Path, tmp_path: Path) -> None:
    (git_repo / "untracked.txt").write_text("new\n")
    state_dir = tmp_path / "state"

    exit_code = _run(git_repo, state_dir)

    assert exit_code == 1
    assert not (state_dir / "runs").exists()
    assert (git_repo / "untracked.txt").exists()


# --- status / list -----------------------------------------------------------


def test_status_reports_outcome_and_phases(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir) == 0
    run_id = next((state_dir / "runs").iterdir()).name

    exit_code = main(["status", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert run_id in output
    assert "implemented_degraded" in output
    assert "implement: succeeded" in output


def test_status_refuses_unknown_run_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    exit_code = main(["status", "does-not-exist", "--state-dir", str(state_dir)])
    assert exit_code == 1


def test_list_reports_all_runs(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir, "first task") == 0
    assert _run(git_repo, state_dir, "second task") == 0

    exit_code = main(["list", "--state-dir", str(state_dir)])

    assert exit_code == 0
    output = capsys.readouterr().out
    run_ids = [p.name for p in (state_dir / "runs").iterdir()]
    assert len(run_ids) == 2
    for run_id in run_ids:
        assert run_id in output


# --- clean -------------------------------------------------------------------


def test_clean_removes_worktree_branch_and_state_dir_only(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir) == 0
    run_id = next((state_dir / "runs").iterdir()).name
    run_dir = state_dir / "runs" / run_id
    metadata = json.loads((run_dir / "metadata.json").read_text())
    branch = metadata["branch"]
    worktree_path = Path(metadata["worktree_path"])

    other_branch_before = _git_output(["branch", "--list"], cwd=git_repo)
    assert branch in other_branch_before

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 0
    assert not run_dir.exists()
    assert not worktree_path.exists()
    branches_after = _git_output(["branch", "--list", branch], cwd=git_repo)
    assert branch not in branches_after
    # The target repo itself, and its main branch, are untouched.
    assert git_repo.exists()
    assert _git_output(["status", "--porcelain"], cwd=git_repo) == ""


def test_clean_refuses_unknown_run_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    exit_code = main(["clean", "does-not-exist", "--state-dir", str(state_dir)])
    assert exit_code == 1


def test_clean_all_removes_every_run(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir, "first task") == 0
    assert _run(git_repo, state_dir, "second task") == 0

    exit_code = main(["clean", "--all", "--state-dir", str(state_dir)])

    assert exit_code == 0
    assert list((state_dir / "runs").iterdir()) == []


def test_run_id_collision_refuses_instead_of_overwriting(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_factory.runner as runner_module

    monkeypatch.setattr(runner_module, "generate_run_id", lambda task: "fixed-run-id")

    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir) == 0
    run_dir = state_dir / "runs" / "fixed-run-id"
    sentinel = run_dir / "metadata.json"
    original_contents = sentinel.read_text()

    exit_code = _run(git_repo, state_dir, task="a different task")

    assert exit_code == 1
    assert sentinel.read_text() == original_contents
