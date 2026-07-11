"""Scoped cleanup of factory-owned resources (ADR-0007, ADR-0012). Removes only
the Run's worktree, its `factory/<run-id>` branch, and its State Dir entry —
never the target's working tree, other branches, remotes, or user files."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import git_ops
from .runs import (
    InvalidRunIdError,
    RunNotFoundError,
    list_run_ids,
    load_run_metadata,
    run_dir,
)
from .run_artifacts import RunArtifacts


class CleanError(RuntimeError):
    pass


def clean_run(state_dir: Path, run_id: str) -> None:
    try:
        target_run_dir = run_dir(state_dir, run_id)
    except InvalidRunIdError as exc:
        raise CleanError(str(exc)) from exc
    if not target_run_dir.exists():
        raise CleanError(f"run '{run_id}' not found under {state_dir}")

    try:
        metadata = load_run_metadata(state_dir, run_id)
    except RunNotFoundError:
        metadata = None

    if metadata is not None:
        backend = metadata.get("backend")
        worktree_value = metadata.get("worktree_path")
        branch = metadata.get("branch")
        if backend == "manual":
            if (
                "worktree_path" not in metadata
                or "branch" not in metadata
                or worktree_value is not None
                or branch is not None
            ):
                raise CleanError(
                    f"manual run '{run_id}' has unexpected git resource metadata; "
                    "refusing cleanup"
                )
            # Manual Mode owns no git resources; only its durable Run directory
            # needs to be removed.
            shutil.rmtree(target_run_dir)
            return
        if not isinstance(backend, str):
            raise CleanError(f"run '{run_id}' has no valid backend; refusing cleanup")
        if not isinstance(worktree_value, str) or not isinstance(branch, str):
            raise CleanError(
                f"run '{run_id}' has incomplete git resource metadata; refusing cleanup"
            )

        worktree_path = Path(worktree_value).absolute()
        expected_worktree = target_run_dir / "worktree"
        expected_branch = f"factory/{run_id}"
        if (
            worktree_path != expected_worktree
            or expected_worktree.resolve() != expected_worktree
            or branch != expected_branch
        ):
            raise CleanError(
                f"run '{run_id}' references resources outside its factory-owned "
                "worktree or branch; refusing cleanup"
            )

        target_repo_value = metadata.get("target_repo")
        if not isinstance(target_repo_value, str):
            raise CleanError(
                f"run '{run_id}' has no valid Target Repo path; refusing cleanup"
            )
        target_repo = Path(target_repo_value)
        if not target_repo.is_dir() or not git_ops.is_git_repo(target_repo):
            raise CleanError(
                f"run '{run_id}' Target Repo is unavailable or invalid; refusing cleanup"
            )
        cleanup_checkpoint = metadata.get("cleanup") or {}
        worktree_removed = cleanup_checkpoint.get("worktree_removed") is True
        if worktree_removed:
            expected_checkpoint = {
                "worktree_removed": True,
                "target_repo": str(target_repo.resolve()),
                "worktree_path": str(worktree_path),
                "branch": branch,
            }
            if cleanup_checkpoint != expected_checkpoint:
                raise CleanError(
                    f"run '{run_id}' has an invalid cleanup checkpoint; "
                    "refusing cleanup"
                )
            if worktree_path.exists():
                raise CleanError(
                    f"run '{run_id}' has inconsistent cleanup state; refusing cleanup"
                )
        else:
            registered_branch = git_ops.registered_worktree_branch(
                target_repo, worktree_path
            )
            if registered_branch != branch:
                raise CleanError(
                    f"run '{run_id}' worktree is not registered to its Target Repo "
                    "and Run Branch; refusing cleanup"
                )
        try:
            if not worktree_removed and worktree_path.exists():
                git_ops.remove_worktree(target_repo, worktree_path)
                metadata["cleanup"] = {
                    "worktree_removed": True,
                    "target_repo": str(target_repo.resolve()),
                    "worktree_path": str(worktree_path),
                    "branch": branch,
                }
                RunArtifacts(target_run_dir).write_metadata(metadata)
            if git_ops.branch_exists(target_repo, branch):
                git_ops.delete_branch(target_repo, branch)
        except (OSError, git_ops.GitError) as exc:
            raise CleanError(
                f"failed to remove git resources for run '{run_id}'; "
                "Run state was preserved"
            ) from exc

    shutil.rmtree(target_run_dir)


def clean_all(state_dir: Path) -> list[str]:
    cleaned = []
    for run_id in list_run_ids(state_dir):
        clean_run(state_dir, run_id)
        cleaned.append(run_id)
    return cleaned
