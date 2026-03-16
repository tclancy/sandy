"""Sandy configuration loader.

Reads a TOML config file and applies env vars from it.
Config is searched in order:
  1. ~/.config/sandy/sandy.toml
  2. ./sandy.toml

Conventions:
  - UPPERCASE keys are environment variables (set into os.environ)
  - lowercase keys are configuration values (e.g. active = yes/no)
  - [plugin-name] sections scope config to that plugin
  - active = yes/no controls whether the loader includes the plugin
"""

import os
import tomllib
from pathlib import Path


_SEARCH_PATHS = [
    Path.home() / ".config" / "sandy" / "sandy.toml",
    Path("sandy.toml"),
]


def find_config_path() -> Path | None:
    """Return the first existing config file path, or None."""
    for path in _SEARCH_PATHS:
        if path.exists():
            return path
    return None


def load_config(path: Path | None = None) -> dict:
    """Load TOML config from *path*, or search default locations.

    Returns an empty dict if no config file is found.
    """
    if path is None:
        path = find_config_path()
    if path is None:
        return {}

    with open(path, "rb") as f:
        return tomllib.load(f)


def apply_env(config: dict) -> None:
    """Set UPPERCASE keys from the config into os.environ.

    Applies global-level UPPERCASE keys first, then plugin-section keys.
    Plugin-section keys override global keys with the same name.
    """
    for key, value in config.items():
        if isinstance(value, dict):
            # plugin section — apply its UPPERCASE keys
            for pkey, pval in value.items():
                if pkey.isupper():
                    os.environ.setdefault(pkey, str(pval))
        elif key.isupper():
            # global env var
            os.environ.setdefault(key, str(value))


def is_active(config: dict, plugin_name: str) -> bool:
    """Return True if the plugin is active (or not mentioned in config).

    A plugin is inactive only when its section exists and sets active to
    a falsy value ("no", "false", "0", "off", case-insensitive).
    If the plugin has no section, it is active by default.
    """
    section = config.get(plugin_name)
    if not isinstance(section, dict):
        return True
    raw = section.get("active", "yes")
    return str(raw).strip().lower() not in ("no", "false", "0", "off")
