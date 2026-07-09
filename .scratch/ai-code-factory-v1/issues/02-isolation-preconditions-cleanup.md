# Isolation preconditions, status/list, scoped cleanup

Status: done — verified (all acceptance criteria met; see Comments)

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

Make the skeleton safe and inspectable. Automation refuses when the Target Repo is
not a git repo, has no commits, or has a dirty working tree — each with a clear,
actionable error and no side effects (never stash/reset/copy). Add
`ai-factory status <run-id>` (Run Outcome + per-Phase status) and `ai-factory list`
(all runs). Add `ai-factory clean <run-id>` and `clean --all` that remove only
factory-owned resources — the worktree (`git worktree remove`), the `factory/<run-id>`
branch, and the Run's State Dir — never the target working tree, other branches,
remotes, or user files. Run-ID collisions refuse rather than overwrite. Runs persist
until explicitly cleaned (no auto-GC). See ADR-0002, 0007, 0012.

## Acceptance criteria

- [ ] Non-git target → automation refused with a clear error; nothing created
- [ ] Dirty working tree → automation refused with a clear error; no stash/reset/copy
- [ ] `status`/`list` report runs with outcomes and phase statuses
- [ ] `clean <run-id>` removes only that run's worktree, branch, and State Dir; other branches/remotes/files untouched
- [ ] Re-using an existing Run ID refuses instead of overwriting
- [ ] Runs are not auto-deleted

## Blocked by

- Issue 01 (`issues/01-walking-skeleton.md`)

## Comments

**Code is complete; execution could not be verified in this session (environment
constraint, not a code issue) — see below.**

Implemented, zero-runtime-dependency, under `src/ai_factory/`:

- `git_ops.py` — added `has_commits` (`git rev-parse --verify HEAD`) and
  `is_clean` (`git status --porcelain` empty) precondition checks, plus scoped
  cleanup primitives `branch_exists`, `remove_worktree` (`git worktree remove
  --force`, safe because the worktree only ever holds factory-committed
  changes), and `delete_branch` (`git branch -D`).
- `runner.py` — `run_task` now checks `is_git_repo` → `has_commits` →
  `is_clean`, in that order, **before** the State Dir/run directory is created,
  so a refusal has zero side effects (no stash/reset/copy — matches ADR-0002).
  Each failure raises `RunError` with an actionable message. The pre-existing
  Run-ID-collision check (`run_dir.exists()` before `mkdir`) already satisfied
  "refuse rather than overwrite" and is now covered by a real test.
- `runs.py` (new) — read-only Run listing/lookup: `load_run_metadata`,
  `list_run_ids`, `list_runs`, and `RunNotFoundError`. Never mutates. A Run
  directory whose `metadata.json` is missing (e.g. interrupted before it was
  written) is still listed with outcome `unknown` rather than silently dropped.
- `views.py` (new) — plain-text rendering for `status` (Run Outcome + reason +
  per-Phase status) and `list` (one row per Run: id, outcome, task).
- `cleanup.py` (new) — `clean_run`/`clean_all`, scoped to exactly the three
  factory-owned resources named in ADR-0007/0012: the worktree (via
  `git worktree remove`), the `factory/<run-id>` branch (`git branch -D`), and
  the Run's State Dir entry (`shutil.rmtree`). Guards `target_repo.exists()`
  before touching git so a Run whose target repo was itself deleted still
  cleans its State Dir. Never touches other branches, remotes, or the target's
  working tree/HEAD.
- `cli.py` — added `status <run-id>`, `list`, and `clean <run-id> | --all`
  subcommands (argparse only, ADR-0009), each accepting `--state-dir`.
- `tests/test_isolation_preconditions_cleanup.py` (new) — end-to-end tests
  against real temp git repos: refusal on no-commits / dirty (modified and
  untracked) targets with no State Dir side effects and the dirty file left
  untouched; `status`/`list` content assertions; `clean <run-id>` removing
  worktree + branch + State Dir while leaving the target repo's branch list and
  working tree clean; `clean --all`; and a Run-ID-collision test (via
  monkeypatching `generate_run_id` to force a real collision) asserting the
  original run's `metadata.json` is untouched.

**What's not done, and why:** this session's Bash tool returned "This command
requires approval" for every mutating or interpreter-invoking command (`git
init`, `python3 -m pytest`, `python3 -c ...`), with no human available to
approve (AFK session) — the same environment constraint hit by issue 01. As a
result this session could not run the test suite. The code was instead
verified by a careful manual trace-through (git command semantics — including
the `git branch --list` `*`/`+` prefix handling for `branch_exists`, ordering
of `remove_worktree` before `shutil.rmtree`, and that all three precondition
checks run before any State Dir side effect), which mirrors how issue 01's
diff bug was caught without a live test run.

**For whoever picks this up next**, from `/Users/oleksandr.zubko/Projects/ai-factory`
(after issue 01's `git init` prefactor has landed):

```
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -v
```

If `tests/test_isolation_preconditions_cleanup.py` passes alongside the
existing walking-skeleton tests, this issue's acceptance criteria are met and
the Status can move to done/closed.

---

**Update (follow-up session): verified.** The prior session's sandbox
constraint is gone (the target repo is now git-initialised, per issue 01's
checkpoint). Ran the previously-blocked commands directly:

- `python3 -m pytest tests/ -v` → **63 passed**, including all 10 tests in
  `tests/test_isolation_preconditions_cleanup.py` (no-commits refusal, dirty
  working tree refusal for both modified and untracked files, `status`,
  `list`, `clean <run-id>` scoped removal, `clean --all`, unknown-run-id
  refusals for `status`/`clean`, and the run-ID-collision refusal).
- `python3 -m ruff check src/ tests/` → all checks passed.
- `python3 -m mypy src/` → 2 pre-existing errors in `runner.py` (risk/decision
  gate dict typing), unrelated to this issue's scope (that file was last
  touched in the issue-01 commit; this issue's precondition checks in it were
  already present and type-clean) — not fixed here since they're out of scope
  for isolation/status/cleanup.

All six acceptance criteria are satisfied by the existing code (no additional
code changes were needed this session — the prior session's implementation
was correct on manual trace-through and is now confirmed by a real test run).
Status moved to done.
