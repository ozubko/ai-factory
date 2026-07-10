"""A generic, command-template-driven backend (ADR-0006).

Vendors (Codex, Claude, the Fake Agent) are config Presets that parameterize this
one backend's command template — never bespoke backend classes.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .base import AgentBackend, AgentRequest, AgentResult

PresetSpec = str | Mapping[str, Any]


class SubprocessBackend(AgentBackend):
    name = "subprocess"

    def __init__(self, command_template: PresetSpec, log_dir: Path) -> None:
        self.command_template = command_template
        self.log_dir = log_dir

    def _placeholders(self, request: AgentRequest) -> dict[str, str]:
        sandbox_mode = "read-only" if request.mode == "read_only" else "workspace-write"
        return {
            "python": sys.executable,
            "phase": request.phase,
            "mode": request.mode,
            # Backend presets can use this for phase-aware tool sandboxing. For
            # example, Codex can run plan/review with `read-only` but
            # implement/fix with `workspace-write`. The Factory still enforces
            # read-only Phases with git afterwards; this is defense-in-depth.
            "sandbox_mode": sandbox_mode,
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

    def _render_argv(self, request: AgentRequest) -> list[str]:
        placeholders = self._placeholders(request)

        if isinstance(self.command_template, str):
            # Backward-compatible legacy command-template mode. This remains
            # useful for simple user config, but paths with spaces are safer in
            # the structured `argv = [...]` format because each token is rendered
            # independently and never reparsed by a shell-like splitter.
            return shlex.split(self.command_template.format(**placeholders))

        argv_value = self.command_template.get("argv")
        if argv_value is not None:
            if not isinstance(argv_value, Sequence) or isinstance(argv_value, (str, bytes)):
                raise TypeError("subprocess preset `argv` must be a list of strings")
            argv: list[str] = []
            for token in argv_value:
                if not isinstance(token, str):
                    raise TypeError("subprocess preset `argv` must contain only strings")
                argv.append(token.format(**placeholders))
            return argv

        command_value = self.command_template.get("command")
        if isinstance(command_value, str):
            return shlex.split(command_value.format(**placeholders))

        raise TypeError(
            "subprocess preset must be either a string, `{argv = [...]}`, or `{command = ...}`"
        )

    def run(self, request: AgentRequest) -> AgentResult:
        argv = self._render_argv(request)

        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = self.log_dir / f"{request.phase}.stdout.log"
        stderr_path = self.log_dir / f"{request.phase}.stderr.log"

        # No shell is involved, so a template can't use `<` to redirect a file
        # into stdin. Pipe the combined prompt directly instead — this is the
        # only way a CLI that reads its prompt from stdin (rather than a
        # positional argument) can receive it.
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
