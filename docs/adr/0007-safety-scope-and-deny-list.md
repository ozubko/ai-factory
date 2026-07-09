# Factory safety scope: real process guarantees, delegated agent sandboxing

The Factory enforces the process-level safety it can actually guarantee and does
not pretend to sandbox arbitrary agent behavior.

**Factory-owned guarantees:**

1. Worktree isolation (target working tree never touched).
2. No push, no merge, no PR creation.
3. A **command deny-list** on every command the Factory itself runs (verification
   commands from CLI flags, `factory.toml`, declared `package.json`/`Makefile`
   scripts, or ecosystem heuristics). A match **refuses the run** with an explicit
   message — never warn-and-continue. Patterns include `rm -rf`,
   `git reset --hard`, `git clean -fd`, `git push[ --force]`, `git branch -D`,
   `docker system prune`, `dropdb`, `terraform apply`, `kubectl delete`, etc.
4. Secret-value redaction: profiles and bundles record the *presence* of
   `.env`/credential files (`secrets_detected`, `secret_values_included: false`)
   but never their values — in `profile.json`, any prompt, or `report.md`.
5. Scoped cleanup: only ever removes the factory worktree, the `factory/<run-id>`
   branch, and that run's state directory.

**Delegated to the backend/preset (documented, not hidden):** what the coding-agent
CLI may execute — filesystem reach beyond the worktree, network egress, arbitrary
shell. Codex/Claude presets should prefer safer vendor modes where available;
`Manual` is safest because it runs no agent subprocess.

An explicit escape hatch (`--allow-unsafe-commands` / `--allow-command "<cmd>"`) is
deferred; the v1 default is refusal.

## Considered Options

- **Guarantee what we can + delegate the rest, documented** (chosen).
- **Attempt full subprocess sandboxing in v1** — rejected: not portable across
  backends; would give a false sense of safety.
- **Warn-and-continue on deny-list hits** — rejected: unsafe default.
