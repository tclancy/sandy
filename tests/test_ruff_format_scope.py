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
  (verified in astral-sh/ruff-pre-commit's `.pre-commit-hooks.yaml` at v0.16.0),
  so **pre-commit never passes it a `.md` file at any version**. It is not a
  stale-pin problem; the hook is structurally blind to the class of file that
  broke.
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
"""

import subprocess
import sys
from pathlib import Path

import pytest


def repo_root() -> Path:
    """Absolute path to the git repo containing this test file."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {out.stderr.strip()}")
    return Path(out.stdout.strip())


def ruff_binary() -> Path:
    """The ruff shipped in the environment running these tests.

    Resolved next to the running interpreter rather than off PATH so the version
    checked here is the one pinned in `uv.lock` -- the same one CI installs. A
    PATH lookup could silently pick up a system-wide ruff of a different version,
    which is the whole failure mode this module exists to close.

    A missing binary is an error, never a skip: a guard that quietly stops running
    is worse than no guard, because the green tick keeps arriving.
    """
    candidate = Path(sys.executable).parent / "ruff"
    if not candidate.exists():
        raise RuntimeError(
            f"ruff not found at {candidate}. It is a dev dependency of this project "
            "(pyproject.toml [dependency-groups] dev), so if pytest can run, ruff "
            "should be installed. Try `uv sync --group dev`."
        )
    return candidate


def test_whole_tree_passes_ruff_format_check():
    """Every file ruff formats is formatted -- the exact gate CI enforces.

    CI step: `uv run ruff format --check .` in `.github/workflows/ci.yml`.
    """
    root = repo_root()
    result = subprocess.run(
        [str(ruff_binary()), "format", "--check", "."],
        cwd=root,
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
