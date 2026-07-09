# Walking skeleton — end-to-end `run` with the Fake Agent

Status: done — all acceptance criteria verified

## Parent

PRD: `.scratch/ai-code-factory-v1/PRD.md`

## What to build

The thinnest complete Run. `ai-factory run <target> "<task>" --backend fake` against
a clean git Target Repo: create a Run with a human-readable Run ID and a State Dir
outside the target; resolve and pin the Base Ref to a concrete SHA; create a
`factory/<run-id>` branch and an out-of-tree worktree; invoke a single `implement`
Phase through the `AgentBackend` seam using the Fake Agent (which edits a file in the
worktree); the Factory observes the change via git and writes `diff.patch`,
`changed-files.txt`, `metadata.json` (with a Run Outcome), and a minimal `report.md`.
The target's main working tree is never modified.

This slice establishes the foundations the rest build on: the zero-runtime-dependency
package (argparse CLI, `ai-factory` console command), the side-effecting `AgentBackend`
contract (base + Subprocess), the Fake Agent test double, Run state, and the git
isolation helpers. Prefactor: `git init` + an initial commit so the Factory can be
dogfooded on itself. See ADR-0001, 0002, 0004, 0006, 0009, 0012.

## Acceptance criteria

- [ ] `ai-factory run <clean-git-repo> "task" --backend fake` completes and exits 0
- [ ] A `factory/<run-id>` branch and an out-of-tree worktree are created; the target's original working tree is unchanged
- [ ] State Dir contains `metadata.json` (with a Run Outcome), `diff.patch`, `changed-files.txt`, and `report.md`
- [ ] Base Ref is pinned to a concrete SHA recorded in `metadata.json`
- [ ] The `implement` Phase runs through the `AgentBackend` seam; the diff is captured from git, not from agent claims
- [ ] Package installs with zero runtime dependencies; the `ai-factory` command works
- [ ] A test drives the CLI against a real temp git repo and asserts on the observable artifacts

## Blocked by

None — can start immediately.

## Comments

**Code is complete; execution could not be verified in this session (environment
constraint, not a code issue) — see below.**

Implemented, zero-runtime-dependency (ADR-0009), under `src/ai_factory/`:

- `backend/base.py` — the `AgentBackend` seam: `AgentRequest`/`AgentResult` +
  `AgentBackend` ABC (ADR-0001, ADR-0004).
- `backend/subprocess_backend.py` — the generic `SubprocessBackend`: renders a
  `{placeholder}` command template via `shlex.split`, runs it with
  `cwd=worktree`, captures stdout/stderr to log files, and guarantees the
  phase's `output_path` artifact exists (ADR-0006).
- `presets/fake_agent.py` + `presets/registry.py` — the Fake Agent CLI test
  double (`python -m ai_factory.presets.fake_agent`) and its command-template
  preset; for `implement` it edits `FAKE_AGENT_CHANGE.md` in its cwd (the
  worktree) so the Factory observes a real git change (CONTEXT.md: Fake Agent).
- `git_ops.py` — worktree isolation helpers (ADR-0002): `is_git_repo`,
  `resolve_sha`, `add_worktree`, `commit_worktree_changes`, `diff_against_base`,
  `changed_files`.
- `run_id.py`, `state_dir.py` — Run ID (slug + short hash) and State Dir
  resolution (`--state-dir` > `AI_FACTORY_STATE_DIR` > XDG default, ADR-0012).
- `runner.py` — orchestrates the walking-skeleton lifecycle: refuses non-git
  targets, pins Base Ref to a concrete SHA, creates the `factory/<run-id>`
  branch + out-of-tree worktree, runs the `implement` Phase through the
  `AgentBackend` seam, then **commits the observed worktree changes onto the
  Run Branch** before diffing — plain `git diff <base_sha>` never shows
  brand-new untracked files, so without this commit the Fake Agent's new file
  would silently vanish from `diff.patch`. Writes `metadata.json` (Run Outcome
  `implemented_degraded`, since no Verification Gate exists until issue 04),
  `diff.patch`, `changed-files.txt`, and `report.md`.
- `cli.py` — argparse-only `ai-factory run <target> <task> --backend
  {fake,manual} [--state-dir]`. `--backend manual` raises a clear
  not-yet-implemented error (Manual Mode is issue 08's scope, not this one).
- `pyproject.toml` — zero runtime deps, `ai-factory` console script, dev extras
  (pytest/ruff/mypy).
- `tests/conftest.py` + `tests/test_walking_skeleton.py` — a real temp git repo
  fixture and an end-to-end test driving `ai_factory.cli.main(["run", ...,
  "--backend", "fake", ...])`, asserting on `metadata.json`, `diff.patch`,
  `changed-files.txt`, `report.md`, the `factory/<run-id>` branch, the
  out-of-tree worktree, and that the target's working tree/HEAD are untouched.
  Plus two refusal tests (`--backend manual`, non-git target) asserting no
  State Dir side effects.

**What's not done, and why:** this session's Bash tool consistently returned
"This command requires approval" for every mutating/interpreter-invoking
command (`git init`, `git add`, `git commit`, `python3 -c ...`, `python3 -m
py_compile`, `python3 -m pytest`, `pip install`), with no human available to
approve — confirmed both directly and via a fresh subagent, which hit the same
wall at `git init`. Read-only/simple commands (`ls`, `find`, `rm`, `echo`,
`python3 --version`, `git status`) worked. As a result, this session could not:

1. Run the repo's `git init` + initial commit prefactor (needed to dogfood the
   Factory on itself in a later issue).
2. Install the package (`pip install -e ".[dev]"`) or run `pytest`.

The code was instead verified by a careful manual trace-through (argument
wiring, git command semantics, dataclass fields, JSON/report shapes), which is
how the untracked-file diff bug above was caught and fixed before it could ship.

**For whoever picks this up next**, from `/Users/oleksandr.zubko/Projects/ai-factory`:

```
git init
git add -A
git commit -m "Initial commit: AI Code Factory walking skeleton"
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -v
```

If the tests pass as-is, this issue's acceptance criteria are met and the
Status can move to `ready-for-agent` done / closed. If anything fails, the
most likely fragile spots are: `sys.executable` containing spaces (breaks the
`shlex.split` command-template rendering) and git commit identity (mitigated
by passing `-c user.name=... -c user.email=...` explicitly, so it should not
depend on the target repo's or the user's global git config).

## Comments (follow-up session)

The sandbox restriction from the prior session was gone; ran the deferred prefactor
and verification exactly as specified:

- `git init` + `git add -A` + initial commit (with explicit `-c user.name=... -c
  user.email=...`, as anticipated) — the workspace is now git-initialised.
- `python3 -m pip install -e ".[dev]"` — installed cleanly, zero runtime
  dependencies, dev extras (pytest/ruff/mypy) resolved fine.
- `python3 -m pytest tests/ -v` — **63 passed, 0 failed** (3 of which are this
  issue's walking-skeleton tests: fake-backend happy path, `--backend manual`
  refusal, non-git-target refusal). The other 60 belong to later issues whose
  code was already present in the tree from other work; out of scope for this
  issue but noted since they also pass.
- Manual end-to-end smoke test beyond the automated tests: ran `ai-factory run
  . "demo task" --backend fake --state-dir ...` against a fresh temp git repo.
  Confirmed exit 0; `factory/<run-id>` branch and out-of-tree worktree created;
  target repo's `git status` clean and still on `main` (untouched); State Dir
  contains `metadata.json` (Run Outcome `implemented_degraded`, `verify`
  skipped/degraded since no Verification Gate exists yet), `diff.patch`,
  `changed-files.txt`, `report.md`, `plan.md`; `base_sha` pinned to a concrete
  commit SHA in `metadata.json`. Cleaned up the temp demo dirs afterward.

None of the anticipated fragile spots (executable-path spaces, git commit
identity) materialized as problems. All acceptance criteria are met; no code
changes were needed this session — this was purely finishing the deferred
bootstrap/verification.
