# The Factory proposes changes but never lands them (v1)

> **Amended by ADR-0014.** The "automation runs straight through by default" rule
> below is superseded: a deterministic risk classifier now gates automatic
> continuation past planning (low-risk proceeds; medium/high pause). Everything
> else in this ADR still holds.

An automated Run ends at a proposed `factory/<run-id>` branch plus `diff.patch`,
verification logs, `report.md`, and `pr-body.md`. The Factory never merges,
pushes, or opens a pull request — the human remains the merge gate. This keeps the
safety promise end-to-end and means v1 needs no remote credentials, tokens, or
branch-protection knowledge.

The lifecycle is `profile → risk_classify → plan → [decision gate] → implement →
verify → fix-loop → report` (risk gating added in ADR-0014). Plan review
(`--pause-after-plan`) and diff review (`--review`) are opt-in. The
Fix Loop is bounded (default 1–2 attempts) and addresses only failures caused by
the agent's own changes, never broad unrelated rewrites.

## Consequences

- v1 carries no push/merge/PR code paths and no remote-credential handling.
- Landing is entirely manual; the Factory's job is to make landing easy, not to do
  it.
