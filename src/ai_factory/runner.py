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
from typing import Any

from . import config, decision_gate, git_ops, profiling, prompt_builder, prompts, risk, runs, safety
from .backend.base import AgentRequest, AgentResult
from .backend.subprocess_backend import SubprocessBackend
from .pr_body import render_pr_body
from .report import render_report
from .run_id import generate_run_id
from .state_dir import resolve_state_dir
from .verify import VerificationResult, run_verification

# Default bound on the Fix Loop (PRD: "default 1-2 attempts"). Not yet
# CLI/config-overridable.
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

_SKIPPED_REVIEW_NOT_REQUESTED = {
    "status": "skipped",
    "reason": "review not requested (pass --review to enable)",
    "started_at": None,
    "finished_at": None,
}

_NOT_EXECUTED_REVIEW = {
    "status": "not_executed",
    "reason": "review did not run: the Run never reached a completed implementation",
    "started_at": None,
    "finished_at": None,
}

# Placeholders for Manual Mode (ADR-0001/0006): no Backend is ever invoked, so
# every Phase is `not_executed` and no worktree/branch/git refs exist.
_NOT_EXECUTED_MANUAL = {
    "status": "not_executed",
    "reason": (
        "Manual Mode: no Backend was invoked; drive this Phase yourself from "
        "the prepared bundle, or re-run with a real --backend for staged "
        "driving (`ai-factory plan`)"
    ),
    "started_at": None,
    "finished_at": None,
}

# Placeholders for staged driving (PRD story 60): the Phase is real (a worktree
# and branch exist) but simply hasn't been driven yet -- a later, separate
# invocation of `ai-factory implement`/`review <run-id>` will run it.
_NOT_EXECUTED_STAGED_IMPLEMENT = {
    "status": "not_executed",
    "reason": "staged mode: not yet run; continue with `ai-factory implement <run-id>`",
    "started_at": None,
    "finished_at": None,
}

_NOT_EXECUTED_STAGED_REVIEW = {
    "status": "not_executed",
    "reason": "staged mode: not yet run; use `ai-factory review <run-id>` once implement has completed",
    "started_at": None,
    "finished_at": None,
}


class RunError(RuntimeError):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _load_config(repo_path: Path, cli_backend: str | None) -> config.ResolvedConfig:
    """Resolve layered config (ADR-0008), surfacing a malformed/untrusted
    `factory.toml` (e.g. one that tries to define a backend command template)
    as a `RunError` instead of an unhandled exception."""
    try:
        return config.load_config(repo_path, cli_backend=cli_backend)
    except config.ConfigError as exc:
        raise RunError(str(exc)) from exc


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


def _run_implement_and_verify(
    backend: SubprocessBackend,
    bundle_dir: Path,
    run_dir: Path,
    worktree_path: Path,
    task: str,
    profile: dict,
    max_fix_attempts: int,
) -> tuple[dict, dict, list[dict], str, str, bool]:
    """Runs `implement`, commits the worktree, then the factory-owned
    Verification Gate and a bounded Fix Loop when it fails (ADR-0005/0011).
    Returns `(implement_phase, verify_phase, fix_attempts, outcome,
    outcome_reason, verify_gate_errored)`. Shared by Automation Mode (`run`)
    and the staged `implement` command so both drive identical behavior."""
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
    implement_phase = {
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

    fix_attempts: list[dict] = []

    if implement_status != "succeeded":
        outcome = "failed"
        outcome_reason = f"implement phase exited {implement_result.exit_code}"
        verify_phase = {
            "status": "not_executed",
            "reason": "implement phase failed; the Verification Gate did not run",
            "started_at": None,
            "finished_at": None,
        }
        return implement_phase, verify_phase, fix_attempts, outcome, outcome_reason, False

    verify_started_at = _now()
    try:
        verify_result = run_verification(
            worktree_path, profile["commands"], run_dir / "verify" / "attempt-0"
        )
    except safety.DeniedCommandError as exc:
        outcome = "failed"
        outcome_reason = str(exc)
        verify_phase = {
            "status": "failed",
            "reason": outcome_reason,
            "started_at": verify_started_at,
            "finished_at": _now(),
        }
        return implement_phase, verify_phase, fix_attempts, outcome, outcome_reason, True

    if verify_result.degraded:
        outcome = "implemented_degraded"
        outcome_reason = "no Verification Gate commands detected (degraded mode)"
        verify_phase = {
            "status": "skipped",
            "reason": "no verification commands detected -- degraded mode (ADR-0005)",
            "started_at": verify_started_at,
            "finished_at": _now(),
            **_verify_result_to_dict(verify_result),
        }
        return implement_phase, verify_phase, fix_attempts, outcome, outcome_reason, False

    if verify_result.passed:
        outcome = "implemented_verified"
        outcome_reason = "Verification Gate passed"
        verify_phase = {
            "status": "succeeded",
            "reason": None,
            "started_at": verify_started_at,
            "finished_at": _now(),
            **_verify_result_to_dict(verify_result),
        }
        return implement_phase, verify_phase, fix_attempts, outcome, outcome_reason, False

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
        outcome_reason = f"Verification Gate passed after {len(fix_attempts)} Fix Loop attempt(s)"
        verify_status = "succeeded"
    else:
        outcome = "implemented_unverified"
        outcome_reason = (
            "Verification Gate failed after exhausting the Fix Loop "
            f"({len(fix_attempts)} attempt(s))"
        )
        verify_status = "failed"

    verify_phase = {
        "status": verify_status,
        "reason": outcome_reason,
        "started_at": verify_started_at,
        "finished_at": _now(),
        **_verify_result_to_dict(current),
    }
    return implement_phase, verify_phase, fix_attempts, outcome, outcome_reason, False


def _run_review(
    backend: SubprocessBackend,
    bundle_dir: Path,
    run_dir: Path,
    worktree_path: Path,
    task: str,
    profile: dict,
    base_sha: str,
) -> tuple[dict, str | None, str | None]:
    """Runs the read-only Diff Review Phase (opt-in via `--review`, or via the
    staged `review` command). Returns `(review_phase, outcome_override,
    outcome_reason_override)`; the overrides are non-`None` only on a Contract
    Violation, signalling the caller to override its own outcome."""
    review_started_at = _now()
    review_context = (
        "## Diff to review\n\n```diff\n"
        + git_ops.diff_against_base(worktree_path, base_sha)
        + "\n```\n"
    )
    review_result, _, review_finished_at = _run_agent_phase(
        backend,
        bundle_dir,
        worktree_path,
        "review",
        task,
        profile,
        output_path=run_dir / "review-output.md",
        mode="read_only",
        extra_context=review_context,
    )
    if not git_ops.is_clean(worktree_path):
        (run_dir / "contract-violation.patch").write_text(
            git_ops.uncommitted_diff(worktree_path)
        )
        violation_files = git_ops.uncommitted_changed_files(worktree_path)
        (run_dir / "contract-violation-files.txt").write_text(
            "\n".join(violation_files) + ("\n" if violation_files else "")
        )
        outcome_reason = (
            "the read-only review Phase modified the worktree (see contract-violation.patch)"
        )
        review_phase = {
            "status": "contract_violation",
            "reason": outcome_reason,
            "started_at": review_started_at,
            "finished_at": review_finished_at,
            "exit_code": review_result.exit_code,
            "summary": review_result.summary,
        }
        return review_phase, "contract_violation", outcome_reason

    review_path = run_dir / "review-output.md"
    review_text = review_path.read_text() if review_path.exists() else ""
    review_phase = {
        "status": "succeeded" if review_result.exit_code == 0 else "failed",
        "reason": (
            None
            if review_result.exit_code == 0
            else f"review phase exited {review_result.exit_code}"
        ),
        "started_at": review_started_at,
        "finished_at": review_finished_at,
        "exit_code": review_result.exit_code,
        "summary": review_result.summary,
        "findings": review_text,
    }
    return review_phase, None, None


def run_manual(target: str, task: str, state_dir_value: str | None) -> int:
    """Manual Mode (the default `--backend`, ADR-0001/0006, CONTEXT.md: Manual
    Mode): prepares the Repo Profile and the `plan` Prompt Bundle and prints
    the intended Run ID / branch / worktree / State Dir paths, but invokes no
    Backend and creates no branch, worktree, or other git refs. Works against
    any directory -- a git repository is not required -- because it never
    mutates anything."""
    target_repo = Path(target).resolve()
    if not target_repo.is_dir():
        raise RunError(f"target '{target_repo}' is not a directory")

    state_dir = resolve_state_dir(state_dir_value)
    run_id = generate_run_id(task)
    run_dir = state_dir / "runs" / run_id
    if run_dir.exists():
        raise RunError(f"run id collision: '{run_id}' already exists at {run_dir}")
    run_dir.mkdir(parents=True)

    started_at = _now()
    branch = f"factory/{run_id}"
    worktree_path = run_dir / "worktree"
    bundle_dir = run_dir / "bundles"

    resolved_config = _load_config(target_repo, cli_backend="manual")
    profile = config.merge_profile_commands(profiling.build_profile(target_repo), resolved_config)
    pre_plan_level, pre_plan_reasons = risk.classify(task, profile)
    plan_extra_context = risk.render_pre_plan_context(pre_plan_level, pre_plan_reasons)
    system_path, user_path, combined_path = _write_prompt_bundle(
        bundle_dir, "plan", task, profile, target_repo, plan_extra_context
    )

    outcome = "planned"
    outcome_reason = (
        "Manual Mode: no Backend was invoked and no branch/worktree/git refs "
        "were created; the Repo Profile and the plan Prompt Bundle were "
        "prepared for you (or another agent) to drive by hand"
    )

    print(f"Run ID: {run_id}")
    print("Backend: manual (no model invoked; no git refs created)")
    print(f"Intended branch: {branch}")
    print(f"Intended worktree path: {worktree_path}")
    print(f"State Dir: {state_dir}")
    print(f"Repo Profile: {run_dir / 'profile.json'}")
    print("Plan Prompt Bundle:")
    print(f"  system:   {system_path}")
    print(f"  user:     {user_path}")
    print(f"  combined: {combined_path}")

    finished_at = _now()
    phases = {
        "plan": dict(_NOT_EXECUTED_MANUAL),
        "implement": dict(_NOT_EXECUTED_MANUAL),
        "verify": dict(_NOT_EXECUTED_MANUAL),
        "review": dict(_NOT_EXECUTED_MANUAL),
    }
    metadata: dict[str, Any] = {
        "run_id": run_id,
        "task": task,
        "target_repo": str(target_repo),
        "backend": "manual",
        "base_ref": None,
        "base_sha": None,
        "branch": None,
        "worktree_path": None,
        "state_dir": str(state_dir),
        "started_at": started_at,
        "finished_at": finished_at,
        "changed_files": [],
        "phases": phases,
        "fix_loop": {"max_attempts": 0, "attempts": []},
        "risk": {
            "level": pre_plan_level,
            "reasons": pre_plan_reasons,
            "auto_continue_allowed": pre_plan_level == "low",
            "overridden_by_user": False,
        },
        "decision_gate": {
            "paused": True,
            "reason": outcome_reason,
            "force_implement_used": False,
            "flags": {
                "pause_after_plan": False,
                "auto": False,
                "force_implement": False,
                "risk_override": None,
                "review": False,
            },
        },
        "outcome": outcome,
        "outcome_reason": outcome_reason,
    }
    (run_dir / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "report.md").write_text(render_report(metadata))
    (run_dir / "pr-body.md").write_text(render_pr_body(metadata))
    return 0


def plan_task(
    target: str,
    task: str,
    backend_name: str,
    state_dir_value: str | None,
) -> int:
    """Staged driving, first invocation (PRD story 60, CONTEXT.md: Phase):
    creates a Run under full git isolation (branch + worktree) and runs only
    the `plan` Phase, then stops -- so a human can inspect `plan.md` before a
    later, separate `ai-factory implement <run-id>` invocation continues the
    same Run."""
    if backend_name == "manual":
        raise RunError(
            "backend 'manual' cannot drive staged phases (it creates no "
            "worktree/branch); pass a real backend, e.g. --backend fake"
        )

    target_repo = Path(target).resolve()
    resolved_config = _load_config(target_repo, cli_backend=backend_name)
    if backend_name not in resolved_config.presets:
        raise RunError(
            f"unknown backend '{backend_name}'; available: {sorted(resolved_config.presets)}"
        )

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

    profile = config.merge_profile_commands(
        profiling.build_profile(worktree_path), resolved_config
    )
    bundle_dir = run_dir / "bundles"
    backend = SubprocessBackend(resolved_config.presets[backend_name], log_dir=run_dir / "logs")

    pre_plan_level, pre_plan_reasons = risk.classify(task, profile)
    plan_extra_context = risk.render_pre_plan_context(pre_plan_level, pre_plan_reasons)

    plan_phase, implement_placeholder, verify_placeholder, halt_outcome, halt_reason = (
        _run_plan_phase(
            backend, bundle_dir, run_dir, worktree_path, task, profile, plan_extra_context
        )
    )
    phases: dict[str, dict] = {"plan": plan_phase}

    if halt_outcome is not None:
        phases["implement"] = implement_placeholder
        phases["verify"] = verify_placeholder
        phases["review"] = dict(_NOT_EXECUTED_REVIEW)
        outcome = halt_outcome
        outcome_reason = halt_reason
        risk_result = {
            "level": pre_plan_level,
            "reasons": pre_plan_reasons,
            "auto_continue_allowed": pre_plan_level == "low",
            "overridden_by_user": False,
        }
        gate_info: dict[str, Any] = {
            "paused": None,
            "reason": None,
            "force_implement_used": False,
        }
    else:
        plan_text = (run_dir / "plan.md").read_text() if (run_dir / "plan.md").exists() else ""
        predicted_files = risk.extract_predicted_files(plan_text)
        final_level, final_reasons = risk.classify(task, profile, predicted_files)
        risk_result = {
            "level": final_level,
            "reasons": final_reasons,
            "auto_continue_allowed": final_level == "low",
            "overridden_by_user": False,
        }
        outcome = "planned"
        outcome_reason = (
            f"staged plan Phase completed (run '{run_id}'); inspect plan.md, then "
            f"run `ai-factory implement {run_id}` to continue"
        )
        gate_info = {
            "paused": True,
            "reason": outcome_reason,
            "force_implement_used": False,
        }
        phases["implement"] = dict(_NOT_EXECUTED_STAGED_IMPLEMENT)
        phases["verify"] = dict(_NOT_EXECUTED_STAGED_IMPLEMENT)
        phases["review"] = dict(_NOT_EXECUTED_STAGED_REVIEW)

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
        "fix_loop": {"max_attempts": DEFAULT_MAX_FIX_ATTEMPTS, "attempts": []},
        "risk": risk_result,
        "decision_gate": {
            **gate_info,
            "flags": {
                "pause_after_plan": False,
                "auto": False,
                "force_implement": False,
                "risk_override": None,
                "review": False,
                "staged": True,
            },
        },
        "outcome": outcome,
        "outcome_reason": outcome_reason,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "report.md").write_text(render_report(metadata))
    (run_dir / "pr-body.md").write_text(render_pr_body(metadata))

    print(f"Run ID: {run_id}")
    print(f"Outcome: {outcome} -- {outcome_reason}")
    return 0 if outcome == "planned" else 1


def _load_staged_run(state_dir: Path, run_id: str) -> tuple[Path, dict]:
    run_dir = runs.run_dir(state_dir, run_id)
    metadata = runs.load_run_metadata(state_dir, run_id)
    if metadata.get("backend") == "manual" or metadata.get("worktree_path") is None:
        raise RunError(
            f"run '{run_id}' was created with Manual Mode, which has no worktree "
            "to continue; staged driving requires a run created via `ai-factory plan`"
        )
    return run_dir, metadata


def _continue_implement(
    run_id: str,
    run_dir: Path,
    metadata: dict,
    max_fix_attempts: int,
    review: bool,
    decision_gate_reason: str,
) -> int:
    """Shared tail of `implement` and a resumed run (CONTEXT.md: Resume): runs
    `implement`, the Verification Gate, the Fix Loop, and (with `--review`)
    the Diff Review Phase against an already-validated, persisted `metadata`,
    then persists the result. Callers are responsible for validating Phase
    statuses and worktree cleanliness before calling this."""
    worktree_path = Path(metadata["worktree_path"])
    task = metadata["task"]
    base_sha = metadata["base_sha"]
    bundle_dir = run_dir / "bundles"
    resolved_config = _load_config(worktree_path, cli_backend=metadata["backend"])
    backend = SubprocessBackend(
        resolved_config.presets[metadata["backend"]], log_dir=run_dir / "logs"
    )
    profile = config.merge_profile_commands(
        profiling.build_profile(worktree_path), resolved_config
    )

    implement_phase, verify_phase, fix_attempts, outcome, outcome_reason, verify_gate_errored = (
        _run_implement_and_verify(
            backend, bundle_dir, run_dir, worktree_path, task, profile, max_fix_attempts
        )
    )
    metadata["phases"]["implement"] = implement_phase
    metadata["phases"]["verify"] = verify_phase
    metadata["fix_loop"] = {"max_attempts": max_fix_attempts, "attempts": fix_attempts}

    if not verify_gate_errored:
        if review:
            review_phase, outcome_override, outcome_reason_override = _run_review(
                backend, bundle_dir, run_dir, worktree_path, task, profile, base_sha
            )
            metadata["phases"]["review"] = review_phase
            if outcome_override is not None:
                outcome = outcome_override
                outcome_reason = outcome_reason_override or outcome_reason
        else:
            metadata["phases"]["review"] = dict(_NOT_EXECUTED_STAGED_REVIEW)

    metadata["decision_gate"]["paused"] = False
    metadata["decision_gate"]["reason"] = decision_gate_reason
    metadata["decision_gate"]["flags"]["review"] = review

    diff_text = git_ops.diff_against_base(worktree_path, base_sha)
    files_changed = git_ops.changed_files(worktree_path, base_sha)
    (run_dir / "diff.patch").write_text(diff_text)
    (run_dir / "changed-files.txt").write_text(
        "\n".join(files_changed) + ("\n" if files_changed else "")
    )
    metadata["changed_files"] = files_changed
    metadata["finished_at"] = _now()
    metadata["outcome"] = outcome
    metadata["outcome_reason"] = outcome_reason

    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "report.md").write_text(render_report(metadata))
    (run_dir / "pr-body.md").write_text(render_pr_body(metadata))

    print(f"Run ID: {run_id}")
    print(f"Outcome: {outcome} -- {outcome_reason}")
    return 0 if outcome in ("implemented_verified", "implemented_degraded") else 1


def implement_task(
    run_id: str,
    state_dir_value: str | None,
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    review: bool = False,
) -> int:
    """Staged driving, second invocation: continues a Run created by
    `ai-factory plan` -- reads its persisted state, then runs `implement`, the
    Verification Gate, the Fix Loop, and (with `--review`) the Diff Review
    Phase, exactly as Automation Mode would."""
    state_dir = resolve_state_dir(state_dir_value)
    run_dir, metadata = _load_staged_run(state_dir, run_id)

    plan_status = metadata["phases"].get("plan", {}).get("status")
    if plan_status != "succeeded":
        raise RunError(
            f"cannot implement run '{run_id}': plan phase status is '{plan_status}' "
            "(expected 'succeeded')"
        )
    implement_status = metadata["phases"].get("implement", {}).get("status")
    if implement_status != "not_executed":
        raise RunError(
            f"cannot implement run '{run_id}': implement phase already has status "
            f"'{implement_status}'"
        )

    return _continue_implement(
        run_id,
        run_dir,
        metadata,
        max_fix_attempts,
        review,
        "staged mode: continued explicitly via `ai-factory implement`",
    )


def _continue_review(run_id: str, run_dir: Path, metadata: dict) -> int:
    """Shared tail of `review` and a resumed run (CONTEXT.md: Resume): runs
    the read-only Diff Review Phase against an already-validated, persisted
    `metadata`, then persists the result. Callers are responsible for
    validating Phase statuses and worktree cleanliness before calling this."""
    worktree_path = Path(metadata["worktree_path"])
    task = metadata["task"]
    base_sha = metadata["base_sha"]
    bundle_dir = run_dir / "bundles"
    resolved_config = _load_config(worktree_path, cli_backend=metadata["backend"])
    backend = SubprocessBackend(
        resolved_config.presets[metadata["backend"]], log_dir=run_dir / "logs"
    )
    profile = config.merge_profile_commands(
        profiling.build_profile(worktree_path), resolved_config
    )

    review_phase, outcome_override, outcome_reason_override = _run_review(
        backend, bundle_dir, run_dir, worktree_path, task, profile, base_sha
    )
    metadata["phases"]["review"] = review_phase
    metadata["decision_gate"]["flags"]["review"] = True
    if outcome_override is not None:
        metadata["outcome"] = outcome_override
        metadata["outcome_reason"] = outcome_reason_override
    metadata["finished_at"] = _now()

    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "report.md").write_text(render_report(metadata))
    (run_dir / "pr-body.md").write_text(render_pr_body(metadata))

    print(f"Run ID: {run_id}")
    print(f"Review status: {review_phase['status']}")
    return 0 if review_phase["status"] in ("succeeded",) else 1


def review_task(run_id: str, state_dir_value: str | None) -> int:
    """Staged driving, optional final invocation: runs the read-only Diff
    Review Phase over a Run whose `implement` Phase already completed. Never
    an approval gate and never changes a passing/failing Verification Gate
    outcome, except for a Contract Violation on the review Phase itself."""
    state_dir = resolve_state_dir(state_dir_value)
    run_dir, metadata = _load_staged_run(state_dir, run_id)

    implement_status = metadata["phases"].get("implement", {}).get("status")
    if implement_status != "succeeded":
        raise RunError(
            f"cannot review run '{run_id}': implement phase status is "
            f"'{implement_status}' (expected 'succeeded')"
        )
    review_status = metadata["phases"].get("review", {}).get("status")
    if review_status not in ("not_executed", "skipped"):
        raise RunError(
            f"cannot review run '{run_id}': review phase already has status '{review_status}'"
        )

    return _continue_review(run_id, run_dir, metadata)


def run_task(
    target: str,
    task: str,
    backend_name: str | None,
    state_dir_value: str | None,
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    pause_after_plan: bool = False,
    auto: bool = False,
    force_implement: bool = False,
    risk_override: str | None = None,
    review: bool = False,
) -> int:
    if risk_override is not None and risk_override not in ("low", "medium", "high"):
        raise RunError(f"invalid --risk override '{risk_override}'; must be low, medium, or high")

    target_repo = Path(target).resolve()
    resolved_config = _load_config(target_repo, cli_backend=backend_name)
    backend_name = resolved_config.backend_name
    if risk_override is None and resolved_config.risk_override is not None:
        risk_override = resolved_config.risk_override

    if backend_name == "manual":
        return run_manual(target, task, state_dir_value)
    if backend_name not in resolved_config.presets:
        raise RunError(
            f"unknown backend '{backend_name}'; available: {sorted(resolved_config.presets)}"
        )

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
    # below so it is never re-derived mid-Run. Repo/user config commands are
    # layered on top (ADR-0008) with repo config taking precedence.
    profile = config.merge_profile_commands(
        profiling.build_profile(worktree_path), resolved_config
    )

    bundle_dir = run_dir / "bundles"
    backend = SubprocessBackend(resolved_config.presets[backend_name], log_dir=run_dir / "logs")

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
        gate_info: dict[str, Any] = {
            "paused": None,
            "reason": None,
            "force_implement_used": False,
        }
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
        (
            phases["implement"],
            phases["verify"],
            fix_attempts,
            outcome,
            outcome_reason,
            verify_gate_errored,
        ) = _run_implement_and_verify(
            backend, bundle_dir, run_dir, worktree_path, task, profile, max_fix_attempts
        )

        # Diff Review (opt-in via --review, ADR-0003/0014): a read-only
        # Phase over the Run's diff, feeding findings into the report --
        # it is not an approval gate and never overrides the Verification
        # Gate's outcome, except for a Contract Violation on itself.
        if not verify_gate_errored:
            if review:
                phases["review"], outcome_override, outcome_reason_override = _run_review(
                    backend, bundle_dir, run_dir, worktree_path, task, profile, base_sha
                )
                if outcome_override is not None:
                    outcome = outcome_override
                    outcome_reason = outcome_reason_override or outcome_reason
            else:
                phases["review"] = dict(_SKIPPED_REVIEW_NOT_REQUESTED)
    else:
        # The Decision Gate paused the Run after `plan.md` (ADR-0014):
        # `implement`/`verify` never run.
        phases["implement"] = dict(_NOT_EXECUTED_GATE_PAUSED)
        phases["verify"] = dict(_NOT_EXECUTED_GATE_PAUSED)
        outcome = "planned"
        outcome_reason = gate_info["reason"]

    if "review" not in phases:
        # The Run never reached a completed implementation (halted at plan,
        # gate-paused, or implement itself failed): Diff Review never runs,
        # whether or not --review was passed.
        phases["review"] = (
            dict(_SKIPPED_REVIEW_NOT_REQUESTED) if not review else dict(_NOT_EXECUTED_REVIEW)
        )

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
                "review": review,
            },
        },
        "outcome": outcome,
        "outcome_reason": outcome_reason,
    }

    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (run_dir / "report.md").write_text(render_report(metadata))
    (run_dir / "pr-body.md").write_text(render_pr_body(metadata))

    return 0 if outcome in ("implemented_verified", "implemented_degraded", "planned") else 1


def resume_task(
    run_id: str,
    state_dir_value: str | None,
    discard_phase_changes: bool = False,
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    review: bool = False,
) -> int:
    """`ai-factory resume <run-id>` (PRD story 54; CONTEXT.md: Resume;
    ADR-0002/0011/0012): re-enters an interrupted Run at its last incomplete
    Phase from persisted `metadata.json` -- phase-granular, with no
    mid-phase checkpointing (a Phase that was interrupted mid-invocation is
    re-driven from that Phase's start, not from wherever it happened to be).

    Before re-running a read-write Phase (`implement`, bundled with `verify`
    and the Fix Loop) that left partial worktree changes, resume refuses and
    directs the user to inspect them or pass `--discard-phase-changes`, which
    resets only the factory-owned worktree to the Phase's last committed
    (base) state -- the target checkout is never touched (ADR-0002).
    Re-running a read-only Phase (`review`) is idempotent: any leftover
    worktree changes left by an interrupted attempt can only be
    Contract-Violation-worthy garbage, so they are discarded unconditionally,
    no flag required."""
    state_dir = resolve_state_dir(state_dir_value)
    try:
        run_dir, metadata = _load_staged_run(state_dir, run_id)
    except runs.RunNotFoundError as exc:
        raise RunError(
            f"run '{run_id}' has no persisted state to resume from (its "
            "metadata.json is missing -- it was interrupted before its plan "
            "Phase ever completed); nothing to resume, start over with "
            "`ai-factory plan`"
        ) from exc

    outcome = metadata.get("outcome")
    if outcome in ("contract_violation", "failed"):
        raise RunError(
            f"run '{run_id}' halted with outcome '{outcome}'; inspect its "
            "saved evidence under the run directory -- nothing to automatically resume"
        )

    worktree_path = Path(metadata["worktree_path"])
    if not worktree_path.exists():
        raise RunError(
            f"run '{run_id}''s worktree at {worktree_path} no longer exists "
            "(it may already have been `ai-factory clean`ed); nothing to resume"
        )

    plan_status = metadata["phases"].get("plan", {}).get("status")
    if plan_status != "succeeded":
        raise RunError(
            f"run '{run_id}' never completed its plan Phase (status "
            f"'{plan_status}'); nothing to resume"
        )

    implement_status = metadata["phases"].get("implement", {}).get("status")
    if implement_status != "succeeded":
        if not git_ops.is_clean(worktree_path):
            if not discard_phase_changes:
                raise RunError(
                    f"run '{run_id}' has uncommitted changes in its worktree "
                    f"({worktree_path}) left by an interrupted implement/fix "
                    "Phase; inspect them (e.g. "
                    f"`git -C {worktree_path} status` / `diff`), or re-run with "
                    "--discard-phase-changes to reset the factory-owned worktree "
                    "to its last committed state and retry -- the target "
                    "checkout is never touched"
                )
            git_ops.reset_worktree_to_head(worktree_path)
        return _continue_implement(
            run_id,
            run_dir,
            metadata,
            max_fix_attempts,
            review,
            "resumed via `ai-factory resume` after an interrupted implement/fix Phase",
        )

    review_status = metadata["phases"].get("review", {}).get("status")
    if review_status == "not_executed" and review:
        if not git_ops.is_clean(worktree_path):
            git_ops.reset_worktree_to_head(worktree_path)
        return _continue_review(run_id, run_dir, metadata)

    raise RunError(
        f"run '{run_id}' has nothing left to resume (outcome '{outcome}'); "
        "pass --review to run the optional Diff Review Phase, or use "
        f"`ai-factory review {run_id}` directly"
    )
