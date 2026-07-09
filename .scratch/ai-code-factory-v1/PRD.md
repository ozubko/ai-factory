# PRD: AI Code Factory v1

Status: ready-for-agent
Feature: ai-code-factory-v1
Domain: see `CONTEXT.md` (glossary) and `docs/adr/0001–0014` (decisions)

## Problem Statement

I want to hand a coding agent a task against one of my repos and get real, useful
work back — but I don't trust today's "autonomous coding" tools. They run straight
through on any task, edit my working tree, make claims about tests I can't trust,
and sometimes try to land code. I can't tell the difference between a change that's
safe to automate (a small local bug fix) and one that needs my judgment (an auth
change, a migration, a broad refactor). I want AI to accelerate implementation
where that's appropriate, while keeping architecture, security, data, and
infrastructure decisions firmly in human hands — and I want the whole thing to be
local, inspectable, and safe by construction.

## Solution

**AI Code Factory** — a local, repo-portable **agentic engineering harness**. Given
a clean git Target Repo and a task, it runs AI agents inside a deterministic
workflow: it profiles the repo, **classifies the task's risk deterministically**,
plans, and then — **only for low-risk tasks** — implements, verifies, and reports;
for medium/high-risk tasks it pauses after planning for my explicit go-ahead. All
work happens on an isolated `factory/<run-id>` branch/worktree outside my checkout;
the Factory **never merges, pushes, opens a PR, or touches my working tree**. It
runs its own authoritative Verification Gate (agent claims are advisory), and hands
me a diff, a report, and a ready-to-paste PR body. The model runner is swappable
behind an `AgentBackend` seam, with a safe Manual Mode as the default and a generic
Subprocess backend (Codex/Claude as config presets) for automation.

## User Stories

**Submitting and running a task**

1. As a developer, I want to run `ai-factory run <repo> "<task>"`, so that I can get an isolated, verified attempt at a task without manual setup.
2. As a developer, I want the Factory to refuse to run automation on a non-git Target Repo, so that isolation guarantees always hold.
3. As a developer, I want the Factory to refuse automation on a dirty working tree, so that my uncommitted work is never stashed, reset, or clobbered.
4. As a developer, I want each Run pinned to a concrete base SHA at creation, so that resuming later builds on the intended commit even if `HEAD` moved.
5. As a developer, I want the Factory to create a `factory/<run-id>` branch and an out-of-tree worktree, so that my main working tree is never modified.
6. As a developer, I want every Run to have a stable, human-readable Run ID, so that I can inspect, resume, and clean it up later.

**Risk-aware gating (the core promise)**

7. As a cautious developer, I want the Factory to classify each task as `low`, `medium`, or `high` risk after profiling, so that automation only proceeds when it's appropriate.
8. As a developer, I want low-risk tasks to auto-continue through implementation and verification, so that small local changes are fast and hands-off.
9. As a developer, I want medium- and high-risk tasks to pause after `plan.md` by default, so that I review the plan before any code is written.
10. As a developer, I want the risk decision to be deterministic and factory-owned (not decided by the model), so that the same inputs always produce the same gate outcome.
11. As a developer, I want risk raised when there's weak or no verification available, so that high-blast-radius, untestable tasks don't slip through automatically.
12. As a developer, I want to see exactly why a Run paused ("risk classified medium/high"), so that I understand what needs my judgment.
13. As a developer, I want to override the computed risk with `--risk <low|medium|high>`, so that I can correct a misclassification for a specific run.
14. As a developer, I want `--pause-after-plan` to always stop after planning regardless of risk, so that I can force a review on any task.
15. As a developer, I want `--auto` to allow classifier-gated continuation explicitly, so that my intent to proceed-when-safe is recorded even if my config default is conservative.
16. As an advanced developer, I want `--force-implement` to continue despite medium/high risk, so that I can knowingly accept the risk — with that override recorded.
17. As a reviewer, I want the risk level, reasons, and whether it was overridden recorded in the Run's metadata, so that decisions are auditable.

**Planning**

18. As a developer, I want a Planning Agent to produce a structured `plan.md`, so that I get a predictable, reviewable plan.
19. As a developer, I want the plan to reflect the deterministic risk classification, so that risk is visible in the plan itself.
20. As a developer, I want the Planning Agent to receive my repo's profile and its own instruction files, so that the plan is repo-aware.
21. As a developer, I want the plan phase to be read-only-enforced, so that "planning" can never quietly change my code.

**Implementation, verification, fix-loop**

22. As a developer, I want an Implementation Agent to make changes in the isolated worktree, so that I can review a diff rather than trust a summary.
23. As a developer, I want the Factory to observe what actually changed via git, so that the reported diff is ground truth, not the agent's claim.
24. As a developer, I want the Factory to run an authoritative Verification Gate (install/lint/typecheck/test/build) in the worktree, so that pass/fail is objective.
25. As a developer, I want the Factory to distinguish agent-claimed results from factory-verified results, so that I never mistake a claim for a fact.
26. As a developer, I want a bounded Fix Loop (default 1–2 attempts) that only addresses failures from the agent's own changes, so that a failing gate gets a fair, contained repair attempt without broad rewrites.
27. As a developer, I want the Run to end in a clear Run Outcome (`implemented_verified`, `implemented_degraded`, `implemented_unverified`, etc.), so that I know the state at a glance.
28. As a developer, I want verification to run in a loud "degraded" mode when no commands are detected (not silently pass), so that I know there was no objective gate.

**Review and reporting**

29. As a developer, I want an optional Diff Review phase via `--review`, so that a review agent can critique the change and feed the report.
30. As a developer, I want a `report.md` that leads with the risk assessment and the factory-verified-vs-agent-claimed distinction, so that the trust story is front and centre.
31. As a developer, I want the report to state whether the Factory continued automatically or paused, and why, so that the run is self-explaining.
32. As a developer, I want a forge-neutral `pr-body.md` with a "verify before merging" footer, so that I can paste it into GitHub/GitLab/Bitbucket without rework.
33. As a developer, I want concrete next-step commands in the report (inspect worktree, switch branch), so that landing the change is easy.
34. As a developer, I want the Factory to never merge, push, or open a PR, so that I remain the merge gate and no remote credentials are ever needed.

**Backends and portability**

35. As a developer, I want Manual Mode as the default backend, so that I can prepare Prompt Bundles and inspect intended paths without any model call — safe while bootstrapping or when running inside another agent.
36. As a developer, I want Manual Mode to create no git refs or worktree, so that it is fully non-mutating.
37. As a developer, I want a generic Subprocess backend driven by a configurable command template, so that I can plug in any coding-agent CLI.
38. As a developer, I want Codex and Claude to be config Presets over the Subprocess backend, not bespoke code, so that CLI flag churn never breaks the Factory core.
39. As a developer, I want to select the backend with `--backend <name>` (over config, over the `manual` default), so that I control which runner is used per run.
40. As a developer, I want prompts passed to backends as files (system/user/combined), so that large prompts and single-input CLIs both work.
41. As a developer, I want the backend to guarantee each phase's output artifact exists (writing captured stdout if the CLI didn't), so that the Factory never has to parse arbitrary vendor output.

**Configuration**

42. As a repo maintainer, I want a `factory.toml` in my repo to pin odd install/test/build commands, so that the Factory works on repos with non-standard workflows.
43. As a developer, I want CLI flags to override repo config to override user config to override defaults, so that precedence is predictable.
44. As a security-conscious user, I want repo config to be unable to define backend command templates (only select a backend by name), so that a Target Repo can never choose which executable the Factory runs.
45. As a developer, I want to redirect the State Dir via `--state-dir`/`AI_FACTORY_STATE_DIR`, so that I can control where run artifacts live.

**Safety**

46. As a developer, I want the Factory to refuse to run any factory-owned command that matches a destructive Command Deny-list, so that a poisoned script can't do damage through the gate.
47. As a security-conscious user, I want secret file *values* never included in profiles, prompts, or reports (only presence recorded), so that credentials don't leak into agent context.
48. As a developer, I want cleanup to only ever remove factory-owned resources, so that my other branches, remotes, and files are never touched.
49. As a developer, I want the Factory to be honest that it does not sandbox the agent's own commands/network (that's delegated to the backend/preset), so that I'm not given a false sense of safety.

**Profiling**

50. As a developer, I want the Factory to profile Python, Node/TypeScript, and Makefile-based repos, so that the common cases are covered.
51. As a developer, I want each detected command tagged with its source (declared/inferred/repo-config) and confidence, so that I can judge how trustworthy the gate is.
52. As a developer, I want my repo's own instruction files (AGENTS.md, CLAUDE.md, .cursor/rules, copilot-instructions, CONTRIBUTING, README) surfaced into prompts (labeled, redacted, size-capped), so that plans respect repo conventions.
53. As a developer, I want factory safety rules to always outrank my repo's instruction files, so that repo conventions can never weaken safety.

**Resume, status, cleanup**

54. As a developer, I want to resume an interrupted Run at its last incomplete Phase, so that I don't restart from scratch.
55. As a developer, I want the Factory to refuse to auto-reset a read-write phase that left partial changes, requiring an explicit `--discard-phase-changes`, so that I never lose in-progress work unexpectedly.
56. As a developer, I want `ai-factory status <run-id>` and `ai-factory list`, so that I can see the state of my runs.
57. As a developer, I want `ai-factory clean <run-id>` (and `--all`) to remove only that run's worktree, branch, and state, so that cleanup is explicit and scoped.
58. As a developer, I want runs to persist until I clean them (no auto-GC), so that diffs and evidence survive for inspection.
59. As a developer, I want Run ID collisions to refuse rather than overwrite, so that I never clobber an existing run.

**Manual / staged driving**

60. As a developer, I want to drive phases explicitly (`plan`, then `implement`, then `review`) across separate invocations, so that I can review between steps.
61. As a developer, I want `ai-factory profile .` on its own, so that I can inspect what the Factory detects before committing to a run.

## Implementation Decisions

- **Language/runtime.** Python 3.11+, **zero runtime dependencies** (stdlib only) — ADR-0009. Dev-only tooling: pytest, ruff, mypy. `git` is a hard runtime dependency. CLI via `argparse`. Distribution `ai-factory`; console command `ai-factory`.
- **Lifecycle (risk-aware)** — ADR-0014, amends ADR-0003. Phases: `profile → risk_classify → plan → [decision gate] → implement → verify → fix-loop → [review] → report`. Default: auto-continue past planning only for `low` risk; `medium`/`high` pause after `plan.md`.
- **Risk classifier** — a deterministic, factory-owned module (NOT model-driven). Inputs: task-text keywords, Repo Profile, plan-predicted changed files (when available at the Decision Gate), available verification commands, presence/absence of tests, and risky file/path patterns (auth/authz, security/secrets, DB migrations, data mutation/deletion, infra/CI-CD/Terraform/K8s, payments/billing, public API contract, broad refactor/architecture). Produces `level` + `reasons[]`. The Decision Gate applies flags (`--pause-after-plan`, `--auto`, `--force-implement`, `--risk`).
- **Isolation** — ADR-0002. Git worktree is the only isolation model in v1. Automation preconditions: target is a git repo, ≥1 commit, clean working tree, resolvable base ref (default `HEAD`, pinned to a SHA). Manual Mode creates no git refs/worktree.
- **Never lands code** — ADR-0003. No merge/push/PR/remote operations; terminal output is the branch + `diff.patch` + verification logs + `report.md` + `pr-body.md`.
- **AgentBackend seam** — ADR-0004/0006. `AgentBackend.run(request) -> AgentResult`, side-effecting. `request`: phase, system_prompt, user_prompt, workdir, output_path, mode (`read_only`|`read_write`), limits. `result`: status, exit_code, stdout/stderr log paths, produced_paths, summary, observed_git_diff_path. `implement`/`fix` mutate the worktree; the Factory captures changes via `git diff <base>...HEAD` + `git status --porcelain` and never applies model patches itself. `plan`/`review` are read-only, enforced post-phase via git → `contract_violation` + saved evidence + halt. Backends: `Manual` (default) and generic `Subprocess`; `codex`/`claude`/`fake` are config Presets. Prompt Bundles written as files (`<phase>-system.md`, `<phase>-user.md`, `<phase>-combined.md`).
- **Verification** — ADR-0005. Factory-owned, authoritative, run in the worktree. Command detection precedence: CLI flags > repo `factory.toml` > declared (package.json scripts / Makefile targets / pyproject/tox/nox) > ecosystem heuristics > degraded. Ecosystems v1: Python, Node/TS, Makefile fallback (extensible registry).
- **Config** — ADR-0008. Precedence: CLI > repo `factory.toml` > user config (`$XDG_CONFIG_HOME/ai-factory/config.toml`) > defaults. Repo config may set commands/hints/prefs/risk-override and select a backend by name only — never define command templates.
- **Safety** — ADR-0007. Command Deny-list on all factory-run commands (match ⇒ refuse the Run); secret-value redaction; scoped cleanup only; agent sandboxing explicitly delegated to backend/preset and documented.
- **Prompts** — ADR-0010. Four static system-prompt assets (plan/implement/review/fix); `plan-task.md` is the de-vendored 11-section plan contract plus a Risk Assessment section. User prompts assembled programmatically (no template engine). Authority hierarchy: factory safety > phase system prompt > repo instructions > task prompt.
- **State & durability** — ADR-0012. All run state lives outside the Target Repo under the State Dir; runs persist until explicit `ai-factory clean`; no auto-GC; run-ID collisions refuse.
- **Status taxonomy (serialized contract)** — ADR-0011/0014:
  - Phase status: `pending | running | succeeded | failed | contract_violation | interrupted | not_executed | skipped`.
  - Run outcome: `planned | implemented_verified | implemented_degraded | implemented_unverified | contract_violation | failed | interrupted`. `planned` is disambiguated by `outcome_reason` (`--pause-after-plan`, risk-gated pause, or manual mode).
- **Risk metadata shape** (decision-encoding schema, from ADR-0014):
  ```json
  "risk": { "level": "low|medium|high", "reasons": [],
            "auto_continue_allowed": true, "overridden_by_user": false }
  ```
- **CLI surface.** `run`, `plan`, `implement`, `review`, `resume`, `status`, `list`, `profile`, `clean`. Risk/gate flags: `--pause-after-plan`, `--auto`, `--force-implement`, `--risk`. Also `--backend`, `--review`, `--state-dir`, `--discard-phase-changes`.

## Testing Decisions

- **What makes a good test here:** it exercises the feature at the highest seam and asserts on **observable outputs only** — never on internal call sequences or private structure. Observable outputs are: the Run's `metadata.json` (Run Outcome, phase statuses, `risk{}`, `outcome_reason`), the artifacts (`plan.md`, `report.md`, `pr-body.md`, `diff.patch`, `verify/*.log`), process exit codes, and git state (the `factory/<run-id>` branch exists; the Target Repo working tree is unchanged).
- **The one code seam: `AgentBackend`** (ADR-0004/0006). Tests inject the **Fake Agent** (a deterministic local CLI Preset) rather than any live vendor. Fake Agent scenarios: writes a plan; edits the worktree on implement; exits non-zero (`fail`); mutates during a read-only phase (`contract-violation`); exits 0 without producing `output_path` (`bad-output`); repairs a failing gate (`fix-success`); leaves it failing (`fix-fail`).
- **Drive from the top (highest seam):** invoke the CLI / run lifecycle end-to-end against **real throwaway git repos created in a temp dir**, with the State Dir redirected to temp. Real `git` is used (never mocked) because the Factory is fundamentally a git-worktree orchestrator; git-dependent tests skip with a clear message if `git` is absent. `Subprocess` backend is exercised **only via the Fake Agent** in CI — real Codex/Claude are documented presets, not CI-gated.
- **Modules tested directly at their own boundary** (deterministic pure functions — trust-critical): the risk classifier (task+profile → level+reasons, including low/medium/high and the `--risk` override), the safety module (command string → refuse/allow; text → redacted), and command detection (repo → commands + source/confidence).
- **Priority scenarios (release bar, not a coverage %):** low-risk auto-continues to `implemented_verified`; medium/high pause after plan (`planned`, risk-gated `outcome_reason`); `--pause-after-plan` always pauses; `--force-implement` overrides; `--risk` recorded with `overridden_by_user`; risk deterministic (same inputs → same level); non-git/dirty target refused; read-only mutation → `contract_violation`; deny-listed command refused; secrets never leak; no-commands → `implemented_degraded`; interrupted read-write phase → resume refuses without `--discard-phase-changes`; `clean` removes only factory-owned resources.
- **Prior art:** none in-repo yet (greenfield) — this PRD establishes the pytest convention. Test layout mirrors the package, with a fakes dir for the Fake Agent and a fixtures dir of tiny per-ecosystem sample repos.

## Out of Scope

Per ADR-0013 (deferred, not rejected): copy-based sandbox fallback; Go/Rust/Java ecosystems; bespoke Codex/Claude adapters; any push/merge/PR/remote operation; full subprocess sandboxing and network egress control; a template engine; argv-based preset format; `--local-state`; a `factory` command alias; auto-GC/retention windows; `--allow-unsafe-commands`; Windows support; monorepo/multi-target orchestration; concurrent/parallel runs; git submodules; Git LFS; multiple workspaces per repo; database/service orchestration; Docker-based sandbox execution; interactive approval UI; web dashboard; forge-specific PR formatting; dependency-install policy beyond the detected install command; long-running/background/scheduled runs; metrics/telemetry; a plugin system. Additionally: **LLM-driven risk scoring is out of scope — the risk classifier stays deterministic and heuristic in v1.**

## Further Notes

- Positioning to preserve in all copy: *a local, repo-portable agentic engineering harness that uses AI agents inside a deterministic safety, planning, verification, and reporting workflow* — not an unchecked autonomous coding bot.
- Bootstrap: the `ai-factory` repo itself must be `git init`'d with an initial commit before it can be dogfooded in Automation Mode (clean-git precondition).
- Open question carried from design: `--auto` is treated as the explicit form of the default classifier-gated policy (proceed only when permitted; does not override medium/high). If the intended default should instead be *conservative* (always pause unless `--auto`), that's a one-line Decision Gate flip — flag during implementation.
- Full design rationale lives in `docs/adr/0001–0014` and the domain glossary in `CONTEXT.md`; implementers should read the ADRs for the area they touch and use glossary vocabulary.
