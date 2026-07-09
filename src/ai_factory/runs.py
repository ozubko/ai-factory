"""Run listing and status (ADR-0011, ADR-0012, CONTEXT.md: Run, Run Outcome,
State Dir). Runs are durable — this module only reads what `runner.py` wrote;
it never mutates or deletes (see `cleanup.py` for that)."""

from __future__ import annotations

import json
from pathlib import Path


class RunNotFoundError(RuntimeError):
    pass


def runs_dir(state_dir: Path) -> Path:
    return state_dir / "runs"


def run_dir(state_dir: Path, run_id: str) -> Path:
    return runs_dir(state_dir) / run_id


def load_run_metadata(state_dir: Path, run_id: str) -> dict:
    metadata_path = run_dir(state_dir, run_id) / "metadata.json"
    if not metadata_path.exists():
        raise RunNotFoundError(f"run '{run_id}' not found under {state_dir}")
    return json.loads(metadata_path.read_text())


def list_run_ids(state_dir: Path) -> list[str]:
    directory = runs_dir(state_dir)
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_dir())


def list_runs(state_dir: Path) -> list[dict]:
    """One entry per Run directory. A Run whose `metadata.json` is missing (e.g.
    a Run interrupted before it was written) is still listed, with `outcome`
    'unknown' rather than being silently dropped."""
    runs = []
    for run_id in list_run_ids(state_dir):
        try:
            runs.append(load_run_metadata(state_dir, run_id))
        except RunNotFoundError:
            runs.append(
                {
                    "run_id": run_id,
                    "task": None,
                    "outcome": "unknown",
                    "outcome_reason": "metadata.json missing (run may have been interrupted)",
                    "phases": {},
                }
            )
    return runs
