"""The AgentBackend seam (ADR-0001, ADR-0004).

Backends are side-effecting: `implement`/`fix` mutate the worktree in place and
the Factory observes the result via git, rather than backends returning patches.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentRequest:
    """One Phase's inputs to a Backend, per the Prompt Bundle contract (ADR-0006)."""

    phase: str
    workdir: Path
    system_prompt_path: Path
    user_prompt_path: Path
    combined_prompt_path: Path
    output_path: Path
    mode: str  # "read_only" | "read_write"
    timeout: float | None = None


@dataclass(frozen=True)
class AgentResult:
    """A Backend's outcome for one Phase. Never authoritative about repo changes —
    the Factory captures those separately via git (ADR-0004)."""

    exit_code: int
    stdout_path: Path
    stderr_path: Path
    output_path: Path
    summary: str | None = None


class AgentBackend:
    """Base class for pluggable agent backends (ADR-0001)."""

    name = "base"

    def run(self, request: AgentRequest) -> AgentResult:
        raise NotImplementedError
