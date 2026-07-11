"""Execute agent Phases behind one small orchestration interface.

The public methods mirror the three lifecycle operations the Factory can drive:
planning, implementation plus verification, and optional Diff Review.  Prompt
bundling, Backend requests, Contract Violation evidence, and Fix Loop details
stay local to this module.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from . import git_ops, prompt_builder, prompts, safety
from .backend.base import AgentBackend, AgentRequest, AgentResult, PhaseMode
from .run_artifacts import RunArtifacts
from .verify import VerificationResult, run_verification

MAX_FAILURE_EXCERPT_CHARS = 2000


@dataclass(frozen=True)
class PlanExecution:
    phase: dict
    outcome: str | None = None
    outcome_reason: str | None = None

    @property
    def halted(self) -> bool:
        return self.outcome is not None


@dataclass(frozen=True)
class ImplementationExecution:
    implement_phase: dict
    verify_phase: dict
    fix_attempts: list[dict]
    outcome: str
    outcome_reason: str
    verification_errored: bool = False


@dataclass(frozen=True)
class ReviewExecution:
    phase: dict
    outcome_override: str | None = None
    outcome_reason_override: str | None = None


@dataclass(frozen=True)
class _FixLoopExecution:
    verification: VerificationResult
    attempts: list[dict]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_prompt_bundle(
    bundle_dir: Path,
    phase: str,
    task: str,
    profile: dict,
    worktree_path: Path,
    extra_context: str | None = None,
) -> tuple[Path, Path, Path]:
    """Write a Phase's system, user, and combined Prompt Bundle files."""
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
    failing = next(command for command in result.results if not command.passed)
    log_text = failing.log_path.read_text()[-MAX_FAILURE_EXCERPT_CHARS:]
    return (
        f"Command `{failing.command}` (key: {failing.key}) failed with exit "
        f"code {failing.exit_code}:\n\n{log_text}"
    )


class PhaseRunner:
    """Facade over the mechanics shared by all agent-driven Phases."""

    def __init__(
        self,
        backend: AgentBackend,
        run_dir: Path,
        worktree_path: Path,
        task: str,
        profile: dict,
    ) -> None:
        self._backend = backend
        self._run_dir = run_dir
        self._bundle_dir = run_dir / "bundles"
        self._worktree_path = worktree_path
        self._task = task
        self._profile = profile
        self._artifacts = RunArtifacts(run_dir)

    def run_plan(self, extra_context: str | None = None) -> PlanExecution:
        """Run the read-only plan Phase and enforce its side-effect contract."""
        plan_path = self._run_dir / "plan.md"
        result, started_at, finished_at = self._run_phase(
            "plan",
            output_path=plan_path,
            mode="read_only",
            extra_context=extra_context,
        )

        if not git_ops.is_clean(self._worktree_path):
            self._artifacts.capture_contract_violation(self._worktree_path)
            phase = {
                "status": "contract_violation",
                "reason": (
                    "the read-only plan Phase modified the worktree; evidence "
                    "saved to contract-violation.patch"
                ),
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": result.exit_code,
                "summary": result.summary,
            }
            reason = (
                "the read-only plan Phase modified the worktree "
                "(see contract-violation.patch)"
            )
            return PlanExecution(phase, "contract_violation", reason)

        if result.exit_code != 0:
            reason = f"plan phase exited {result.exit_code}"
            phase = {
                "status": "failed",
                "reason": reason,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": result.exit_code,
                "summary": result.summary,
            }
            return PlanExecution(phase, "failed", reason)

        plan_text = plan_path.read_text() if plan_path.exists() else ""
        missing_headings = prompts.missing_plan_headings(plan_text)
        phase = {
            "status": "succeeded",
            "reason": None,
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": result.exit_code,
            "summary": result.summary,
            "plan_quality": "degraded" if missing_headings else "ok",
            "missing_headings": missing_headings,
        }
        return PlanExecution(phase)

    def run_implementation(self, max_fix_attempts: int) -> ImplementationExecution:
        """Run implement, the Verification Gate, and the bounded Fix Loop."""
        implement_phase = self._run_implementation_phase()
        if implement_phase["status"] != "succeeded":
            reason = implement_phase["reason"]
            verify_phase = {
                "status": "not_executed",
                "reason": "implement phase failed; the Verification Gate did not run",
                "started_at": None,
                "finished_at": None,
            }
            return ImplementationExecution(
                implement_phase, verify_phase, [], "failed", reason
            )

        verify_started_at = _now()
        try:
            verify_result = self._verify(attempt=0)
        except safety.DeniedCommandError as exc:
            reason = str(exc)
            verify_phase = {
                "status": "failed",
                "reason": reason,
                "started_at": verify_started_at,
                "finished_at": _now(),
            }
            return ImplementationExecution(
                implement_phase,
                verify_phase,
                [],
                "failed",
                reason,
                verification_errored=True,
            )

        if verify_result.degraded:
            reason = "no Verification Gate commands detected (degraded mode)"
            verify_phase = {
                "status": "skipped",
                "reason": "no verification commands detected -- degraded mode (ADR-0005)",
                "started_at": verify_started_at,
                "finished_at": _now(),
                **_verify_result_to_dict(verify_result),
            }
            return ImplementationExecution(
                implement_phase,
                verify_phase,
                [],
                "implemented_degraded",
                reason,
            )

        if verify_result.passed:
            reason = "Verification Gate passed"
            verify_phase = {
                "status": "succeeded",
                "reason": None,
                "started_at": verify_started_at,
                "finished_at": _now(),
                **_verify_result_to_dict(verify_result),
            }
            return ImplementationExecution(
                implement_phase,
                verify_phase,
                [],
                "implemented_verified",
                reason,
            )

        fix_loop = self._run_fix_loop(verify_result, max_fix_attempts)
        current = fix_loop.verification
        fix_attempts = fix_loop.attempts

        if current.passed:
            outcome = "implemented_verified"
            reason = (
                "Verification Gate passed after "
                f"{len(fix_attempts)} Fix Loop attempt(s)"
            )
            verify_status = "succeeded"
        else:
            outcome = "implemented_unverified"
            reason = (
                "Verification Gate failed after exhausting the Fix Loop "
                f"({len(fix_attempts)} attempt(s))"
            )
            verify_status = "failed"

        verify_phase = {
            "status": verify_status,
            "reason": reason,
            "started_at": verify_started_at,
            "finished_at": _now(),
            **_verify_result_to_dict(current),
        }
        return ImplementationExecution(
            implement_phase,
            verify_phase,
            fix_attempts,
            outcome,
            reason,
        )

    def run_review(self, base_sha: str) -> ReviewExecution:
        """Run the read-only Diff Review Phase and enforce its contract."""
        review_started_at = _now()
        review_context = (
            "## Diff to review\n\n```diff\n"
            + git_ops.diff_against_base(self._worktree_path, base_sha)
            + "\n```\n"
        )
        result, _, finished_at = self._run_phase(
            "review",
            output_path=self._run_dir / "review-output.md",
            mode="read_only",
            extra_context=review_context,
        )
        if not git_ops.is_clean(self._worktree_path):
            self._artifacts.capture_contract_violation(self._worktree_path)
            reason = (
                "the read-only review Phase modified the worktree "
                "(see contract-violation.patch)"
            )
            phase = {
                "status": "contract_violation",
                "reason": reason,
                "started_at": review_started_at,
                "finished_at": finished_at,
                "exit_code": result.exit_code,
                "summary": result.summary,
            }
            return ReviewExecution(phase, "contract_violation", reason)

        review_path = self._run_dir / "review-output.md"
        review_text = review_path.read_text() if review_path.exists() else ""
        phase = {
            "status": "succeeded" if result.exit_code == 0 else "failed",
            "reason": (
                None
                if result.exit_code == 0
                else f"review phase exited {result.exit_code}"
            ),
            "started_at": review_started_at,
            "finished_at": finished_at,
            "exit_code": result.exit_code,
            "summary": result.summary,
            "findings": review_text,
        }
        return ReviewExecution(phase)

    def _run_implementation_phase(self) -> dict:
        result, started_at, finished_at = self._run_phase(
            "implement",
            output_path=self._run_dir / "implement-output.md",
            mode="read_write",
        )
        git_ops.commit_worktree_changes(
            self._worktree_path, message=f"implement: {self._task}"
        )
        status = "succeeded" if result.exit_code == 0 else "failed"
        return {
            "status": status,
            "reason": None
            if status == "succeeded"
            else f"implement phase exited {result.exit_code}",
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": result.exit_code,
            "summary": result.summary,
        }

    def _run_fix_loop(
        self, initial: VerificationResult, max_attempts: int
    ) -> _FixLoopExecution:
        current = initial
        attempts: list[dict] = []
        for attempt in range(1, max_attempts + 1):
            result, started_at, finished_at = self._run_phase(
                "fix",
                output_path=self._run_dir / "fix-output.md",
                mode="read_write",
                extra_context=_failure_excerpt(current),
            )
            git_ops.commit_worktree_changes(
                self._worktree_path,
                message=f"fix attempt {attempt}: {self._task}",
            )
            current = self._verify(attempt=attempt)
            attempts.append(
                {
                    "attempt": attempt,
                    "phase_status": "succeeded" if result.exit_code == 0 else "failed",
                    "exit_code": result.exit_code,
                    "summary": result.summary,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "verify": _verify_result_to_dict(current),
                }
            )
            if current.passed:
                break
        return _FixLoopExecution(current, attempts)

    def _run_phase(
        self,
        phase: str,
        *,
        output_path: Path,
        mode: PhaseMode,
        extra_context: str | None = None,
    ) -> tuple[AgentResult, str, str]:
        system_path, user_path, combined_path = write_prompt_bundle(
            self._bundle_dir,
            phase,
            self._task,
            self._profile,
            self._worktree_path,
            extra_context,
        )
        request = AgentRequest(
            phase=phase,
            workdir=self._worktree_path,
            system_prompt_path=system_path,
            user_prompt_path=user_path,
            combined_prompt_path=combined_path,
            output_path=output_path,
            mode=mode,
        )
        started_at = _now()
        result = self._backend.run(request)
        return result, started_at, _now()

    def _verify(self, attempt: int) -> VerificationResult:
        return run_verification(
            self._worktree_path,
            self._profile["commands"],
            self._run_dir / "verify" / f"attempt-{attempt}",
        )
