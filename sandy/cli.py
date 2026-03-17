import argparse
import os
import sys

from sandy.config import apply_env, load_config
from sandy.loader import load_plugins
from sandy.matcher import find_matches


def _get_plugin_dir() -> str:
    """Return the path to the built-in plugins directory."""
    return os.path.join(os.path.dirname(__file__), "plugins")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route text commands to plugins.")
    parser.add_argument("text", nargs="?", help="The command text to process")
    parser.add_argument("--actor", default="tom", help="Who is sending the command (default: tom)")
    args = parser.parse_args(argv)

    if not args.text:
        parser.print_usage(file=sys.stderr)
        return 1

    config = load_config()
    apply_env(config)

    plugin_dir = _get_plugin_dir()
    plugins = load_plugins(plugin_dir, config)
    matches = find_matches(args.text, plugins)

    if not matches:
        print("I don't know how to do that yet.")
        return 1

    successes = 0
    for i, match in enumerate(matches):
        if i > 0:
            print()  # blank line between plugin outputs
        try:
            result = match.handle(args.text, args.actor)
            print(f"[{match.name}]")
            print(result)
            successes += 1
        except Exception as e:
            print(f"{match.name} plugin failed: {e}", file=sys.stderr)

    return 0 if successes > 0 else 1


def cli():
    """Entry point for the `sandy` console script."""
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nWrapping up early today!")
        sys.exit(0)
