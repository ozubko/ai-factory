"""Persistence for the durable artifacts produced by a Run.

This module owns artifact names and formats so orchestration code only decides
*when* a Run should be published.  Reports and PR bodies are always derived
from the same metadata snapshot that is written to ``metadata.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import git_ops
from .pr_body import render_pr_body
from .report import render_report


@dataclass(frozen=True)
class RunArtifacts:
    """Read and write the files owned by one Run directory."""

    run_dir: Path

    def write_profile(self, profile: dict) -> None:
        self._write_json("profile.json", profile)

    def capture_changes(self, worktree_path: Path, base_sha: str) -> list[str]:
        """Persist the git-observed diff and return its changed-file entries."""
        diff_text = git_ops.diff_against_base(worktree_path, base_sha)
        changed_files = git_ops.changed_files(worktree_path, base_sha)
        (self.run_dir / "diff.patch").write_text(diff_text)
        (self.run_dir / "changed-files.txt").write_text(
            "\n".join(changed_files) + ("\n" if changed_files else "")
        )
        return changed_files

    def capture_contract_violation(self, worktree_path: Path) -> None:
        """Persist all uncommitted evidence left by a read-only Phase."""
        diff_text = git_ops.uncommitted_diff(worktree_path)
        changed_files = git_ops.uncommitted_changed_files(worktree_path)
        (self.run_dir / "contract-violation.patch").write_text(diff_text)
        (self.run_dir / "contract-violation-files.txt").write_text(
            "\n".join(changed_files) + ("\n" if changed_files else "")
        )

    def publish(self, metadata: dict) -> None:
        """Write metadata and both human-facing views from one snapshot."""
        self.write_metadata(metadata)
        (self.run_dir / "report.md").write_text(render_report(metadata))
        (self.run_dir / "pr-body.md").write_text(render_pr_body(metadata))

    def write_metadata(self, metadata: dict) -> None:
        """Persist an updated metadata checkpoint without regenerating views."""
        self._write_json("metadata.json", metadata)

    def _write_json(self, filename: str, value: dict) -> None:
        (self.run_dir / filename).write_text(json.dumps(value, indent=2) + "\n")
