"""Scoped cleanup of factory-owned resources (ADR-0007, ADR-0012). Removes only
the Run's worktree, its `factory/<run-id>` branch, and its State Dir entry —
never the target's working tree, other branches, remotes, or user files."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import git_ops
from .runs import RunNotFoundError, list_run_ids, load_run_metadata, run_dir


class CleanError(RuntimeError):
    pass


def clean_run(state_dir: Path, run_id: str) -> None:
    target_run_dir = run_dir(state_dir, run_id)
    if not target_run_dir.exists():
        raise CleanError(f"run '{run_id}' not found under {state_dir}")

    try:
        metadata = load_run_metadata(state_dir, run_id)
    except RunNotFoundError:
        metadata = None

    if metadata is not None:
        target_repo = Path(metadata["target_repo"])
        worktree_path = Path(metadata["worktree_path"])
        branch = metadata["branch"]
        if target_repo.exists() and git_ops.is_git_repo(target_repo):
            if worktree_path.exists():
                git_ops.remove_worktree(target_repo, worktree_path)
            if git_ops.branch_exists(target_repo, branch):
                git_ops.delete_branch(target_repo, branch)

    shutil.rmtree(target_run_dir)


def clean_all(state_dir: Path) -> list[str]:
    cleaned = []
    for run_id in list_run_ids(state_dir):
        clean_run(state_dir, run_id)
        cleaned.append(run_id)
    return cleaned
