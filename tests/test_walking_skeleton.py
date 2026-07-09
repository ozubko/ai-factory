import json
import subprocess
from pathlib import Path

from ai_factory.cli import main


def _git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_run_with_fake_backend_produces_expected_artifacts(git_repo: Path, tmp_path: Path) -> None:
    target = git_repo
    original_head = _git_output(["rev-parse", "HEAD"], cwd=target)
    state_dir = tmp_path / "state"

    exit_code = main(
        [
            "run",
            str(target),
            "add a fake change",
            "--backend",
            "fake",
            "--state-dir",
            str(state_dir),
        ]
    )

    assert exit_code == 0

    # The target's working tree is unchanged.
    assert _git_output(["status", "--porcelain"], cwd=target) == ""
    assert _git_output(["rev-parse", "HEAD"], cwd=target) == original_head

    run_dirs = list((state_dir / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    metadata = json.loads((run_dir / "metadata.json").read_text())
    assert metadata["base_sha"] == original_head
    assert metadata["backend"] == "fake"
    assert metadata["outcome"] == "implemented_degraded"
    assert metadata["phases"]["implement"]["status"] == "succeeded"

    diff_text = (run_dir / "diff.patch").read_text()
    assert "FAKE_AGENT_CHANGE.md" in diff_text

    changed_files_text = (run_dir / "changed-files.txt").read_text()
    assert "FAKE_AGENT_CHANGE.md" in changed_files_text

    report_text = (run_dir / "report.md").read_text()
    assert "Run Report" in report_text
    assert "implemented_degraded" in report_text

    branch = metadata["branch"]
    assert branch == f"factory/{metadata['run_id']}"
    branch_list = _git_output(["branch", "--list", branch], cwd=target)
    assert branch in branch_list

    worktree_path = Path(metadata["worktree_path"])
    assert worktree_path.is_dir()
    assert not str(worktree_path).startswith(str(target))
    assert (worktree_path / "FAKE_AGENT_CHANGE.md").exists()


def test_run_refuses_on_non_git_target(tmp_path: Path) -> None:
    target = tmp_path / "not-a-repo"
    target.mkdir()
    state_dir = tmp_path / "state"

    exit_code = main(
        [
            "run",
            str(target),
            "some task",
            "--backend",
            "fake",
            "--state-dir",
            str(state_dir),
        ]
    )

    assert exit_code == 1
    assert not (state_dir / "runs").exists()
