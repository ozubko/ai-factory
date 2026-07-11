"""Orchestrates one Run's lifecycle through `profile -> risk_classify -> plan
-> [decision gate] -> implement -> verify -> fix-loop -> report` (ADR-0014).

This module builds the Repo Profile, computes a pre-plan Risk Level (informing
the Planning Agent), runs the read-only `plan` Phase (ADR-0004/0010) and
enforces it via git afterwards, recomputes the authoritative post-plan Risk
Level (now also informed by plan-predicted changed files), applies the
Decision Gate, and -- only when the gate permits -- runs the `implement`
   Phase, the factory-owned Verification Gate, a bounded Fix Loop when the gate
   fails, and the optional read-only Diff Review (ADR-0005, ADR-0007, ADR-0011,
   ADR-0014).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, decision_gate, git_ops, profiling, risk, runs
from .backend.subprocess_backend import SubprocessBackend
from .phase_runner import PhaseRunner, write_prompt_bundle
from .run_artifacts import RunArtifacts
from .run_id import generate_run_id
from .state_dir import resolve_state_dir

# Default bound on the Fix Loop (PRD: "default 1-2 attempts"). Not yet
# CLI/config-overridable.
DEFAULT_MAX_FIX_ATTEMPTS = 2

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


@dataclass(frozen=True)
class _AutomationRun:
    """The stable resources shared by every automated lifecycle path."""

    target_repo: Path
    state_dir: Path
    run_id: str
    run_dir: Path
    started_at: str
    base_ref: str
    base_sha: str
    branch: str
    worktree_path: Path
    profile: dict
    phase_runner: PhaseRunner
    artifacts: RunArtifacts


def _validate_automation_target(target_repo: Path) -> None:
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


def _prepare_automation_run(
    target_repo: Path,
    task: str,
    backend_name: str,
    state_dir_value: str | None,
    resolved_config: config.ResolvedConfig,
) -> _AutomationRun:
    """Validate and create the isolated resources shared by plan/run."""
    if backend_name not in resolved_config.presets:
        raise RunError(
            f"unknown backend '{backend_name}'; available: "
            f"{sorted(resolved_config.presets)}"
        )

    _validate_automation_target(target_repo)
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
    backend = SubprocessBackend(
        resolved_config.presets[backend_name], log_dir=run_dir / "logs"
    )
    return _AutomationRun(
        target_repo=target_repo,
        state_dir=state_dir,
        run_id=run_id,
        run_dir=run_dir,
        started_at=started_at,
        base_ref=base_ref,
        base_sha=base_sha,
        branch=branch,
        worktree_path=worktree_path,
        profile=profile,
        phase_runner=PhaseRunner(backend, run_dir, worktree_path, task, profile),
        artifacts=RunArtifacts(run_dir),
    )


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
    artifacts = RunArtifacts(run_dir)

    started_at = _now()
    branch = f"factory/{run_id}"
    worktree_path = run_dir / "worktree"
    bundle_dir = run_dir / "bundles"

    resolved_config = _load_config(target_repo, cli_backend="manual")
    profile = config.merge_profile_commands(
        profiling.build_profile(target_repo), resolved_config
    )
    pre_plan_level, pre_plan_reasons = risk.classify(task, profile)
    plan_extra_context = risk.render_pre_plan_context(pre_plan_level, pre_plan_reasons)
    system_path, user_path, combined_path = write_prompt_bundle(
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
    artifacts.write_profile(profile)
    artifacts.publish(metadata)
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
    automation = _prepare_automation_run(
        target_repo, task, backend_name, state_dir_value, resolved_config
    )
    profile = automation.profile

    pre_plan_level, pre_plan_reasons = risk.classify(task, profile)
    plan_extra_context = risk.render_pre_plan_context(pre_plan_level, pre_plan_reasons)

    plan_execution = automation.phase_runner.run_plan(plan_extra_context)
    phases: dict[str, dict] = {"plan": plan_execution.phase}

    if plan_execution.halted:
        phases["implement"] = dict(_NOT_EXECUTED_HALTED)
        phases["verify"] = dict(_NOT_EXECUTED_HALTED)
        phases["review"] = dict(_NOT_EXECUTED_REVIEW)
        outcome = plan_execution.outcome
        outcome_reason = plan_execution.outcome_reason
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
        plan_path = automation.run_dir / "plan.md"
        plan_text = plan_path.read_text() if plan_path.exists() else ""
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
            f"staged plan Phase completed (run '{automation.run_id}'); inspect "
            f"plan.md, then run `ai-factory implement {automation.run_id}` to continue"
        )
        gate_info = {
            "paused": True,
            "reason": outcome_reason,
            "force_implement_used": False,
        }
        phases["implement"] = dict(_NOT_EXECUTED_STAGED_IMPLEMENT)
        phases["verify"] = dict(_NOT_EXECUTED_STAGED_IMPLEMENT)
        phases["review"] = dict(_NOT_EXECUTED_STAGED_REVIEW)

    files_changed = automation.artifacts.capture_changes(
        automation.worktree_path, automation.base_sha
    )

    finished_at = _now()
    metadata = {
        "run_id": automation.run_id,
        "task": task,
        "target_repo": str(automation.target_repo),
        "backend": backend_name,
        "base_ref": automation.base_ref,
        "base_sha": automation.base_sha,
        "branch": automation.branch,
        "worktree_path": str(automation.worktree_path),
        "state_dir": str(automation.state_dir),
        "started_at": automation.started_at,
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
    automation.artifacts.publish(metadata)

    print(f"Run ID: {automation.run_id}")
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
    artifacts = RunArtifacts(run_dir)
    task = metadata["task"]
    base_sha = metadata["base_sha"]
    resolved_config = _load_config(worktree_path, cli_backend=metadata["backend"])
    backend = SubprocessBackend(
        resolved_config.presets[metadata["backend"]], log_dir=run_dir / "logs"
    )
    profile = config.merge_profile_commands(
        profiling.build_profile(worktree_path), resolved_config
    )
    phase_runner = PhaseRunner(backend, run_dir, worktree_path, task, profile)

    implementation = phase_runner.run_implementation(max_fix_attempts)
    outcome = implementation.outcome
    outcome_reason = implementation.outcome_reason
    metadata["phases"]["implement"] = implementation.implement_phase
    metadata["phases"]["verify"] = implementation.verify_phase
    metadata["fix_loop"] = {
        "max_attempts": max_fix_attempts,
        "attempts": implementation.fix_attempts,
    }

    if not implementation.verification_errored:
        if review:
            review_execution = phase_runner.run_review(base_sha)
            metadata["phases"]["review"] = review_execution.phase
            if review_execution.outcome_override is not None:
                outcome = review_execution.outcome_override
                outcome_reason = (
                    review_execution.outcome_reason_override or outcome_reason
                )
        else:
            metadata["phases"]["review"] = dict(_NOT_EXECUTED_STAGED_REVIEW)

    metadata["decision_gate"]["paused"] = False
    metadata["decision_gate"]["reason"] = decision_gate_reason
    metadata["decision_gate"]["flags"]["review"] = review

    files_changed = artifacts.capture_changes(worktree_path, base_sha)
    metadata["changed_files"] = files_changed
    metadata["finished_at"] = _now()
    metadata["outcome"] = outcome
    metadata["outcome_reason"] = outcome_reason

    artifacts.publish(metadata)

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
    artifacts = RunArtifacts(run_dir)
    task = metadata["task"]
    base_sha = metadata["base_sha"]
    resolved_config = _load_config(worktree_path, cli_backend=metadata["backend"])
    backend = SubprocessBackend(
        resolved_config.presets[metadata["backend"]], log_dir=run_dir / "logs"
    )
    profile = config.merge_profile_commands(
        profiling.build_profile(worktree_path), resolved_config
    )
    phase_runner = PhaseRunner(backend, run_dir, worktree_path, task, profile)

    review_execution = phase_runner.run_review(base_sha)
    metadata["phases"]["review"] = review_execution.phase
    metadata["decision_gate"]["flags"]["review"] = True
    if review_execution.outcome_override is not None:
        metadata["outcome"] = review_execution.outcome_override
        metadata["outcome_reason"] = review_execution.outcome_reason_override
    metadata["finished_at"] = _now()

    artifacts.publish(metadata)

    print(f"Run ID: {run_id}")
    print(f"Review status: {review_execution.phase['status']}")
    return 0 if review_execution.phase["status"] in ("succeeded",) else 1


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
        raise RunError(
            f"invalid --risk override '{risk_override}'; must be low, medium, or high"
        )

    target_repo = Path(target).resolve()
    resolved_config = _load_config(target_repo, cli_backend=backend_name)
    backend_name = resolved_config.backend_name
    if risk_override is None and resolved_config.risk_override is not None:
        risk_override = resolved_config.risk_override

    if backend_name == "manual":
        return run_manual(target, task, state_dir_value)
    automation = _prepare_automation_run(
        target_repo, task, backend_name, state_dir_value, resolved_config
    )
    profile = automation.profile

    phases: dict[str, dict] = {}
    fix_attempts: list[dict] = []

    # `risk_classify` (ADR-0014): a pre-plan Risk Level, computed from task text
    # and the Repo Profile alone (no plan-predicted files exist yet), fed to the
    # Planning Agent as informational context. No model call.
    pre_plan_level, pre_plan_reasons = risk.classify(task, profile)
    plan_extra_context = risk.render_pre_plan_context(pre_plan_level, pre_plan_reasons)

    plan_execution = automation.phase_runner.run_plan(plan_extra_context)
    phases["plan"] = plan_execution.phase

    if plan_execution.halted:
        phases["implement"] = dict(_NOT_EXECUTED_HALTED)
        phases["verify"] = dict(_NOT_EXECUTED_HALTED)
        outcome = plan_execution.outcome
        outcome_reason = plan_execution.outcome_reason
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
        plan_path = automation.run_dir / "plan.md"
        plan_text = plan_path.read_text() if plan_path.exists() else ""
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

    if plan_execution.halted:
        pass
    elif not gate_info["paused"]:
        implementation = automation.phase_runner.run_implementation(max_fix_attempts)
        phases["implement"] = implementation.implement_phase
        phases["verify"] = implementation.verify_phase
        fix_attempts = implementation.fix_attempts
        outcome = implementation.outcome
        outcome_reason = implementation.outcome_reason

        # Diff Review (opt-in via --review, ADR-0003/0014): a read-only
        # Phase over the Run's diff, feeding findings into the report --
        # it is not an approval gate and never overrides the Verification
        # Gate's outcome, except for a Contract Violation on itself.
        if not implementation.verification_errored:
            if review:
                review_execution = automation.phase_runner.run_review(
                    automation.base_sha
                )
                phases["review"] = review_execution.phase
                if review_execution.outcome_override is not None:
                    outcome = review_execution.outcome_override
                    outcome_reason = (
                        review_execution.outcome_reason_override or outcome_reason
                    )
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
            dict(_SKIPPED_REVIEW_NOT_REQUESTED)
            if not review
            else dict(_NOT_EXECUTED_REVIEW)
        )

    files_changed = automation.artifacts.capture_changes(
        automation.worktree_path, automation.base_sha
    )

    finished_at = _now()
    metadata = {
        "run_id": automation.run_id,
        "task": task,
        "target_repo": str(automation.target_repo),
        "backend": backend_name,
        "base_ref": automation.base_ref,
        "base_sha": automation.base_sha,
        "branch": automation.branch,
        "worktree_path": str(automation.worktree_path),
        "state_dir": str(automation.state_dir),
        "started_at": automation.started_at,
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

    automation.artifacts.publish(metadata)

    return (
        0
        if outcome in ("implemented_verified", "implemented_degraded", "planned")
        else 1
    )


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
