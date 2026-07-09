"""Programmatic per-phase user-prompt assembly (ADR-0010, CONTEXT.md: Prompt
Bundle).

No template engine: a deterministic string builder assembles task + Repo
Profile + detected commands + a bounded file tree + surfaced Repository
Instructions (secret-redacted) into one user prompt per Phase. Same inputs
always produce the same prompt text.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import safety
from .profiling import IGNORED_DIR_NAMES

# Caps how many file-tree entries are embedded in a Prompt Bundle, so a huge
# repo can't blow up the prompt; truncation is noted rather than silently
# applied (mirrors profiling.py's instruction-size cap).
MAX_FILE_TREE_ENTRIES = 200


def _bounded_file_tree(worktree: Path) -> tuple[list[str], bool]:
    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(worktree):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIR_NAMES)
        rel_dir = Path(dirpath).relative_to(worktree)
        for filename in sorted(filenames):
            rel_path = filename if str(rel_dir) == "." else (rel_dir / filename).as_posix()
            entries.append(rel_path)
    entries.sort()
    truncated = len(entries) > MAX_FILE_TREE_ENTRIES
    return entries[:MAX_FILE_TREE_ENTRIES], truncated


def _format_commands(commands: dict) -> list[str]:
    if not commands:
        return ["(none detected -- the Verification Gate will run in degraded mode)"]
    return [
        f"- {key}: `{info['command']}` (source: {info['source']}, confidence: {info['confidence']})"
        for key, info in sorted(commands.items())
    ]


def _format_instructions(instructions: list[dict]) -> list[str]:
    if not instructions:
        return ["(none found)"]
    lines: list[str] = []
    for entry in instructions:
        note = " (truncated)" if entry.get("truncated") else ""
        lines.append(f"### {entry['path']}{note}")
        lines.append("")
        lines.append(safety.redact_secrets(entry.get("content", "")))
        lines.append("")
    return lines


def build_user_prompt(
    phase: str,
    task: str,
    profile: dict,
    worktree: Path,
    extra_context: str | None = None,
) -> str:
    """Assemble the `phase` user prompt from run state. Deterministic: the same
    `(phase, task, profile, worktree contents, extra_context)` always produces
    the same text."""
    file_entries, tree_truncated = _bounded_file_tree(worktree)

    lines = [
        "## Task",
        "",
        task,
        "",
        "## Repo Profile",
        "",
        f"- ecosystem: {profile.get('ecosystem', 'unknown')}",
        f"- degraded: {profile.get('degraded', True)}",
        "",
        "## Detected verification commands",
        "",
        *_format_commands(profile.get("commands") or {}),
        "",
        "## File tree" + (" (truncated)" if tree_truncated else ""),
        "",
        "```",
        *file_entries,
        "```",
        "",
        "## Repository Instructions",
        "",
        *_format_instructions(profile.get("instructions") or []),
    ]

    if extra_context:
        lines += ["## Additional context", "", extra_context, ""]

    return "\n".join(lines) + "\n"
