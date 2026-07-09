import shutil
import subprocess
from pathlib import Path

import pytest


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not available on PATH")

    repo = tmp_path / "target-repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-m", "initial commit"], cwd=repo)
    return repo
