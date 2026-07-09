"""Plain-text rendering for `ai-factory status` and `ai-factory list`
(CONTEXT.md: Run Outcome, Phase)."""

from __future__ import annotations


def render_status(metadata: dict) -> str:
    lines = [
        f"Run: {metadata['run_id']}",
        f"Outcome: {metadata.get('outcome', 'unknown')}",
    ]
    reason = metadata.get("outcome_reason")
    if reason:
        lines.append(f"Reason: {reason}")
    lines.append("Phases:")
    phases = metadata.get("phases") or {}
    if not phases:
        lines.append("  (none)")
    for name, phase in phases.items():
        lines.append(f"  {name}: {phase.get('status', 'unknown')}")
    return "\n".join(lines)


def render_list(runs: list[dict]) -> str:
    if not runs:
        return "(no runs)"
    lines = [f"{'RUN ID':<40}  {'OUTCOME':<24}  TASK"]
    for run in runs:
        run_id = run.get("run_id", "?")
        outcome = run.get("outcome", "unknown")
        task = run.get("task") or ""
        lines.append(f"{run_id:<40}  {outcome:<24}  {task}")
    return "\n".join(lines)
