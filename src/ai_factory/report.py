"""Renders the Run Report (ADR-0005/0011/0014, CONTEXT.md: Run Report).

Full PR body and review sections land in later issues (07); this report leads
with the Risk Assessment and the factory-verified-vs-agent-claimed distinction
(the Verification Gate is authoritative, the agent's own claims are advisory
only) and ends with concrete next steps.
"""

from __future__ import annotations


def _format_risk_body(risk: dict, gate: dict) -> list[str]:
    lines = [
        f"- Level: **{risk.get('level', 'unknown')}**"
        + (" (overridden by user via --risk)" if risk.get("overridden_by_user") else ""),
        "- Reasons:",
        *[f"  - {reason}" for reason in (risk.get("reasons") or [])],
        f"- Auto-continue allowed by the classifier: {risk.get('auto_continue_allowed')}",
    ]
    if gate.get("paused") is None:
        lines.append("- Decision Gate: did not run (the plan Phase halted first)")
    elif gate.get("paused"):
        lines.append(f"- Decision Gate: **paused** after plan.md -- {gate.get('reason') or 'n/a'}")
    else:
        reason = (
            "risk classified 'low'; auto-continued"
            if not gate.get("force_implement_used")
            else "continued via --force-implement despite medium/high risk"
        )
        lines.append(f"- Decision Gate: **continued** to implement -- {reason}")
    return lines


def _format_verify_body(phase: dict) -> list[str]:
    if phase.get("status") == "not_executed":
        return ["- (gate did not run: " + (phase.get("reason") or "n/a") + ")"]
    if phase.get("degraded"):
        return ["- degraded: no verification commands were detected (ADR-0005)"]
    commands = phase.get("commands")
    if not commands:
        return [f"- (gate did not run: {phase.get('reason') or 'n/a'})"]
    return [
        f"- [{'PASS' if command['passed'] else 'FAIL'}] {command['key']}: "
        f"`{command['command']}` (exit {command['exit_code']}) -> {command['log_path']}"
        for command in commands
    ]


def _format_plan_body(phase: dict) -> list[str]:
    if not phase:
        return ["- (plan phase did not run)"]
    if phase.get("status") == "contract_violation":
        return [
            "- **Contract Violation:** this read-only Phase modified the "
            "worktree; evidence saved to `contract-violation.patch`",
        ]
    if phase.get("status") == "failed":
        return [f"- (plan phase failed: {phase.get('reason') or 'n/a'})"]
    lines = [f"- status: {phase.get('status', 'unknown')}"]
    quality = phase.get("plan_quality")
    if quality:
        lines.append(f"- plan quality: {quality}")
    missing = phase.get("missing_headings") or []
    if missing:
        lines.append("- missing headings: " + ", ".join(missing))
    return lines


def _format_fix_attempts(attempts: list[dict]) -> list[str]:
    lines: list[str] = []
    for attempt in attempts:
        gate_passed = attempt["verify"].get("passed")
        lines.append(
            f"- Attempt {attempt['attempt']}: agent exit {attempt['exit_code']} "
            f"({attempt.get('summary') or 'no summary'}); "
            f"gate after this attempt: {'PASSED' if gate_passed else 'still failing'}"
        )
    return lines


def render_report(metadata: dict) -> str:
    run_id = metadata["run_id"]
    outcome = metadata["outcome"]
    outcome_reason = metadata.get("outcome_reason") or "n/a"
    phases = metadata.get("phases") or {}
    plan_phase = phases.get("plan", {})
    implement_phase = phases.get("implement", {})
    verify_phase = phases.get("verify", {})
    summary = implement_phase.get("summary") or "(no summary captured)"
    fix_attempts = (metadata.get("fix_loop") or {}).get("attempts") or []
    risk = metadata.get("risk") or {}
    gate = metadata.get("decision_gate") or {}

    lines = [
        f"# Run Report: {run_id}",
        "",
        f"**Outcome:** {outcome}",
        f"**Why:** {outcome_reason}",
        "",
        "## Risk Assessment",
        "",
        *_format_risk_body(risk, gate),
        "",
        "## Plan",
        "",
        *_format_plan_body(plan_phase),
        "",
        "## Factory-verified vs agent-claimed",
        "",
        "- **Factory-verified (authoritative):** the diff below is observed from "
        "git, and the Verification Gate results below are run by the Factory "
        "itself -- neither is the agent's claim.",
        f"- **Agent-claimed (advisory only):** {summary}",
        "",
        "## Verification Gate (factory-verified, authoritative)",
        "",
        f"Status: {verify_phase.get('status', 'not_executed')}",
        "",
        *_format_verify_body(verify_phase),
        "",
    ]

    if fix_attempts:
        lines += [
            "## Fix Loop (bounded agent retries; each retry re-runs the "
            "authoritative Verification Gate)",
            "",
            *_format_fix_attempts(fix_attempts),
            "",
        ]

    lines += [
        "## Changed files",
        "",
        "```",
        *(metadata.get("changed_files") or ["(none)"]),
        "```",
        "",
        "## Next steps",
        "",
        f"- Inspect the worktree: `cd {metadata['worktree_path']}`",
        f"- Review the diff: `git -C {metadata['target_repo']} diff "
        f"{metadata['base_sha']} {metadata['branch']}`",
        f"- Switch to the branch: `git -C {metadata['target_repo']} switch {metadata['branch']}`",
        "",
    ]
    return "\n".join(lines)
