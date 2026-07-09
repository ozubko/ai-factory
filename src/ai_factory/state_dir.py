"""State Dir resolution (ADR-0012, CONTEXT.md: State Dir).

All run state lives outside the Target Repo. Precedence: `--state-dir` CLI flag >
`AI_FACTORY_STATE_DIR` env var > `${XDG_STATE_HOME:-~/.local/state}/ai-factory`.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_state_dir(cli_value: str | None = None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()

    env_value = os.environ.get("AI_FACTORY_STATE_DIR")
    if env_value:
        return Path(env_value).expanduser().resolve()

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state_home).expanduser() if xdg_state_home else Path.home() / ".local" / "state"
    return (base / "ai-factory").resolve()
