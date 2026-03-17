import argparse
import sys

from sandy.pipeline import run_pipeline
from sandy.progress import make_reporter


def _format_text(plugin_name: str, response) -> str:
    """Format a plugin response as plain text for the CLI.

    Handles both legacy string responses and the standard dict response format.
    """
    lines = [f"[{plugin_name}]"]
    if isinstance(response, str):
        lines.append(response)
        return "\n".join(lines)
    if "title" in response:
        lines.append(response["title"])
    if "text" in response:
        lines.append(response["text"])
    if "links" in response:
        for link in response["links"]:
            lines.append(f"  {link['label']}: {link['url']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Handle `sandy serve` before argparse (avoids subparser/positional conflict)
    if argv and argv[0] == "serve":
        from sandy.daemon import serve

        serve()
        return 0

    parser = argparse.ArgumentParser(description="Route text commands to plugins.")
    parser.add_argument("text", nargs="?", help="The command text to process")
    parser.add_argument("--actor", default="tom", help="Who is sending the command (default: tom)")
    args = parser.parse_args(argv)

    if not args.text:
        parser.print_usage(file=sys.stderr)
        return 1

    results, errors = run_pipeline(
        args.text,
        args.actor,
        progress_factory=make_reporter,
    )

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
