# Prompt architecture: static system prompts, assembled user prompts, instruction authority

Each Phase's system prompt is a static asset in `prompts/` (`plan-task.md`,
`implement-task.md`, `review-diff.md`, `fix-failures.md`) containing only role,
rules, phase boundaries, safety constraints, and the output contract — no
repo-specific paths, commands, task text, run IDs, or backend details.
`plan-task.md` is the de-vendored 11-section Planning Agent contract; the Factory
validates that the produced `plan.md` has the expected major headings (missing →
degraded plan quality / contract violation).

> Amended by ADR-0014: the plan contract gains a `## 12. Risk Assessment` section,
> and the plan/implement user prompts receive the deterministic risk
> classification.

The per-phase **user** prompt is assembled programmatically from run state (task,
profile, detected commands with source/confidence, bounded file tree, instruction
files, `plan.md`, `diff.patch`, verification logs, phase status). No template
engine in v1 — a deterministic string builder, which is easier to test.

The target's own instruction files (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*`,
`.github/copilot-instructions.md`, `CONTRIBUTING.md`, `README.md`) are surfaced
into the plan/implement prompts: labeled by path, secret-redacted, size-capped
(truncation recorded in `profile.json`).

**Authority hierarchy (highest first):**

```
factory safety rules  >  phase system prompt  >  repo instruction files  >  task user prompt
```

If repo instructions conflict with factory safety, factory safety wins.

## Considered Options

- **Static system + programmatic user assembly** (chosen) — deterministic,
  testable, zero-dep.
- **Template engine (Jinja etc.)** — rejected: adds a dependency and is harder to
  test deterministically.
- **Repo instructions as top authority** — rejected: safety must not be
  overridable by target-controlled content.
