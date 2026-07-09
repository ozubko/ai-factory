# v1 scope boundary

v1 is deliberately a small, safe, local, git-based delivery harness.

**Core promise:** given a clean git repo and a task, `ai-factory` creates an
isolated branch/worktree, runs a portable agent workflow, verifies the result
objectively, and hands a human a diff, report, and PR body — without touching the
target checkout or landing code.

**In scope:** Python 3.11+, zero runtime dependencies, argparse CLI, clean-git
required for automation, external XDG state dir, factory-managed branch/worktree,
Manual backend default + generic Subprocess backend, Fake-CLI-tested-in-CI, Python
+ Node/TS + Makefile command detection, deterministic factory-owned verification
gate, no push/merge/PR, durable runs, explicit cleanup only.

**Explicitly deferred (not rejected forever):**

- copy-based sandbox fallback
- Go / Rust / Java ecosystems
- bespoke Codex / Claude adapters
- push / merge / PR creation / any remote operation
- full subprocess sandboxing; network egress control
- template engine; argv-based preset format
- `--local-state`; `factory` command alias
- auto-GC / retention windows; `--allow-unsafe-commands`
- Windows support; monorepo / multi-target orchestration; concurrent runs
- git submodules; Git LFS handling; multiple workspaces per repo
- database/service orchestration; Docker-based sandbox execution
- interactive approval UI; web dashboard; forge-specific PR formatting
- dependency-install policy beyond the detected install command
- long-running / background / scheduled runs; metrics / telemetry; plugin system

These sit outside the v1 trust boundary; each is a candidate for a later,
separately-reasoned iteration.
