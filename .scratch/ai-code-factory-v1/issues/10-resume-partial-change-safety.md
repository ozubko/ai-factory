# Resume + partial-change safety

Status: done

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

`ai-factory resume <run-id>` re-enters an interrupted Run at its last incomplete Phase
from persisted state — phase-granular, with no mid-phase checkpointing. Before
re-running a read-write Phase (`implement`/`fix`) that left partial worktree changes,
resume refuses and directs the user to inspect or pass `--discard-phase-changes`,
which resets only the factory-owned worktree to the phase's base state (never the
target). Re-running read-only phases is idempotent. See ADR-0002, 0011, 0012.

## Acceptance criteria

- [ ] An interrupted Run resumes at the last incomplete Phase using persisted state
- [ ] Resuming a partial read-write Phase refuses without `--discard-phase-changes`; the message explains the options
- [ ] `--discard-phase-changes` resets only the factory worktree and proceeds; the target checkout is untouched
- [ ] Resuming a read-only Phase is idempotent

## Blocked by

- Issue 06 (`issues/06-risk-aware-lifecycle.md`)

## Comments

Implemented `ai-factory resume <run-id>`, reading persisted `metadata.json` to find
the last incomplete Phase and continue from there, sharing the exact `implement`
and `review` pipelines already used by staged driving (`_continue_implement`,
`_continue_review`, extracted from `implement_task`/`review_task`).

- Plan-succeeded, implement not yet run (whether gate-paused or genuinely
  interrupted) → resume drives `implement` → Verification Gate → Fix Loop
  (+ `--review`), identically to `ai-factory implement`.
- Before re-driving `implement`/`fix`, resume checks the factory worktree with
  `git status`; if an interrupted attempt left it dirty, resume refuses with a
  message pointing at the worktree path and `--discard-phase-changes`.
  `--discard-phase-changes` calls a new `git_ops.reset_worktree_to_head`
  (`git reset --hard HEAD` + `git clean -fd`), scoped to the worktree directory
  only — the target's working tree is a physically separate directory and is
  never touched.
- Re-running the read-only `review` Phase is unconditionally idempotent: any
  worktree dirt left by an interrupted review attempt is discarded without
  requiring `--discard-phase-changes`, since read-only leftovers can only be
  Contract-Violation-worthy garbage, never legitimate partial work.
- Runs with a terminal halt (`contract_violation`/`failed`), a missing
  `metadata.json`, a missing worktree, or nothing left to do all refuse with a
  clear explanation ("nothing to resume").

Added the `Resume` term to `CONTEXT.md`. New tests in
`tests/test_resume_partial_change_safety.py`; full suite (118 tests), ruff, and
mypy all pass.
