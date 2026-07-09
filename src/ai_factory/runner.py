"""Orchestrates one Run's lifecycle through `profile -> risk_classify -> plan
-> [decision gate] -> implement -> verify -> fix-loop -> report` (ADR-0014).

This module builds the Repo Profile, computes a pre-plan Risk Level (informing
the Planning Agent), runs the read-only `plan` Phase (ADR-0004/0010) and
enforces it via git afterwards, recomputes the authoritative post-plan Risk
Level (now also informed by plan-predicted changed files), applies the
Decision Gate, and -- only when the gate permits -- runs the `implement`
Phase, the factory-owned Verification Gate, and a bounded Fix Loop when the
gate fails (ADR-0005, ADR-0007, ADR-0011, ADR-0014). `[review]` lands in a
later issue.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from . import decision_gate, git_ops, profiling, prompt_builder, prompts, risk, safety
from .backend.base import AgentRequest, AgentResult
from .backend.subprocess_backend import SubprocessBackend
from .presets.registry import PRESETS
from .report import render_report
from .run_id import generate_run_id
from .state_dir import resolve_state_dir
from .verify import VerificationResult, run_verification

MANUAL_NOT_IMPLEMENTED = (
    "backend 'manual' is not implemented yet (Manual Mode lands in a later issue); "
    "pass --backend fake for now."
)

# Default bound on the Fix Loop (PRD: "default 1-2 attempts"). Not yet
# CLI/config-overridable -- that lands with config layering (issue 09).
DEFAULT_MAX_FIX_ATTEMPTS = 2

# Tail of a failing command's log fed to the Fix Loop prompt, to keep the Prompt
# Bundle bounded even if the command produced a huge log.
MAX_FAILURE_EXCERPT_CHARS = 2000

_NOT_EXECUTED_HALTED = {
    "status": "not_executed",
    "reason": "halted: the plan Phase committed a Contract Violation",
    "started_at": None,
    "finished_at": None,
}

_NOT_EXECUTED_GATE_PAUSED = {
    "status": "not_executed",
    "reason": "paused: the Decision Gate did not permit automatic continuation",
    "started_at": None,
    "finished_at": None,
}


class RunError(RuntimeError):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _write_prompt_bundle(
    bundle_dir: Path,
    phase: str,
    task: str,
    profile: dict,
    worktree_path: Path,
    extra_context: str | None = None,
) -> tuple[Path, Path, Path]:
    bundle_dir.mkdir(parents=True, exist_ok=True)

    system_text = prompts.SYSTEM_PROMPTS[phase]
    user_text = prompt_builder.build_user_prompt(
        phase, task, profile, worktree_path, extra_context
    )
    combined_text = f"{system_text}\n\n{user_text}"

    system_path = bundle_dir / f"{phase}-system.md"
    user_path = bundle_dir / f"{phase}-user.md"
    combined_path = bundle_dir / f"{phase}-combined.md"
    system_path.write_text(system_text)
    user_path.write_text(user_text)
    combined_path.write_text(combined_text)
    return system_path, user_path, combined_path


def _run_agent_phase(
    backend: SubprocessBackend,
    bundle_dir: Path,
    worktree_path: Path,
    phase: str,
    task: str,
    profile: dict,
    output_path: Path,
    mode: str,
    extra_context: str | None = None,
) -> tuple[AgentResult, str, str]:
    system_path, user_path, combined_path = _write_prompt_bundle(
        bundle_dir, phase, task, profile, worktree_path, extra_context
    )
    request = AgentRequest(
        phase=phase,
        workdir=worktree_path,
        system_prompt_path=system_path,
        user_prompt_path=user_path,
        combined_prompt_path=combined_path,
        output_path=output_path,
        mode=mode,
    )
    started_at = _now()
    result = backend.run(request)
    finished_at = _now()
    return result, started_at, finished_at


def _verify_result_to_dict(verify_result: VerificationResult) -> dict:
    return {
        "degraded": verify_result.degraded,
        "passed": verify_result.passed,
        "commands": [
            {
                "key": result.key,
                "command": result.command,
                "exit_code": result.exit_code,
                "passed": result.passed,
                "log_path": str(result.log_path),
            }
            for result in verify_result.results
        ],
    }


def _failure_excerpt(result: VerificationResult) -> str:
    failing = next(r for r in result.results if not r.passed)
    log_text = failing.log_path.read_text()[-MAX_FAILURE_EXCERPT_CHARS:]
    return (
        f"Command `{failing.command}` (key: {failing.key}) failed with exit "
        f"code {failing.exit_code}:\n\n{log_text}"
    )


def _run_plan_phase(
    backend: SubprocessBackend,
    bundle_dir: Path,
    run_dir: Path,
    worktree_path: Path,
    task: str,
    profile: dict,
    extra_context: str | None = None,
) -> tuple[dict, dict, dict, str | None, str | None]:
    """Runs the read-only `plan` Phase and enforces it via git afterwards.

    Returns `(plan_phase, implement_placeholder, verify_placeholder,
    outcome, outcome_reason)`. `outcome`/`outcome_reason` are set (and the two
    placeholders are `not_executed`) only on a Contract Violation or a plan
    Phase failure, signalling the caller to halt before `implement`.
    """
    plan_path = run_dir / "plan.md"
    plan_result, started_at, finished_at = _run_agent_phase(
        backend,
        bundle_dir,
        worktree_path,
        "plan",
        task,
        profile,
        output_path=plan_path,
        mode="read_only",
        extra_context=extra_context,
    )

    if not git_ops.is_clean(worktree_path):
        (run_dir / "contract-violation.patch").write_text(
            git_ops.uncommitted_diff(worktree_path)
        )
        violation_files = git_ops.uncommitted_changed_files(worktree_path)
        (run_dir / "contract-violation-files.txt").write_text(
            "\n".join(violation_files) + ("\n" if violation_files else "")
        )
        plan_phase = {
            "status": "contract_violation",
            "reason": (
                "the read-only plan Phase modified the worktree; evidence "
                "saved to contract-violation.patch"
            ),
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": plan_result.exit_code,
            "summary": plan_result.summary,
        }
        outcome_reason = (
            "the read-only plan Phase modified the worktree "
            "(see contract-violation.patch)"
        )
        return (
            plan_phase,
            dict(_NOT_EXECUTED_HALTED),
            dict(_NOT_EXECUTED_HALTED),
            "contract_violation",
            outcome_reason,
        )

    if plan_result.exit_code != 0:
        plan_phase = {
            "status": "failed",
            "reason": f"plan phase exited {plan_result.exit_code}",
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": plan_result.exit_code,
            "summary": plan_result.summary,
        }
        outcome_reason = f"plan phase exited {plan_result.exit_code}"
        return plan_phase, dict(_NOT_EXECUTED_HALTED), dict(_NOT_EXECUTED_HALTED), "failed", outcome_reason

    plan_text = plan_path.read_text() if plan_path.exists() else ""
    missing_headings = prompts.missing_plan_headings(plan_text)
    plan_phase = {
        "status": "succeeded",
        "reason": None,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": plan_result.exit_code,
        "summary": plan_result.summary,
        "plan_quality": "degraded" if missing_headings else "ok",
        "missing_headings": missing_headings,
    }
    return plan_phase, {}, {}, None, None


def run_task(
    target: str,
    task: str,
    backend_name: str,
    state_dir_value: str | None,
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    pause_after_plan: bool = False,
    auto: bool = False,
    force_implement: bool = False,
    risk_override: str | None = None,
) -> int:
    if backend_name == "manual":
        raise RunError(MANUAL_NOT_IMPLEMENTED)
    if backend_name not in PRESETS:
        raise RunError(f"unknown backend '{backend_name}'; available: {sorted(PRESETS)}")
    if risk_override is not None and risk_override not in ("low", "medium", "high"):
        raise RunError(f"invalid --risk override '{risk_override}'; must be low, medium, or high")

    target_repo = Path(target).resolve()
    if not git_ops.is_git_repo(target_repo):
        raise RunError(f"target '{target_repo}' is not a git repository")
    if not git_ops.has_commits(target_repo):
        raise RunError(
            f"target '{target_repo}' has no commits; automation requires at least "
            "one commit to pin a Base Ref"
        )
    if not git_ops.is_clean(target_repo):
        raise RunError(
            f"target '{target_repo}' has a dirty working tree; commit or stash "
            "your changes before running automation (the Factory never stashes, "
            "resets, or copies the target working tree for you)"
        )

    state_dir = resolve_state_dir(state_dir_value)
    run_id = generate_run_id(task)
    run_dir = state_dir / "runs" / run_id
    if run_dir.exists():
        raise RunError(f"run id collision: '{run_id}' already exists at {run_dir}")
    run_dir.mkdir(parents=True)

    started_at = _now()
    base_ref = "HEAD"
    base_sha = git_ops.resolve_sha(target_repo, base_ref)
    branch = f"factory/{run_id}"
    worktree_path = run_dir / "worktree"

    git_ops.add_worktree(target_repo, worktree_path, branch, base_sha)

    # Built once, up front: the plan Phase needs the Repo Profile as an input
    # (PRD story 20), and the same profile is reused for the Verification Gate
    # below so it is never re-derived mid-Run.
    profile = profiling.build_profile(worktree_path)

    bundle_dir = run_dir / "bundles"
    backend = SubprocessBackend(PRESETS[backend_name], log_dir=run_dir / "logs")

    phases: dict[str, dict] = {}
    fix_attempts: list[dict] = []

    # `risk_classify` (ADR-0014): a pre-plan Risk Level, computed from task text
    # and the Repo Profile alone (no plan-predicted files exist yet), fed to the
    # Planning Agent as informational context. No model call.
    pre_plan_level, pre_plan_reasons = risk.classify(task, profile)
    plan_extra_context = risk.render_pre_plan_context(pre_plan_level, pre_plan_reasons)

    plan_phase, implement_placeholder, verify_placeholder, halt_outcome, halt_reason = (
        _run_plan_phase(
            backend, bundle_dir, run_dir, worktree_path, task, profile, plan_extra_context
        )
    )
    phases["plan"] = plan_phase

    if halt_outcome is not None:
        phases["implement"] = implement_placeholder
        phases["verify"] = verify_placeholder
        outcome = halt_outcome
        outcome_reason = halt_reason
        # A halted plan Phase never reaches the Decision Gate; record the
        # pre-plan classification since it is all that was ever computed.
        risk_result = {
            "level": pre_plan_level,
            "reasons": pre_plan_reasons,
            "auto_continue_allowed": pre_plan_level == "low",
            "overridden_by_user": False,
        }
        gate_info = {"paused": None, "reason": None, "force_implement_used": False}
    else:
        # Decision Gate (ADR-0014): recompute the authoritative, post-plan Risk
        # Level -- now also informed by plan-predicted changed files -- then
        # decide whether automation continues into `implement`.
        plan_text = (run_dir / "plan.md").read_text() if (run_dir / "plan.md").exists() else ""
        predicted_files = risk.extract_predicted_files(plan_text)
        computed_level, computed_reasons = risk.classify(task, profile, predicted_files)

        if risk_override is not None:
            final_level = risk_override
            final_reasons = computed_reasons + [
                f"overridden by user via --risk to '{risk_override}' "
                f"(computed level was '{computed_level}')"
            ]
            overridden = True
        else:
            final_level = computed_level
            final_reasons = computed_reasons
            overridden = False

        risk_result = {
            "level": final_level,
            "reasons": final_reasons,
            "auto_continue_allowed": final_level == "low",
            "overridden_by_user": overridden,
        }

        gate = decision_gate.decide(
            final_level,
            pause_after_plan=pause_after_plan,
            auto=auto,
            force_implement=force_implement,
        )
        gate_info = {
            "paused": not gate.should_implement,
            "reason": gate.outcome_reason,
            "force_implement_used": gate.force_implement_used,
        }

    if halt_outcome is not None:
        pass
    elif not gate_info["paused"]:
        implement_result, implement_started_at, implement_finished_at = _run_agent_phase(
            backend,
            bundle_dir,
            worktree_path,
            "implement",
            task,
            profile,
            output_path=run_dir / "implement-output.md",
            mode="read_write",
        )
        git_ops.commit_worktree_changes(worktree_path, message=f"implement: {task}")
        implement_status = "succeeded" if implement_result.exit_code == 0 else "failed"
        phases["implement"] = {
            "status": implement_status,
            "reason": (
                None
                if implement_status == "succeeded"
                else f"implement phase exited {implement_result.exit_code}"
            ),
            "started_at": implement_started_at,
            "finished_at": implement_finished_at,
            "exit_code": implement_result.exit_code,
            "summary": implement_result.summary,
        }

        if implement_status != "succeeded":
            outcome = "failed"
            outcome_reason = f"implement phase exited {implement_result.exit_code}"
            phases["verify"] = {
                "status": "not_executed",
                "reason": "implement phase failed; the Verification Gate did not run",
                "started_at": None,
                "finished_at": None,
            }
        else:
            verify_started_at = _now()
            try:
                verify_result = run_verification(
                    worktree_path, profile["commands"], run_dir / "verify" / "attempt-0"
                )
            except safety.DeniedCommandError as exc:
                outcome = "failed"
                outcome_reason = str(exc)
                phases["verify"] = {
                    "status": "failed",
                    "reason": outcome_reason,
                    "started_at": verify_started_at,
                    "finished_at": _now(),
                }
            else:
                if verify_result.degraded:
                    outcome = "implemented_degraded"
                    outcome_reason = "no Verification Gate commands detected (degraded mode)"
                    phases["verify"] = {
                        "status": "skipped",
                        "reason": "no verification commands detected -- degraded mode (ADR-0005)",
                        "started_at": verify_started_at,
                        "finished_at": _now(),
                        **_verify_result_to_dict(verify_result),
                    }
                elif verify_result.passed:
                    outcome = "implemented_verified"
                    outcome_reason = "Verification Gate passed"
                    phases["verify"] = {
                        "status": "succeeded",
                        "reason": None,
                        "started_at": verify_started_at,
                        "finished_at": _now(),
                        **_verify_result_to_dict(verify_result),
                    }
                else:
                    current = verify_result
                    for attempt_num in range(1, max_fix_attempts + 1):
                        extra_context = _failure_excerpt(current)
                        fix_result, fix_started_at, fix_finished_at = _run_agent_phase(
                            backend,
                            bundle_dir,
                            worktree_path,
                            "fix",
                            task,
                            profile,
                            output_path=run_dir / "fix-output.md",
                            mode="read_write",
                            extra_context=extra_context,
                        )
                        git_ops.commit_worktree_changes(
                            worktree_path, message=f"fix attempt {attempt_num}: {task}"
                        )
                        current = run_verification(
                            worktree_path, profile["commands"], run_dir / "verify" / f"attempt-{attempt_num}"
                        )
                        fix_attempts.append(
                            {
                                "attempt": attempt_num,
                                "phase_status": "succeeded" if fix_result.exit_code == 0 else "failed",
                                "exit_code": fix_result.exit_code,
                                "summary": fix_result.summary,
                                "started_at": fix_started_at,
                                "finished_at": fix_finished_at,
                                "verify": _verify_result_to_dict(current),
                            }
                        )
                        if current.passed:
                            break

                    if current.passed:
                        outcome = "implemented_verified"
                        outcome_reason = (
                            f"Verification Gate passed after {len(fix_attempts)} Fix Loop attempt(s)"
                        )
                        verify_status = "succeeded"
                    else:
                        outcome = "implemented_unverified"
                        outcome_reason = (
                            "Verification Gate failed after exhausting the Fix Loop "
                            f"({len(fix_attempts)} attempt(s))"
                        )
                        verify_status = "failed"

                    phases["verify"] = {
                        "status": verify_status,
                        "reason": outcome_reason,
                        "started_at": verify_started_at,
                        "finished_at": _now(),
                        **_verify_result_to_dict(current),
                    }
    else:
        # The Decision Gate paused the Run after `plan.md` (ADR-0014):
        # `implement`/`verify` never run.
        phases["implement"] = dict(_NOT_EXECUTED_GATE_PAUSED)
        phases["verify"] = dict(_NOT_EXECUTED_GATE_PAUSED)
        outcome = "planned"
        outcome_reason = gate_info["reason"]

    diff_text = git_ops.diff_against_base(worktree_path, base_sha)
    files_changed = git_ops.changed_files(worktree_path, base_sha)
    (run_dir / "diff.patch").write_text(diff_text)
    (run_dir / "changed-files.txt").write_text(
        "\n".join(files_changed) + ("\n" if files_changed else "")
    )

    finished_at = _now()
    metadata = {
        "run_id": run_id,
        "task": task,
        "target_repo": str(target_repo),
        "backend": backend_name,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "branch": branch,
        "worktree_path": str(worktree_path),
        "state_dir": str(state_dir),
        "started_at": started_at,
        "finished_at": finished_at,
        "changed_files": files_changed,
        "phases": phases,
        "fix_loop": {
            "max_attempts": max_fix_attempts,
            "attempts": fix_attempts,
        },
        "risk": risk_result,
        "decision_gate": {
            **gate_info,
            "flags": {
                "pause_after_plan": pause_after_plan,
                "auto": auto,
                "force_implement": force_implement,
                "risk_override": risk_override,
            },
        },
        "outcome": outcome,
        "outcome_reason": outcome_reason,
    }

    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "report.md").write_text(render_report(metadata))

    return 0 if outcome in ("implemented_verified", "implemented_degraded", "planned") else 1
