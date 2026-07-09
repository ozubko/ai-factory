# AI Code Factory

A local, repo-portable **agentic engineering harness**: it runs AI agents inside a
deterministic safety, risk-classification, planning, verification, and reporting
workflow against any target repository, using swappable agent backends. It
automates implementation when a task is local and verifiable, and pauses for human
judgment when it is not — not an unchecked autonomous coding bot.

See [`CONTEXT.md`](./CONTEXT.md) for the domain glossary and [`docs/adr/`](./docs/adr/)
for the design decisions behind everything below.

## Install

Requires Python 3.11+ and `git`. Zero runtime dependencies.

```bash
pip install -e ".[dev]"   # dev extras: pytest, ruff, mypy
```

## Quickstart

```bash
cd /path/to/some/clean/git/repo
ai-factory run . "fix the off-by-one in parse_range()"
```

This will:

1. Refuse if the target isn't a git repo with a commit and a clean working tree.
2. Pin the current commit as the Base Ref, create a `factory/<run-id>` branch and
   an out-of-tree worktree — your working tree is never touched.
3. Classify the task's risk (`low`/`medium`/`high`), deterministically, no model
   call involved.
4. Plan. **Low risk auto-continues to implementation; medium/high pause after
   `plan.md`** for you to review (see `--force-implement`/`--auto` below).
5. Implement, run the repo's own verification commands (install/lint/typecheck/
   test/build) as the authoritative gate, and retry a bounded number of times on
   failure.
6. Write `report.md` and `pr-body.md` — the Factory never merges, pushes, or opens
   a PR. You are the merge gate.

Everything lands under the State Dir, **outside** the target repo:
`${XDG_STATE_HOME:-~/.local/state}/ai-factory/runs/<run-id>/` (override with
`--state-dir` or `AI_FACTORY_STATE_DIR`).

Try it risk-free first with the built-in test double, which makes no real model
call:

```bash
ai-factory run . "demo task" --backend fake
ai-factory list
ai-factory status <run-id>
ai-factory clean <run-id>   # removes only that run's worktree/branch/state
```

## Backends: what actually runs the agent

`AgentBackend` is the one swappable seam (ADR-0001, ADR-0004, ADR-0006). There are
two implementations:

- **`manual`** (the default) — never calls a model, creates no git refs or
  worktree. It prepares the Repo Profile and Prompt Bundles and prints the
  Run's intended paths. Works even against non-git folders. Use it to inspect
  what the Factory would do, or to drive phases yourself.
- **`subprocess`** — runs a configurable command template. Vendors (`codex`,
  `claude`) and the test double (`fake`) are named **Presets** over this one
  backend — data in `src/ai_factory/presets/registry.py` or your own
  `~/.config/ai-factory/config.toml`, never bespoke code (ADR-0006).

```bash
ai-factory run . "task" --backend fake     # deterministic test double
ai-factory run . "task" --backend claude   # real Claude Code CLI
ai-factory run . "task" --backend codex    # real Codex CLI
```

**Honesty note:** the `claude`/`codex` presets are written against each CLI's
documented flags, but — per ADR-0006 — only `fake`/`manual` are exercised in this
project's own test suite. Treat them as a verified starting point, not a
guarantee. If your installed CLI version differs, override the preset in your own
user config rather than editing the registry:

```toml
# ~/.config/ai-factory/config.toml
[presets]
claude = "claude -p ... --dangerously-skip-permissions ..."  # your variant
```

A repo's own `factory.toml` may select a backend **by name** but can never define
a template — a target repo must never choose which executable the Factory runs
(ADR-0006/0008).

### A note on unattended automation

`claude`'s default preset uses `--permission-mode acceptEdits`, which auto-accepts
file edits but still gates shell commands behind an approval prompt. With nobody
present to approve, an `implement`/`fix` Phase that needs to run a shell command
will stall. For genuinely unattended runs, override the preset to use
`--dangerously-skip-permissions` instead — understand that trade-off before
enabling it. The Factory does not sandbox what the agent itself can execute; that
is delegated to the backend/preset by design, and documented rather than hidden
(ADR-0007).

## Risk-aware automation

The core feature (ADR-0014): a deterministic, factory-owned classifier — never
the model — decides whether a Run may continue past planning.

```bash
ai-factory run . "fix a small localized bug"                  # low risk → auto-continues
ai-factory run . "add authentication and handle credentials"  # high risk → pauses after plan.md
ai-factory run . "task" --pause-after-plan                    # always pause, any risk
ai-factory run . "task" --force-implement                     # continue despite medium/high (recorded)
ai-factory run . "task" --risk low                             # override the computed level
```

## Staged / manual driving

Drive a Run phase-by-phase across separate invocations, reviewing between steps:

```bash
ai-factory plan . "task" --backend claude
# ... inspect plan.md, then ...
ai-factory implement <run-id>
ai-factory review <run-id>       # optional Diff Review
ai-factory resume <run-id>       # re-enter an interrupted run at its last phase
```

## What this is not

Per the [v1 scope boundary](./docs/adr/0013-v1-scope-boundary.md): no push, merge,
or PR creation; no full sandboxing of the agent's own commands or network; no
Go/Rust/Java support yet (Python, Node/TypeScript, and a Makefile fallback
ship in v1); no Windows support; no auto-cleanup of old runs (`ai-factory clean`
is explicit). See that ADR for the complete, intentionally deferred list.

## Development

```bash
pytest tests/ -q
ruff check src/ tests/
mypy src/
```
