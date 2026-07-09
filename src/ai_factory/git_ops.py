"""Git isolation helpers (ADR-0002). Git worktrees are the only isolation model
in v1: the target's main working tree is never touched by these operations."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def is_git_repo(path: Path) -> bool:
    result = _run(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def has_commits(path: Path) -> bool:
    """True if the repo has at least one commit (a resolvable HEAD)."""
    return _run(["rev-parse", "--verify", "HEAD"], cwd=path, check=False).returncode == 0


def is_clean(path: Path) -> bool:
    """True if the working tree has no staged, unstaged, or untracked changes."""
    result = _run(["status", "--porcelain"], cwd=path, check=False)
    return result.returncode == 0 and result.stdout.strip() == ""


def resolve_sha(path: Path, ref: str = "HEAD") -> str:
    return _run(["rev-parse", ref], cwd=path).stdout.strip()


def add_worktree(target_repo: Path, worktree_path: Path, branch: str, base_sha: str) -> None:
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["worktree", "add", "-b", branch, str(worktree_path), base_sha], cwd=target_repo)


def commit_worktree_changes(worktree_path: Path, message: str) -> bool:
    """Stage and commit everything in the worktree so the observed diff (including
    brand-new, previously-untracked files) lands on the Run Branch. Plain
    `git diff <base_sha>` never shows untracked files, so a commit is required to
    capture the full change. Returns True if a commit was made (False if the
    backend left the worktree unchanged). Uses an explicit author identity so this
    never depends on the Target Repo having git user config set."""
    _run(["add", "-A"], cwd=worktree_path)
    nothing_staged = _run(["diff", "--cached", "--quiet"], cwd=worktree_path, check=False)
    if nothing_staged.returncode == 0:
        return False
    _run(
        [
            "-c", "user.name=AI Code Factory",
            "-c", "user.email=ai-factory@localhost",
            "commit", "-m", message,
        ],
        cwd=worktree_path,
    )
    return True


def diff_against_base(worktree_path: Path, base_sha: str) -> str:
    return _run(["diff", base_sha, "HEAD"], cwd=worktree_path, check=False).stdout


def changed_files(worktree_path: Path, base_sha: str) -> list[str]:
    result = _run(["diff", "--name-status", base_sha, "HEAD"], cwd=worktree_path, check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def uncommitted_diff(worktree_path: Path) -> str:
    """Diff of every uncommitted change in `worktree_path` against `HEAD`,
    including brand-new untracked files, without permanently staging anything.
    `add -N` (intent-to-add) marks untracked paths so `git diff HEAD` includes
    their full content; diffing against `HEAD` (rather than the index) also
    catches changes to already-tracked files regardless of staged/unstaged
    state. Used to save Contract Violation evidence for a read-only Phase
    without committing."""
    _run(["add", "-N", "-A"], cwd=worktree_path)
    return _run(["diff", "HEAD"], cwd=worktree_path, check=False).stdout


def uncommitted_changed_files(worktree_path: Path) -> list[str]:
    """Name-status list of uncommitted changes against `HEAD`; call after
    `uncommitted_diff` so intent-to-added untracked files are included."""
    result = _run(["diff", "--name-status", "HEAD"], cwd=worktree_path, check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def branch_exists(target_repo: Path, branch: str) -> bool:
    """`git branch --list` prefixes the checked-out-here branch with `* ` and a
    branch checked out in another linked worktree with `+ ` — strip either."""
    result = _run(["branch", "--list", branch], cwd=target_repo, check=False)
    return any(
        line.strip().lstrip("*+").strip() == branch for line in result.stdout.splitlines()
    )


def remove_worktree(target_repo: Path, worktree_path: Path) -> None:
    """Remove a factory-owned worktree. `--force` is safe here: the worktree only
    ever holds factory-committed changes (see `commit_worktree_changes`), never the
    target's main working tree."""
    _run(["worktree", "remove", "--force", str(worktree_path)], cwd=target_repo, check=False)


def delete_branch(target_repo: Path, branch: str) -> None:
    """Force-delete a factory-owned `factory/<run-id>` branch (never merged, so
    plain `-d` would refuse)."""
    _run(["branch", "-D", branch], cwd=target_repo, check=False)
