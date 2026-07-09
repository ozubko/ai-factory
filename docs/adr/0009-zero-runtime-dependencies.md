# Zero runtime dependencies (stdlib only)

The Factory has no third-party runtime dependencies in v1 — only the Python
stdlib (`argparse`, `subprocess`, `pathlib`, `json`, `tomllib`, `shlex`). Dev-only
tooling (`pytest`, `ruff`, `mypy`) is allowed. `tomllib` is read-only, which is
fine because users hand-author `factory.toml` and the Factory never writes TOML.

Rationale: a tool that runs coding agents against your repositories should be
trivial to install, easy to inspect, and easy to trust — those properties matter
more than the ergonomics a CLI framework (`click`/`typer`) or a validation library
(`pydantic`) would add.

Trade-off: we hand-roll CLI parsing (`argparse`) and config validation instead of
leaning on third-party libraries. Accepted for v1.
