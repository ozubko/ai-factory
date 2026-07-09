# Pluggable AgentBackend with manual default, automation as the direction

The Factory is an orchestration layer around portable agent prompts; the model
runner is swapped behind an `AgentBackend` seam (Manual, Codex, Claude, …).
Manual Mode is the default so the Factory is useful without ever calling a model
— essential while bootstrapping the Factory and when running inside an
interactive coding agent — while autonomous automation through a subprocess-style
backend is the headline direction for small-to-medium tasks.

## Considered Options

- **Orchestrator only** — hard-wire a headless CLI and always automate. Rejected:
  ties the Factory to one vendor and can't run safely inside another agent.
- **Harness only** — never call a model; only prepare bundles for a human/agent.
  Rejected: useful, but not a "factory" and gives up the automation goal.
- **Hybrid via `AgentBackend`** (chosen) — one seam, Manual default, real backends
  opt-in. Keeps portability and lets the same core serve both modes.
