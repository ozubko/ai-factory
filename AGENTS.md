# AGENTS.md

Repo-local instructions for AI agents working on the **AI Code Factory**. See
[`CONTEXT.md`](./CONTEXT.md) for the domain glossary and [`docs/adr/`](./docs/adr/)
for architectural decisions.

## Agent skills

### Issue tracker

Issues and PRDs live as local markdown under `.scratch/<feature>/` — no external
tracker, and PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical role strings (defaults: `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`), recorded as `Status:` lines in each issue file. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See
`docs/agents/domain.md`.
