"""Whole-tree formatting guard — the check CI runs, run locally.

`main` sat red at CI's `Format check (ruff)` step from 2026-07-28 23:53 ET onward
and nobody noticed locally, because **no local hook looks at the same file set CI
does** (sandy#159).

The mechanism is worth writing down, because "bump the pre-commit rev" is the
obvious fix and it does not work:

- CI runs `uv run ruff format --check .` and lets **ruff** discover files. As of
  ruff 0.16.0 that discovery includes Python code blocks inside **Markdown**.
  A routine patch-level Dependabot bump (0.15.22 -> 0.16.0, d856864) therefore
  widened the formatter's scope from "our source" to "our prose" overnight, and
  five docs nobody had touched in weeks started failing.
- pre-commit's `ruff-format` hook declares `types_or: [python, pyi, jupyter]`
  (verified in astral-sh/ruff-pre-commit's `.pre-commit-hooks.yaml` at both
  v0.15.6 and v0.16.0), so **pre-commit never passes it a `.md` file at any
  version**. It is not a stale-pin problem; the hook is structurally blind to
  the class of file that broke.
- pre-commit also passes only *changed* files, so a doc that is already committed
  and unformatted stays invisible forever — which is exactly how this landed.

Hence this test. It runs the same whole-tree command CI runs, from the pre-commit
`pytest` hook (`pass_filenames: false`, `always_run: true`), so the gate that
actually gates merges is evaluated before the push rather than after.

The repo's answer to the ruff 0.16 scope change is
`[tool.ruff.format] exclude = ["*.md"]` in `pyproject.toml` — see that comment for
the reasoning. This test does not assert that setting exists, deliberately: it
asserts the *outcome* CI cares about. Reformatting the docs instead would be a
different valid answer and should keep this test green.

**Which ruff runs is load-bearing, and getting it wrong fails silently.** Code
review caught this guard reporting a clean pass over the live regression: an
interpreter outside this project (Tom's shell exports a `VIRTUAL_ENV` pointing at
another repo, which every `uv run` here warns about) carries ruff 0.15.6, and
0.15.6 does not discover Markdown at all. The check ran, found nothing to
complain about, and went green for the same reason the bug existed. So the binary
is resolved from the project venv first, and its version is asserted against the
floor this project *declares* in `pyproject.toml` — derived, not duplicated, so a
future Dependabot bump moves the floor without anyone remembering to edit here.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# tests/ sits directly under the repo root. Derived from __file__ rather than
# shelled out to `git rev-parse` so the guard has no dependency on a git binary
# or on being run from inside a work tree.
REPO_ROOT = Path(__file__).resolve().parent.parent


def declared_ruff_floor() -> tuple[int, ...]:
    """The minimum ruff version this project declares, read from pyproject.toml.

    Read rather than hardcoded: the floor moves every time Dependabot bumps the
    dev group, and a constant duplicated here would silently drift below it —
    reintroducing exactly the vacuous-pass hole this function exists to close.
    """
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    for spec in data["dependency-groups"]["dev"]:
        match = re.fullmatch(r"ruff\s*>=\s*([0-9]+(?:\.[0-9]+)*)", spec.strip())
        if match:
            return tuple(int(part) for part in match.group(1).split("."))
    raise RuntimeError(
        "No `ruff>=X.Y.Z` entry found in [dependency-groups].dev of pyproject.toml. "
        "This guard reads the floor from there; if the spec's shape changed, update "
        "declared_ruff_floor() to match."
    )


def installed_ruff_version(binary: Path) -> tuple[int, ...]:
    """The version of a given ruff binary, as a comparable tuple."""
    out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"`{binary} --version` failed: {out.stderr.strip()}")
    match = re.search(r"([0-9]+(?:\.[0-9]+)+)", out.stdout)
    if not match:
        raise RuntimeError(f"Could not parse a version out of `{binary} --version`: {out.stdout!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def ruff_binary() -> Path:
    """The ruff this project pins, not whichever ruff happens to be reachable.

    Project venv first, interpreter-adjacent second. A missing binary is an
    error, never a skip, and a binary older than the declared floor is an error
    too: a guard that quietly stops running is worse than no guard, because the
    green tick keeps arriving.
    """
    candidates = (REPO_ROOT / ".venv" / "bin" / "ruff", Path(sys.executable).parent / "ruff")
    binary = next((candidate for candidate in candidates if candidate.exists()), None)
    if binary is None:
        raise RuntimeError(
            "ruff not found at any of: "
            + ", ".join(str(candidate) for candidate in candidates)
            + ". It is a dev dependency of this project, so if pytest can run, ruff "
            "should be installed. Try `uv sync --group dev`."
        )

    floor = declared_ruff_floor()
    version = installed_ruff_version(binary)
    if version < floor:
        raise RuntimeError(
            f"{binary} is ruff {'.'.join(map(str, version))}, below the "
            f"{'.'.join(map(str, floor))} floor pyproject.toml declares. This guard "
            "would still run, but against a formatter whose file discovery is "
            "narrower than CI's — which is how it can pass while CI fails "
            "(sandy#159). Run the suite under the project environment: "
            "`uv run --frozen pytest`."
        )
    return binary


def test_whole_tree_passes_ruff_format_check():
    """Every file ruff formats is formatted -- the exact gate CI enforces.

    CI step: `uv run ruff format --check .` in `.github/workflows/ci.yml`.
    """
    result = subprocess.run(
        [str(ruff_binary()), "format", "--check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(
            "`ruff format --check .` fails, so CI's `Format check (ruff)` step will "
            "fail too and this branch cannot merge.\n\n"
            "Fix with `uv run ruff format .` -- but first check WHAT it wants to "
            "reformat. If it is Markdown or another non-source file type, the ruff "
            "version likely widened its file discovery again (this happened at "
            "0.16.0, sandy#159), and the right answer may be to extend "
            "`[tool.ruff.format] exclude` in pyproject.toml rather than to let the "
            "formatter rewrite prose.\n\n"
            f"--- ruff stdout ---\n{result.stdout}\n"
            f"--- ruff stderr ---\n{result.stderr}"
        )


def test_guard_rejects_a_ruff_older_than_the_declared_floor():
    """The version assertion is the half that makes a wrong binary loud.

    Without it the guard degrades silently: ruff 0.15.6 does not discover
    Markdown, so it reports a clean tree over the exact regression #159 is about.
    Pinned as a test because the failure it prevents looks like success.
    """
    floor = declared_ruff_floor()
    assert floor >= (0, 16, 0), (
        "The declared floor dropped below 0.16.0, where Markdown discovery landed. "
        "Below it this guard cannot see the file class it was written for."
    )
    assert installed_ruff_version(ruff_binary()) >= floor
