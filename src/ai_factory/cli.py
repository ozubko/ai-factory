"""ai-factory CLI (argparse only — ADR-0009: zero runtime dependencies)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cleanup, runs, views
from .presets.registry import PRESETS
from .profiling import build_profile
from .runner import RunError, implement_task, plan_task, resume_task, review_task, run_task
from .state_dir import resolve_state_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-factory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a task against a Target Repo.")
    run_parser.add_argument("target", help="Path to the Target Repo.")
    run_parser.add_argument("task", help="The task description.")
    run_parser.add_argument(
        "--backend",
        default=None,
        help=(
            "AgentBackend preset to use for this Run. Overrides repo/user config "
            "(precedence: --backend > repo factory.toml > user config > 'manual'); "
            "'manual' makes no model call and creates no git refs."
        ),
    )
    run_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )
    run_parser.add_argument(
        "--pause-after-plan",
        action="store_true",
        help="Always pause after plan.md, regardless of the computed Risk Level.",
    )
    run_parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Explicitly allow classifier-gated continuation (proceeds only when "
            "the Risk Level is 'low'; does not override medium/high)."
        ),
    )
    run_parser.add_argument(
        "--force-implement",
        action="store_true",
        help="Continue to implement despite a medium/high Risk Level (recorded in metadata.json).",
    )
    run_parser.add_argument(
        "--risk",
        choices=["low", "medium", "high"],
        default=None,
        help="Override the computed Risk Level for this Run (sets overridden_by_user).",
    )
    run_parser.add_argument(
        "--review",
        action="store_true",
        help=(
            "Run the read-only Diff Review Phase after implementation and feed its "
            "findings into report.md. Never an approval gate and never changes the "
            "Run's outcome."
        ),
    )

    profile_parser = subparsers.add_parser(
        "profile", help="Detect and print the Repo Profile for a Target Repo (no Run is created)."
    )
    profile_parser.add_argument("target", help="Path to the Target Repo.")

    plan_parser = subparsers.add_parser(
        "plan",
        help=(
            "Staged driving: create a Run and run only the `plan` Phase, then "
            "stop for human review (continue with `ai-factory implement <run-id>`)."
        ),
    )
    plan_parser.add_argument("target", help="Path to the Target Repo.")
    plan_parser.add_argument("task", help="The task description.")
    plan_parser.add_argument(
        "--backend",
        required=True,
        help=(
            "AgentBackend preset to use for this Run (Manual Mode cannot drive "
            "staged phases). Built-in presets: " + ", ".join(sorted(PRESETS)) +
            "; user config may define additional presets."
        ),
    )
    plan_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )

    implement_parser = subparsers.add_parser(
        "implement",
        help="Staged driving: continue a Run created by `ai-factory plan` past `implement`/verify/fix-loop.",
    )
    implement_parser.add_argument("run_id", help="The Run ID to continue (from `ai-factory plan`).")
    implement_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )
    implement_parser.add_argument(
        "--review",
        action="store_true",
        help="Also run the read-only Diff Review Phase after implementation.",
    )

    review_parser = subparsers.add_parser(
        "review",
        help="Staged driving: run the read-only Diff Review Phase over a Run whose implement already completed.",
    )
    review_parser.add_argument("run_id", help="The Run ID to review.")
    review_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help=(
            "Re-enter an interrupted Run at its last incomplete Phase using "
            "persisted state."
        ),
    )
    resume_parser.add_argument("run_id", help="The Run ID to resume.")
    resume_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )
    resume_parser.add_argument(
        "--discard-phase-changes",
        action="store_true",
        help=(
            "Reset the factory-owned worktree to its last committed state before "
            "retrying an interrupted read-write Phase (implement/fix), discarding "
            "any partial changes it left behind. The target checkout is never "
            "touched."
        ),
    )
    resume_parser.add_argument(
        "--review",
        action="store_true",
        help="Also run the read-only Diff Review Phase if it is the only Phase left to resume.",
    )

    status_parser = subparsers.add_parser("status", help="Show a Run's outcome and Phase statuses.")
    status_parser.add_argument("run_id", help="The Run ID to inspect.")
    status_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )

    list_parser = subparsers.add_parser("list", help="List all Runs.")
    list_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )

    clean_parser = subparsers.add_parser(
        "clean", help="Remove a Run's factory-owned worktree, branch, and State Dir entry."
    )
    clean_parser.add_argument("run_id", nargs="?", default=None, help="The Run ID to clean.")
    clean_parser.add_argument(
        "--all", action="store_true", dest="clean_all", help="Clean every Run."
    )
    clean_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the State Dir (also settable via AI_FACTORY_STATE_DIR).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            return run_task(
                args.target,
                args.task,
                args.backend,
                args.state_dir,
                pause_after_plan=args.pause_after_plan,
                auto=args.auto,
                force_implement=args.force_implement,
                risk_override=args.risk,
                review=args.review,
            )
        except RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "plan":
        try:
            return plan_task(args.target, args.task, args.backend, args.state_dir)
        except RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "implement":
        try:
            return implement_task(args.run_id, args.state_dir, review=args.review)
        except RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "review":
        try:
            return review_task(args.run_id, args.state_dir)
        except RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "resume":
        try:
            return resume_task(
                args.run_id,
                args.state_dir,
                discard_phase_changes=args.discard_phase_changes,
                review=args.review,
            )
        except RunError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "profile":
        target_repo = Path(args.target).resolve()
        if not target_repo.is_dir():
            print(f"error: target '{target_repo}' is not a directory", file=sys.stderr)
            return 1
        print(json.dumps(build_profile(target_repo), indent=2))
        return 0

    if args.command == "status":
        state_dir = resolve_state_dir(args.state_dir)
        try:
            metadata = runs.load_run_metadata(state_dir, args.run_id)
        except runs.RunNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(views.render_status(metadata))
        return 0

    if args.command == "list":
        state_dir = resolve_state_dir(args.state_dir)
        print(views.render_list(runs.list_runs(state_dir)))
        return 0

    if args.command == "clean":
        state_dir = resolve_state_dir(args.state_dir)
        if args.clean_all and args.run_id is not None:
            parser.error("clean: pass either a run-id or --all, not both")
        if not args.clean_all and args.run_id is None:
            parser.error("clean: pass a run-id or --all")
        try:
            if args.clean_all:
                cleaned = cleanup.clean_all(state_dir)
                print("\n".join(cleaned) if cleaned else "(no runs to clean)")
            else:
                cleanup.clean_run(state_dir, args.run_id)
                print(f"cleaned {args.run_id}")
        except cleanup.CleanError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
