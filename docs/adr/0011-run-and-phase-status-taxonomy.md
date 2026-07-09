# Run outcome and phase status taxonomy

Two canonical status levels, serialized in `metadata.json` and surfaced in the CLI
and `report.md`. Because tooling depends on these strings, the names are fixed
here.

**Phase status:**

```
pending | running | succeeded | failed | contract_violation
        | interrupted | not_executed | skipped
```

- `not_executed` — Manual Mode prepared the bundle without calling a model.
- `skipped` — intentionally not run (e.g. `review` without `--review`).
- `degraded` is deliberately **not** a phase status.

**Run outcome:**

```
planned | implemented_verified | implemented_degraded
        | implemented_unverified | contract_violation | failed | interrupted
```

- `planned` — stopped after plan (`--pause-after-plan` or the `plan` command).
- `implemented_verified` — changes made and the authoritative Verification Gate
  passed.
- `implemented_degraded` — changes made, but no complete authoritative gate was
  available (e.g. no commands detected). Named this way (not bare `degraded`) so
  the outcome encodes that implementation happened.
- `implemented_unverified` — changes made, the gate ran, but failed after the
  bounded Fix Loop.
- `contract_violation` / `failed` / `interrupted` — as named.

`metadata.json` also carries a freeform `outcome_reason`, and each phase records a
`reason` plus `started_at`/`finished_at`.

## Considered Options

- **Two-level taxonomy with `implemented_degraded`** (chosen).
- **Bare `degraded` outcome** — rejected: ambiguous about whether code was
  implemented.
