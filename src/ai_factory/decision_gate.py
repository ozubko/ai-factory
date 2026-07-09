"""The Decision Gate after `plan` (ADR-0014, CONTEXT.md: Decision Gate).

Deterministically decides whether an Automation Mode Run continues past
planning into `implement`, given the final (post-plan) Risk Level and the
Run's flags. Never model-decided: the same `(level, flags)` always produces
the same decision.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateDecision:
    should_implement: bool
    # Set only when pausing; becomes the Run's `outcome_reason` (Run Outcome
    # `planned`, disambiguated per ADR-0014/0011).
    outcome_reason: str | None
    force_implement_used: bool


def decide(
    level: str,
    *,
    pause_after_plan: bool = False,
    auto: bool = False,
    force_implement: bool = False,
) -> GateDecision:
    """`auto` is accepted for auditability (it records the user's explicit
    intent to allow classifier-gated continuation) but never changes the
    decision by itself: it does not override `medium`/`high` (ADR-0014) --
    only `--force-implement` does, and `--pause-after-plan` always wins."""
    del auto

    if pause_after_plan:
        return GateDecision(
            should_implement=False,
            outcome_reason="--pause-after-plan was passed; pausing after plan.md regardless of risk",
            force_implement_used=False,
        )

    if level == "low":
        return GateDecision(should_implement=True, outcome_reason=None, force_implement_used=False)

    if force_implement:
        return GateDecision(should_implement=True, outcome_reason=None, force_implement_used=True)

    return GateDecision(
        should_implement=False,
        outcome_reason=(
            f"risk classified '{level}'; pausing after plan.md for explicit human "
            "continuation (use --force-implement to override, or --risk to correct "
            "the classification)"
        ),
        force_implement_used=False,
    )
