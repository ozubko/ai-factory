# Runs are durable output; cleanup is explicit and scoped

A Run's state dir, worktree, and `factory/<run-id>` branch persist until explicitly
removed — they are product output the human needs to inspect the diff, read logs,
and open a PR. Failed and interrupted runs are kept too (debugging + resume). v1
has no auto-GC, no retention window, and no background cleanup.

Removal happens only via `ai-factory clean <run-id>` (and `ai-factory clean
--all`), which touches only factory-owned resources: `git worktree remove`, delete
`factory/<run-id>`, and delete the run's state dir — never the target working
tree, non-factory branches, remotes, or user files. Run-ID collisions refuse
rather than overwrite.

Rationale: durability serves inspection and the trust story; auto-deletion would
destroy diffs and evidence the human has not yet landed.
