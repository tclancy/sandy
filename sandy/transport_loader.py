"""Discover and validate transport plugins from sandy/transports/."""

import importlib.util
import os
import sys

REQUIRED_ATTRS = ("name", "listen", "format_response")


def load_transports(transport_dir: str, config: dict | None = None) -> list:
    """Discover and load valid transport plugins from a directory.

    If config has a [daemon] section with a transports list,
    only transports whose name appears in that list are returned.
    """
    if config is None:
        config = {}
    active_list = config.get("daemon", {}).get("transports")

    transports = []
    if not os.path.isdir(transport_dir):
        return transports

    filenames = sorted(
        f for f in os.listdir(transport_dir) if f.endswith(".py") and f != "__init__.py"
    )

    for filename in filenames:
        filepath = os.path.join(transport_dir, filename)
        module_name = f"sandy_transport_{os.path.abspath(filepath).replace('/', '_')}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                print(f"Warning: could not create loader for {filename}", file=sys.stderr)
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Warning: failed to load transport {filename}: {e}", file=sys.stderr)
            continue

        missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
        if missing:
            print(
                f"Warning: skipping transport {filename}: missing {', '.join(missing)}",
                file=sys.stderr,
            )
            continue

        if not callable(getattr(module, "listen")):
            print(
                f"Warning: skipping transport {filename}: listen is not callable", file=sys.stderr
            )
            continue

        if active_list is not None and module.name not in active_list:
            continue

        transports.append(module)

    return transports
