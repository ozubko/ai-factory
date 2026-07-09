# Git worktree is the only isolation model for v1 automation

Automated runs isolate work in a git worktree and nothing else. An automation run
requires the target to be a git repository with at least one commit and a clean
working tree; it branches from a Base Ref (default `HEAD`) into a factory-managed
Run Branch/worktree, runs the agent there, and reports a diff against the base.
Non-git or dirty targets are refused with a clear error — the Factory never
silently stashes, copies, resets, or mutates the target's main working tree, which
is the core safety promise. Manual Mode still works on non-git folders because it
never mutates.

## Considered Options

- **Git worktree only** (chosen) — one isolation model, one diffing model, clean
  branch-based diffs. Cost: refuses non-git/dirty targets.
- **Copy-based sandbox fallback** — deferred. Adds a second isolation + diffing
  model and edge cases around ignored/generated files, symlinks, permissions,
  submodules, large repos, and cleanup. Revisit once the git path is solid.
