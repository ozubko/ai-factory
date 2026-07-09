# Config layering and the repo-vs-user trust split

Config resolves in precedence order:

```
CLI flags
> <target-repo>/factory.toml            (repo config — target-controlled)
> ${XDG_CONFIG_HOME:-~/.config}/ai-factory/config.toml   (user config — trusted)
> built-in defaults
```

Repo config is treated as **target-controlled input, not trusted factory policy**.
It may define verification commands (each still deny-list-checked and recorded
with `source: repo_config` and `config_path`), ecosystem hints, include/exclude
paths, and verification preferences, and it may select a backend **by name only**
(`[backend] name = "manual"`). It may **not** define backend command
templates/presets — a subprocess template chooses *which executable the Factory
runs*, so the target must never be able to program that. Backend presets come only
from user config or built-ins.

Rationale: repo-level config is needed for portability (real repos have odd
install/test/build commands), but letting the target define what executable runs
would hand it the keys.

## Considered Options

- **Layered config with repo-vs-user trust split** (chosen).
- **User-level + CLI only** — rejected: loses repo portability; every user
  re-discovers repo-specific commands.
- **Full repo config including presets/templates** — rejected: lets the target
  program the Factory.
