# Verification is factory-owned and deterministically detected

The Verification Gate is owned and run by the Factory inside the worktree, and its
result is the only authoritative pass/fail — agent-claimed results are advisory
and reported as such. Verification commands are chosen deterministically, never
invented by the model, in strict priority order:

1. CLI flags (`--test`, `--lint`, …)
2. `factory.toml` `[commands]`
3. repo-declared commands (`package.json` scripts, `Makefile` targets,
   `pyproject.toml`/`tox`/`nox`)
4. ecosystem heuristics (tagged `inferred`)
5. skipped → **degraded mode**

When no commands can be detected the Run proceeds in a *loud* degraded mode
(clearly flagged in `report.md`) rather than failing. Each command records its
`source` (`declared` | `inferred`) and a confidence.

Rationale: the Factory's whole value is wrapping agent behavior in an objective
process; letting the model choose the authoritative gate would collapse that. The
trade-off is less breadth/convenience in exchange for trust.

## Considered Options

- **Deterministic detection + config/CLI override** (chosen).
- **Model-chosen commands** — rejected: the gate would no longer be objective.
