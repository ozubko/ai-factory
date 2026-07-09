"""The Fake Agent — a deterministic test-double CLI satisfying the Subprocess
backend contract without a live vendor (CONTEXT.md: Fake Agent).

Invoked as `python -m ai_factory.presets.fake_agent`. Behavior is deterministic
per phase:

- `plan` / `review` are read-only: they write a contract-compliant artifact to
  `--output` and never touch the worktree, *unless* `--mutate-readonly` is
  passed, in which case they also edit a file in the worktree to simulate a
  misbehaving read-only Phase (used to exercise the Factory's Contract
  Violation detection).
- `implement` / `fix` each edit a distinct, deterministic marker file in the
  worktree (their `cwd`), so the Factory can observe a real git diff.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..prompts import PLAN_HEADINGS

_FAKE_PLAN_MD = (
    "\n\n".join(f"{heading}\n\n(Fake Agent placeholder content.)" for heading in PLAN_HEADINGS)
    + "\n"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake-agent")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--mutate-readonly",
        action="store_true",
        help=(
            "Simulate a misbehaving read-only Phase (plan/review) by editing "
            "the worktree anyway, so the Factory's Contract Violation "
            "detection can be exercised end-to-end."
        ),
    )
    parser.add_argument(
        "--mutate-readonly-phase",
        default=None,
        help=(
            "Restrict --mutate-readonly to this phase only (e.g. 'review'), so "
            "a single read-only Phase's Contract Violation path can be "
            "exercised in isolation. Default: mutate any read-only phase."
        ),
    )
    args = parser.parse_args(argv)

    def _should_mutate() -> bool:
        if not args.mutate_readonly:
            return False
        return args.mutate_readonly_phase in (None, args.phase)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.phase == "plan":
        output_path.write_text(_FAKE_PLAN_MD)
        if _should_mutate():
            Path("FAKE_AGENT_PLAN_VIOLATION.md").write_text(
                "Fake Agent violated the read-only plan Phase contract.\n"
            )
        summary = "Fake Agent wrote a contract-compliant plan.md."
    elif args.phase == "review":
        if _should_mutate():
            Path("FAKE_AGENT_REVIEW_VIOLATION.md").write_text(
                "Fake Agent violated the read-only review Phase contract.\n"
            )
        summary = "Fake Agent review: no issues found."
        output_path.write_text(summary + "\n")
    elif args.phase == "implement":
        marker = Path("FAKE_AGENT_CHANGE.md")
        marker.write_text("Fake Agent implement phase touched this file.\n")
        summary = f"Fake Agent edited {marker} in the worktree."
        output_path.write_text(summary + "\n")
    elif args.phase == "fix":
        marker = Path("FAKE_AGENT_FIX.md")
        marker.write_text("Fake Agent fix phase touched this file.\n")
        summary = f"Fake Agent edited {marker} in the worktree."
        output_path.write_text(summary + "\n")
    else:
        summary = f"Fake Agent has no behavior for phase '{args.phase}'."
        output_path.write_text(summary + "\n")

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
