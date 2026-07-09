# Manual Mode (full) + staged phase commands

Status: done — verified (all acceptance criteria met; see Comments)

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

A fully non-mutating Manual backend (the default) that prepares the Repo Profile and
Prompt Bundles and prints the intended Run ID / branch / worktree / State Dir paths,
returning `not_executed` and creating no git refs or worktree. Explicit phase commands
`ai-factory plan | implement | review <...>` for staged, human-driven runs across
separate invocations, reading and writing the same Run state. Manual Mode must work
against a non-git folder because it never mutates. See ADR-0001, 0006, 0010.

## Acceptance criteria

- [x] `--backend manual` (default) prepares bundles + prints intended paths and creates no branch/worktree/git refs
- [x] Manual Mode works against a non-git folder (non-mutating)
- [x] Staged driving: `plan` then `implement` across separate invocations operate on the same Run
- [x] Manual phases return `not_executed`

## Blocked by

- Issue 05 (`issues/05-planning-phase-prompts.md`)

## Comments

Implemented both halves:

- **Manual Mode (`run_manual` in `runner.py`)** is now the default `--backend` for
  `ai-factory run`. It never checks git preconditions, never creates a worktree or
  branch, and works against any directory. It builds the Repo Profile and the
  `plan` Prompt Bundle directly against the target path, prints the intended Run
  ID / branch / worktree / State Dir paths to stdout, and writes `metadata.json`
  with every Phase `not_executed` and `outcome: "planned"` (`outcome_reason`
  explicitly says "Manual Mode"). `report.md`/`pr-body.md` render cleanly for this
  case (`report.py`'s "Next steps" section now branches on whether a
  worktree/branch/base_sha actually exist).
- **Staged phase commands** (`ai-factory plan|implement|review`) drive a real,
  git-isolated Run across separate invocations, reading/writing the same
  `metadata.json`. `plan` creates the branch+worktree, runs only `plan`, and stops
  (`outcome: "planned"`, staged reason). `implement` reloads the run's persisted
  state (worktree path, backend, task, base SHA), re-derives the Repo Profile from
  the worktree on disk, and runs `implement` + the Verification Gate + Fix Loop.
  `review` runs the read-only Diff Review Phase afterward. Both refuse with a clear
  `RunError` if called out of order (e.g. `implement` before `plan` succeeded, or
  re-running an already-executed phase) or against a Manual Mode run (no worktree
  to continue).
- Refactored the shared implement/verify/fix-loop and review logic out of
  `run_task` into `_run_implement_and_verify`/`_run_review` so Automation Mode and
  the staged commands share identical, tested behavior (zero behavior change for
  `run_task` — verified via the full existing test suite).
- Removed the now-obsolete `test_manual_backend_is_not_yet_implemented` (it
  asserted the old placeholder behavior this issue replaces) and added
  `tests/test_manual_mode_staged_commands.py` covering all four acceptance
  criteria, including non-git-target Manual Mode, no-git-refs-created, staged
  `plan`→`implement`→`review`, and refusal paths.

Verified: `pytest -q` (106 passed), `ruff check`, `mypy src` all clean; also
smoke-tested the real CLI end-to-end (`run --backend manual` against both a git
and a non-git folder, and `plan`/`implement`/`review` against a git target with
the `fake` preset), confirming the target's working tree and git refs are
untouched by Manual Mode and that staged commands correctly continue the same Run.
