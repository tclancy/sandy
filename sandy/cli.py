import argparse
import os
import subprocess
import sys
import tempfile

import requests

from sandy.pipeline import run_pipeline
from sandy.progress import make_reporter


def _format_title(value: str) -> list[str]:
    return [value]


def _format_text(value: str) -> list[str]:
    return [value]


def _format_links(value: list[dict]) -> list[str]:
    return [f"  {link['label']}: {link['url']}" for link in value]


def _format_audio(url: str) -> list[str]:
    """Download and play an audio URL locally via afplay (macOS)."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        try:
            subprocess.run(["afplay", tmp_path], check=True)
        finally:
            os.unlink(tmp_path)
    except Exception:
        return [f"  (could not play audio: {url})"]
    return []


_FIELD_FORMATTERS: dict[str, object] = {
    "title": _format_title,
    "text": _format_text,
    "links": _format_links,
    "audio_url": _format_audio,
}


def _render_response(plugin_name: str, response: dict) -> str:
    """Format a plugin response dict as plain text for the CLI.

    Each key in the response is dispatched to a ``_format_{key}`` function
    via ``_FIELD_FORMATTERS``. Unknown keys are silently skipped, so new
    field types only require adding a formatter — no edits to this function.
    """
    lines = [f"[{plugin_name}]"]
    for key, value in response.items():
        formatter = _FIELD_FORMATTERS.get(key)
        if formatter:
            lines.extend(formatter(value))
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
        print(_render_response(plugin_name, response))

    return 0 if results else 1


def cli():
    """Entry point for the `sandy` console script."""
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nWrapping up early today!")
        sys.exit(0)
