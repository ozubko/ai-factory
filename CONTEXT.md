# AI Code Factory

A local, repo-portable **agentic engineering harness**: it runs AI agents inside a
deterministic safety, risk-classification, planning, verification, and reporting
workflow against any target repository, using swappable agent backends. It
automates implementation when a task is local and verifiable, and pauses for human
judgment when it is not — not an unchecked autonomous coding bot.

## Language

**Factory**:
This project — the orchestration layer that drives a task through profiling,
planning, implementation, and verification against a target repo.
_Avoid_: pipeline, tool, wrapper

**Target Repo**:
The external repository the factory operates on, distinct from the factory's own
codebase.
_Avoid_: project, codebase, workspace

**Run**:
One end-to-end pass of the factory over a single task against one target repo.
_Avoid_: job, session, build

**Backend**:
The swappable component that executes an agent Phase (a.k.a. `AgentBackend`).
v1 has two implementations — `Manual` and `Subprocess`; vendors like Codex and
Claude are Presets over `Subprocess`, not separate classes.
_Avoid_: provider, driver, engine, model

**Preset**:
A named backend configuration in `factory.toml` (`codex`, `claude`, `fake`, or
user-defined) that selects and parameterizes a Backend — usually a command
template for `Subprocess`. Vendors are Presets, not code.
_Avoid_: adapter, driver, profile

**Fake Agent**:
The test-double CLI that satisfies the Subprocess contract without a live vendor,
used to validate the full lifecycle (edits the worktree, writes artifacts, and
can simulate failure or a Contract Violation).
_Avoid_: mock, stub, dummy

**Manual Mode**:
The default backend that prepares all run inputs (profile, prompt bundles,
expected outputs, worktree paths, verification commands) but invokes no model and
creates no branch, worktree, or other git refs.
_Avoid_: dry-run, harness mode

**Planning Agent**:
The portable prompt/phase that inspects the target repo and produces the Plan;
it must not modify code.
_Avoid_: planner

**Implementation Agent**:
The portable prompt/phase that executes the Plan by editing the target repo.
_Avoid_: coder, executor, dev agent

**Plan**:
The Planning Agent's output artifact describing the intended change (`plan.md`).
_Avoid_: spec, design doc

**Repo Profile**:
The deterministic snapshot of a target repo — language, package manager,
structure, verification commands, and agent instructions.
_Avoid_: scan, analysis

**Prompt Bundle**:
The per-phase inputs handed to a Backend, written as files: a static
`<phase>-system.md`, a programmatically assembled `<phase>-user.md`, and a
`<phase>-combined.md` for backends that take a single input.
_Avoid_: context pack, payload

**Repository Instructions**:
The target repo's own guidance files (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules`,
`.github/copilot-instructions.md`, `CONTRIBUTING.md`, `README.md`) surfaced into
prompts — labeled, secret-redacted, size-capped, and always outranked by factory
safety rules.
_Avoid_: repo docs, conventions

**Verification Gate**:
The factory-owned, authoritative checkpoint where the target repo's
install/lint/typecheck/test/build commands are run in the worktree; agent-claimed
results are never authoritative. Runs in degraded mode (loud, not a refusal) when
no commands can be detected.
_Avoid_: check, CI

**Ecosystem**:
A registered detector (Python, Node/TypeScript, Makefile fallback in v1) that
identifies a target repo's stack and its declared verification commands.
_Avoid_: language pack, plugin, adapter

**Fix Loop**:
The bounded set of retry attempts (default 1–2) the Implementation Agent gets to
make the Verification Gate pass, addressing only failures caused by its own
changes.
_Avoid_: retry, self-heal, broad rewrite

**Diff Review**:
An optional post-implementation phase (opt-in via `--review`) where a review
agent critiques the Run's diff and feeds findings into the report; it is not an
approval gate.
_Avoid_: code review, approval

**Phase**:
One unit of agent work in a Run — `plan`, `implement`, `review`, or `fix` — each
with its own role prompt and a read-only (`plan`, `review`) or read-write
(`implement`, `fix`) posture.
_Avoid_: step, stage

**Contract Violation**:
A Run outcome where a read-only Phase modified the worktree; detected by the
Factory via git after the phase, recorded with saved evidence, and halts the run.
_Avoid_: error, failure

**Command Deny-list**:
The set of destructive command patterns the Factory refuses to run in any
factory-owned command (verification/gate commands); a match refuses the Run
rather than warning.
_Avoid_: blocklist, blacklist

**Repo Config**:
A `factory.toml` inside the target repo — target-controlled input that may set
verification commands/preferences and select a Backend by name, but may never
define backend command templates. Distinct from trusted user config.
_Avoid_: project config, local config

**Automation Mode**:
A Run that creates an isolated Run Branch/worktree and invokes a real backend; it
continues past planning to implementation only when the Decision Gate permits (low
risk), otherwise pauses after `plan.md`. Requires a clean git target.
_Avoid_: auto mode, full mode

**Run Branch**:
The factory-managed git branch and linked worktree created for one automation
run, isolating changes from the target's main working tree.
_Avoid_: temp branch, scratch branch

**Risk Level**:
A Run's deterministic risk rating — `low`, `medium`, or `high` — computed by the
Factory from task text, repo profile, verification availability, and risky
file/path patterns.
_Avoid_: severity, priority

**Risk Classification**:
The `risk_classify` Phase, run after profiling: a factory-owned, deterministic
(non-LLM in v1) computation of the Run's Risk Level and reasons.
_Avoid_: risk scoring, triage

**Decision Gate**:
The checkpoint after planning that decides whether Automation Mode continues to
implementation — auto-continues only for low risk, otherwise pauses after
`plan.md` (overridable with `--force-implement`).
_Avoid_: approval gate, checkpoint

**Resume**:
`ai-factory resume <run-id>` re-enters an interrupted Run at its last
incomplete Phase from persisted `metadata.json` — phase-granular, with no
mid-phase checkpointing. Refuses to re-run a partial read-write Phase
(`implement`/`fix`) until `--discard-phase-changes` resets only the
factory-owned worktree to the Phase's last committed state; read-only Phases
(`review`) are idempotent to resume.
_Avoid_: retry, restart, replay

**Base Ref**:
The commit an automation run branches from and diffs against; defaults to `HEAD`.
_Avoid_: baseline, parent

**State Dir**:
The external location holding all factory-owned run state, outside the target
repo; defaults to `${XDG_STATE_HOME:-~/.local/state}/ai-factory`.
_Avoid_: work dir, output dir, cache dir

**Run ID**:
The stable, human-readable identifier for a Run (task slug + short hash); also
the run's directory name and the suffix of its `factory/<run-id>` branch.
_Avoid_: job id, uuid

**Run Outcome**:
The terminal state of a Run: `planned`, `implemented_verified`,
`implemented_degraded`, `implemented_unverified`, `contract_violation`, `failed`,
or `interrupted`. Distinct from per-Phase status.
_Avoid_: result, exit status

**Run Report**:
The Run's primary human deliverable (`report.md` + forge-neutral `pr-body.md`) —
leads with the factory-verification-vs-agent-claims distinction and ends with
concrete next steps. The Factory produces it but never lands the code.
_Avoid_: summary, output
