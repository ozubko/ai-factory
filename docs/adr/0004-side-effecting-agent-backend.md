# Side-effecting AgentBackend; the Factory observes side effects via git

Backends act in place rather than returning patches:
`AgentBackend.run(request) -> AgentResult`. A real backend runs its coding-agent
CLI with `cwd = worktree`; `implement`/`fix` phases mutate the worktree, and the
Factory captures the result with `git diff <base>...HEAD` and
`git status --porcelain` (saved as `diff.patch` / `changed-files.txt`). The
Factory never applies model-produced patches itself in v1.

Each backend is responsible for producing the phase's designated `output_path`
artifact (`plan.md`, `review.md`, `fix-summary.md`) in whatever way fits the tool
— instruct the CLI to write it, or capture the agent's output and write it itself.
The adapter normalizes everything into `AgentResult`, so the core never parses
arbitrary stdout. Because `output_path` lives outside the worktree (in the State
Dir), a sandboxed CLI that can't write there just has its output captured by the
backend.

`plan` and `review` are read-only phases, enforced by the Factory: after the
phase it checks the worktree via git, and if a read-only phase changed files it
records a `contract_violation` (saving `contract-violation.patch` and status),
then stops the run — this is stronger than a prompt-level instruction.

## Considered Options

- **Side-effecting + git observation** (chosen) — matches how Codex/Claude CLIs
  actually behave; the Factory owns artifacts and validates repo side effects.
- **Pure patch-returning backends** — rejected: fights the tools, which edit files
  rather than emit patches.
