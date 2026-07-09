"""A generic, command-template-driven backend (ADR-0006).

Vendors (Codex, Claude, the Fake Agent) are config Presets that parameterize this
one backend's command template — never bespoke backend classes.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from .base import AgentBackend, AgentRequest, AgentResult


class SubprocessBackend(AgentBackend):
    name = "subprocess"

    def __init__(self, command_template: str, log_dir: Path) -> None:
        self.command_template = command_template
        self.log_dir = log_dir

    def run(self, request: AgentRequest) -> AgentResult:
        placeholders = {
            "python": sys.executable,
            "phase": request.phase,
            "workdir": str(request.workdir),
            "system_prompt_path": str(request.system_prompt_path),
            "user_prompt_path": str(request.user_prompt_path),
            "combined_prompt_path": str(request.combined_prompt_path),
            "output_path": str(request.output_path),
            # Prompt bundles and output_path live outside the worktree, in the
            # run directory (ADR-0002/0012) — a real CLI's own directory
            # sandboxing (e.g. `--add-dir`) needs a path to grant access to.
            "run_dir": str(request.output_path.parent),
        }
        argv = shlex.split(self.command_template.format(**placeholders))

        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = self.log_dir / f"{request.phase}.stdout.log"
        stderr_path = self.log_dir / f"{request.phase}.stderr.log"

        # No shell is involved (argv exec only), so a template can't use `<` to
        # redirect a file into stdin. Pipe the combined prompt directly instead —
        # this is the only way a CLI that reads its prompt from stdin (rather
        # than a positional argument) can receive it.
        with (
            stdout_path.open("w") as out,
            stderr_path.open("w") as err,
            request.combined_prompt_path.open("rb") as prompt_in,
        ):
            proc = subprocess.run(
                argv,
                cwd=request.workdir,
                stdin=prompt_in,
                stdout=out,
                stderr=err,
                timeout=request.timeout,
            )

        # The backend guarantees the phase's output artifact exists (ADR-0004/0006):
        # the CLI may write it itself, otherwise captured stdout becomes the artifact.
        if not request.output_path.exists():
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            request.output_path.write_text(stdout_path.read_text())

        summary = request.output_path.read_text().strip()[:500] or None

        return AgentResult(
            exit_code=proc.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            output_path=request.output_path,
            summary=summary,
        )
