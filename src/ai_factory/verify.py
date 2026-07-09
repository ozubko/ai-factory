"""The Verification Gate (ADR-0005, ADR-0007, ADR-0011, ADR-0014; CONTEXT.md:
Verification Gate).

Factory-owned and authoritative: runs the Repo Profile's detected verification
commands inside the worktree, in a fixed order, capturing one log file per
command under `verify/`. Agent-claimed results are never consulted here. Every
command is checked against the Command Deny-list *before any command runs* — a
match refuses the whole gate rather than executing anything (ADR-0007).
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import safety

# Fixed execution order (ADR-0005): install first, build last. The gate stops at
# the first failing command rather than running the rest against a broken state.
COMMAND_ORDER: tuple[str, ...] = ("install", "lint", "typecheck", "test", "build")


@dataclass(frozen=True)
class CommandResult:
    key: str
    command: str
    exit_code: int
    log_path: Path

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class VerificationResult:
    """`degraded=True` means no commands were available to run at all (loud
    degraded mode, ADR-0005) — distinct from `results` being non-empty but
    containing a failure."""

    degraded: bool
    results: tuple[CommandResult, ...]

    @property
    def passed(self) -> bool:
        return not self.degraded and all(result.passed for result in self.results)


def run_verification(
    worktree: Path, commands: dict[str, dict], log_dir: Path
) -> VerificationResult:
    """Run `commands` (the Repo Profile shape: `{key: {"command": ..., ...}}`) in
    `worktree`, in `COMMAND_ORDER`, stopping at the first failure. Every command
    is Deny-list-checked before any of them run, so a match refuses the whole
    gate without side effects. Returns `degraded=True` (no commands to run) when
    `commands` is empty."""
    ordered = [(key, commands[key]["command"]) for key in COMMAND_ORDER if key in commands]

    for _key, command_text in ordered:
        safety.check_command(command_text)

    if not ordered:
        return VerificationResult(degraded=True, results=())

    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[CommandResult] = []
    for key, command_text in ordered:
        log_path = log_dir / f"{key}.log"
        argv = shlex.split(command_text)
        with log_path.open("w") as log_file:
            proc = subprocess.run(
                argv, cwd=worktree, stdout=log_file, stderr=subprocess.STDOUT
            )
        result = CommandResult(
            key=key, command=command_text, exit_code=proc.returncode, log_path=log_path
        )
        results.append(result)
        if not result.passed:
            break

    return VerificationResult(degraded=False, results=tuple(results))
