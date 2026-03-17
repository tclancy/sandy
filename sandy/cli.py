import argparse
import sys

from sandy.pipeline import run_pipeline


def _format_text(plugin_name: str, response: dict) -> str:
    """Format a plugin response dict as plain text for the CLI."""
    lines = [f"[{plugin_name}]"]
    if "title" in response:
        lines.append(response["title"])
    lines.append(response.get("text", ""))
    if "links" in response:
        for link in response["links"]:
            lines.append(f"  {link['label']}: {link['url']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route text commands to plugins.")
    parser.add_argument("text", nargs="?", help="The command text to process")
    parser.add_argument("--actor", default="tom", help="Who is sending the command (default: tom)")
    args = parser.parse_args(argv)

    if not args.text:
        parser.print_usage(file=sys.stderr)
        return 1

    results, errors = run_pipeline(args.text, args.actor)

    for error in errors:
        print(error, file=sys.stderr)

    if not results and not errors:
        print("I don't know how to do that yet.")
        return 1

    for i, (plugin_name, response) in enumerate(results):
        if i > 0:
            print()
        print(_format_text(plugin_name, response))

    return 0 if results else 1


def cli():
    """Entry point for the `sandy` console script."""
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nWrapping up early today!")
        sys.exit(0)
