# Sandy Configuration File

Sandy reads a TOML configuration file for secrets, API keys, and plugin activation settings.

## File Location

Sandy looks for the config file in this order:

1. `~/.config/sandy/sandy.toml` — recommended (keeps secrets out of the project)
2. `./sandy.toml` — project root (useful for development)

The first file found is used.

## Creating Your Config

Copy `sandy.toml.example` from the project root:

```bash
mkdir -p ~/.config/sandy
cp sandy.toml.example ~/.config/sandy/sandy.toml
```

Then edit it with your actual API keys and settings.

## File Format (TOML)

The config uses [TOML](https://toml.io/en/) — a simple, human-readable format with sections and key/value pairs. No JSON quotes-and-commas, no YAML indentation.

### Conventions

| Key style | Meaning |
|-----------|---------|
| `UPPERCASE` | Environment variable — injected into the process at startup |
| `lowercase` | Configuration value — read by Sandy internals (e.g. `active`) |

### Structure

```toml
# Global environment variables (available to all plugins)
GLOBAL_ENV_VAR = "some-value"

[plugin-name]
active = yes                   # yes/no (case-insensitive) — default: yes
PLUGIN_SPECIFIC_KEY = "..."    # env var scoped to this section
```

### Plugin Activation

Set `active = no` in a plugin's section to disable it:

```toml
[spotify]
active = no
```

Disabled plugins are not loaded, so their commands won't match. Any plugin not mentioned in the config is active by default.

### Environment Variables

All UPPERCASE keys are applied to `os.environ` at startup. Existing environment variables are **not overridden** — if a variable is already set in the shell, the config value is ignored. This lets you override config values with shell exports.

Example:

```toml
[spotify]
active = yes
SPOTIPY_CLIENT_ID     = "abc123"
SPOTIPY_CLIENT_SECRET = "xyz789"
SPOTIPY_REDIRECT_URI  = "http://127.0.0.1:8888/callback"
```

## Security

- `sandy.toml` is listed in `.gitignore` — it will not be committed
- `sandy.toml.example` is committed and shows the expected keys with placeholder values
- Never put real secrets in `sandy.toml.example`
