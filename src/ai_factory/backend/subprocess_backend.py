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
        }
        argv = shlex.split(self.command_template.format(**placeholders))

        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = self.log_dir / f"{request.phase}.stdout.log"
        stderr_path = self.log_dir / f"{request.phase}.stderr.log"

        with stdout_path.open("w") as out, stderr_path.open("w") as err:
            proc = subprocess.run(
                argv,
                cwd=request.workdir,
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
