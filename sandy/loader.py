import importlib.util
import os
import sys


REQUIRED_ATTRS = ("name", "commands", "handle")


def load_plugins(plugin_dir: str) -> list:
    """Discover and load valid plugins from a directory.

    Imports each .py file (except __init__.py), validates it has the
    required attributes (name, commands, handle) with handle being
    callable, and returns valid plugins sorted alphabetically by filename.
    """
    plugins = []
    if not os.path.isdir(plugin_dir):
        return plugins

    filenames = sorted(
        f for f in os.listdir(plugin_dir)
        if f.endswith(".py") and f != "__init__.py"
    )

    for filename in filenames:
        filepath = os.path.join(plugin_dir, filename)
        # Use full filepath in module name to avoid sys.modules collisions
        # when loading plugins from different directories (e.g. in tests)
        module_name = f"sandy_plugin_{os.path.abspath(filepath).replace('/', '_')}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                print(f"Warning: could not create loader for {filename}", file=sys.stderr)
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Warning: failed to load {filename}: {e}", file=sys.stderr)
            continue

        missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
        if missing:
            print(
                f"Warning: skipping {filename}: missing {', '.join(missing)}",
                file=sys.stderr,
            )
            continue

        if not callable(module.handle):
            print(
                f"Warning: skipping {filename}: handle is not callable",
                file=sys.stderr,
            )
            continue

        plugins.append(module)

    return plugins
