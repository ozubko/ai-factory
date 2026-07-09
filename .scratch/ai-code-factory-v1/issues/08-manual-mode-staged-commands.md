# Manual Mode (full) + staged phase commands

Status: ready-for-agent

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

- [ ] `--backend manual` (default) prepares bundles + prints intended paths and creates no branch/worktree/git refs
- [ ] Manual Mode works against a non-git folder (non-mutating)
- [ ] Staged driving: `plan` then `implement` across separate invocations operate on the same Run
- [ ] Manual phases return `not_executed`

## Blocked by

- Issue 05 (`issues/05-planning-phase-prompts.md`)
