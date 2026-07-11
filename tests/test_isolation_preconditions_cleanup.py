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


def _run_manual(target: Path, state_dir: Path, task: str) -> int:
    return main(
        [
            "run",
            str(target),
            task,
            "--backend",
            "manual",
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


def test_clean_manual_mode_run_removes_only_requested_run(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    assert _run_manual(git_repo, state_dir, "first manual task") == 0
    requested_run_dir = next((state_dir / "runs").iterdir())
    assert _run_manual(git_repo, state_dir, "second manual task") == 0

    remaining_run_dir = next(
        run_dir
        for run_dir in (state_dir / "runs").iterdir()
        if run_dir != requested_run_dir
    )
    remaining_metadata = (remaining_run_dir / "metadata.json").read_text()

    exit_code = main(["clean", requested_run_dir.name, "--state-dir", str(state_dir)])

    assert exit_code == 0
    assert not requested_run_dir.exists()
    assert remaining_run_dir.is_dir()
    assert (remaining_run_dir / "metadata.json").read_text() == remaining_metadata
    assert list((state_dir / "runs").iterdir()) == [remaining_run_dir]


def test_clean_removes_worktree_branch_and_state_dir_only(
    git_repo: Path, tmp_path: Path
) -> None:
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


def test_clean_refuses_tampered_target_repo(git_repo: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir) == 0
    run_dir = next((state_dir / "runs").iterdir())
    metadata_path = run_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["target_repo"] = str(tmp_path / "not-the-target-repo")
    metadata_path.write_text(json.dumps(metadata))

    exit_code = main(["clean", run_dir.name, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert run_dir.is_dir()
    assert Path(metadata["worktree_path"]).is_dir()
    assert metadata["branch"] in _git_output(["branch", "--list"], cwd=git_repo)


def test_clean_preserves_state_when_git_removal_fails(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_factory.cleanup as cleanup_module

    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir) == 0
    run_dir = next((state_dir / "runs").iterdir())
    metadata = json.loads((run_dir / "metadata.json").read_text())

    def fail_removal(_target_repo: Path, _worktree_path: Path) -> None:
        raise cleanup_module.git_ops.GitError("simulated failure")

    monkeypatch.setattr(cleanup_module.git_ops, "remove_worktree", fail_removal)

    exit_code = main(["clean", run_dir.name, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert run_dir.is_dir()
    assert Path(metadata["worktree_path"]).is_dir()
    assert metadata["branch"] in _git_output(["branch", "--list"], cwd=git_repo)


def test_clean_can_resume_after_branch_removal_fails(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_factory.cleanup as cleanup_module

    state_dir = tmp_path / "state"
    assert _run(git_repo, state_dir) == 0
    run_dir = next((state_dir / "runs").iterdir())
    metadata = json.loads((run_dir / "metadata.json").read_text())

    with monkeypatch.context() as context:

        def fail_removal(_target_repo: Path, _branch: str) -> None:
            raise cleanup_module.git_ops.GitError("simulated failure")

        context.setattr(cleanup_module.git_ops, "delete_branch", fail_removal)
        assert main(["clean", run_dir.name, "--state-dir", str(state_dir)]) == 1

    checkpoint = json.loads((run_dir / "metadata.json").read_text())
    assert checkpoint["cleanup"] == {
        "worktree_removed": True,
        "target_repo": str(git_repo.resolve()),
        "worktree_path": metadata["worktree_path"],
        "branch": metadata["branch"],
    }
    assert not Path(metadata["worktree_path"]).exists()
    assert run_dir.is_dir()

    exit_code = main(["clean", run_dir.name, "--state-dir", str(state_dir)])

    assert exit_code == 0
    assert not run_dir.exists()
    assert metadata["branch"] not in _git_output(["branch", "--list"], cwd=git_repo)


def test_clean_rejects_unbound_worktree_removal_checkpoint(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = "forged-checkpoint-run"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    branch = f"factory/{run_id}"
    assert _git(["branch", branch], cwd=git_repo).returncode == 0
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "backend": "fake",
                "target_repo": str(git_repo),
                "worktree_path": str(run_dir / "worktree"),
                "branch": branch,
                "cleanup": {"worktree_removed": True},
            }
        )
    )

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert run_dir.is_dir()
    assert branch in _git_output(["branch", "--list"], cwd=git_repo)


def test_clean_refuses_unknown_run_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    exit_code = main(["clean", "does-not-exist", "--state-dir", str(state_dir)])
    assert exit_code == 1


@pytest.mark.parametrize("run_id_kind", ["traversal", "absolute"])
def test_clean_rejects_traversal_and_absolute_run_ids(
    tmp_path: Path, run_id_kind: str
) -> None:
    state_dir = tmp_path / "state"
    (state_dir / "runs").mkdir(parents=True)
    external_dir = tmp_path / f"{run_id_kind}-sentinel"
    external_dir.mkdir()
    sentinel = external_dir / "keep.txt"
    sentinel.write_text("must remain untouched\n")
    run_id = (
        str(Path("..") / ".." / external_dir.name)
        if run_id_kind == "traversal"
        else str(external_dir.resolve())
    )

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert external_dir.is_dir()
    assert sentinel.read_text() == "must remain untouched\n"
    assert list((state_dir / "runs").iterdir()) == []


@pytest.mark.parametrize("run_id_kind", ["dot", "normalized", "absolute-child"])
def test_clean_rejects_noncanonical_ids_that_resolve_inside_runs(
    tmp_path: Path, run_id_kind: str
) -> None:
    state_dir = tmp_path / "state"
    victim_dir = state_dir / "runs" / "victim"
    victim_dir.mkdir(parents=True)
    sentinel = victim_dir / "keep.txt"
    sentinel.write_text("must remain untouched\n")
    run_id = {
        "dot": "./victim",
        "normalized": "placeholder/../victim",
        "absolute-child": str(victim_dir.resolve()),
    }[run_id_kind]

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert sentinel.read_text() == "must remain untouched\n"


def test_clean_does_not_infer_manual_mode_from_missing_resources(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    run_id = "damaged-automation-run"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "backend": "fake",
                "target_repo": str(tmp_path / "target-repo"),
                "worktree_path": None,
                "branch": None,
            }
        )
    )

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert run_dir.is_dir()
    assert metadata_path.is_file()


def test_clean_rejects_resources_outside_the_run_directory(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = "tampered-run"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    external_worktree = tmp_path / "external-worktree"
    external_worktree.mkdir()
    sentinel = external_worktree / "keep.txt"
    sentinel.write_text("must remain untouched\n")
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "backend": "fake",
                "target_repo": str(git_repo),
                "worktree_path": str(external_worktree),
                "branch": f"factory/{run_id}",
            }
        )
    )

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert run_dir.is_dir()
    assert sentinel.read_text() == "must remain untouched\n"


def test_clean_rejects_worktree_alias_to_external_path(
    git_repo: Path, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = "aliased-worktree-run"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    external_worktree = tmp_path / "external-worktree"
    branch = f"factory/{run_id}"
    result = _git(
        ["worktree", "add", "-b", branch, str(external_worktree), "HEAD"],
        cwd=git_repo,
    )
    assert result.returncode == 0
    sentinel = external_worktree / "keep.txt"
    sentinel.write_text("must remain untouched\n")
    try:
        (run_dir / "worktree").symlink_to(external_worktree, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "backend": "fake",
                "target_repo": str(git_repo),
                "worktree_path": str(external_worktree),
                "branch": branch,
            }
        )
    )

    exit_code = main(["clean", run_id, "--state-dir", str(state_dir)])

    assert exit_code == 1
    assert sentinel.read_text() == "must remain untouched\n"
    assert branch in _git_output(["branch", "--list"], cwd=git_repo)


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
