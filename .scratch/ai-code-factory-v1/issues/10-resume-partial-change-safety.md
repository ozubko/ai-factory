# Resume + partial-change safety

Status: ready-for-agent

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
