"""Repo hygiene guards — things that must never be committed to this tree.

Showboat artifacts are the live case (sandy#154). The Dispatch operating rules
(`agent.md`, in the metaframework repo — see tclancy/metaframework#289) require
test-run evidence to be inlined in the **pull request body**; a copy committed
to the repo goes stale the moment the suite grows and then quietly misinforms
whoever opens it. `test-run.md` sat at the repo root for seven weeks claiming
"14 passed" against a suite of 566, and was named in three consecutive Daily
Briefings before anyone removed it. That is why this guard exists instead of a
one-off deletion.

Two scoping decisions worth knowing:

- The check keys on **content, not filename**. `test-run.md` was one arbitrary
  name; the next stray is as likely to be `demo.md` or `walkthrough.mdx`.
  Showboat stamps every document it generates with an HTML-comment id, so the
  marker identifies the artifact under any name or extension. Every tracked
  file is read — binaries are skipped by sniffing for a NUL byte rather than by
  trusting an extension allowlist, because an allowlist is exactly how a guard
  ends up passing while an artifact sits in the tree.

- Only **tracked** files are examined. Generating a showboat doc, pasting it
  into a PR, and deleting it is the intended workflow, so an untracked scratch
  file in the working directory must never block a commit.

A file that legitimately quotes the marker — documentation explaining this very
rule, including this module — goes in ALLOWED. The failure message says so,
because the message is this guard's entire UX for whoever trips it later.

These run inside the repo's existing pre-commit `pytest` hook, so the guard is
enforced at commit time and in CI without any new hook wiring.
"""

import subprocess
from pathlib import Path

import pytest

SHOWBOAT_MARKER = "<!-- showboat-id:"

# Files allowed to contain the marker because describing the rule requires
# naming it. Repo-root-relative POSIX paths.
ALLOWED = frozenset({"tests/test_repo_hygiene.py"})

# The artifact that prompted sandy#154, pinned by name so a re-add is
# unmistakable even if it were somehow stripped of its marker.
HISTORICAL_STRAY = "test-run.md"


def _git(root: Path, *args: str) -> str:
    """Run a read-only git command, surfacing stderr if it fails."""
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {root}: {out.stderr.strip()}")
    return out.stdout


def repo_root() -> Path:
    """Absolute path to the git repo containing this test file."""
    return Path(_git(Path(__file__).parent, "rev-parse", "--show-toplevel").strip())


def tracked_files(root: Path) -> list[str]:
    """Repo-root-relative POSIX paths of every file git is tracking.

    Split on NUL: plain `ls-files` quotes non-ASCII paths, which would silently
    drop them from the scan.
    """
    return [p for p in _git(root, "ls-files", "-z").split("\0") if p]


def read_text_or_none(path: Path) -> str | None:
    """Decoded contents, or None if the file is unreadable or binary.

    Binary detection is a NUL sniff over the head of the file — extension-blind,
    so a marker in a `.mdx`, `.html`, or suffixless file is still found.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="ignore")


def is_showboat_document(text: str) -> bool:
    """True if this content is a generated showboat document."""
    return SHOWBOAT_MARKER in text


def find_showboat_artifacts(root: Path, paths: list[str]) -> list[str]:
    """Tracked paths that are committed showboat documents."""
    offenders = []
    for rel in paths:
        if rel in ALLOWED:
            continue
        text = read_text_or_none(root / rel)
        if text is not None and is_showboat_document(text):
            offenders.append(rel)
    return offenders


def _offender_message(offenders: list[str]) -> str:
    return (
        "Showboat test-run evidence is committed to the repo: "
        + ", ".join(offenders)
        + ". It belongs inline in the pull request body, not in the tree "
        "(tclancy/metaframework#289) — a committed copy goes stale as soon as "
        "the suite changes. Delete the file and paste the showboat doc into the "
        "PR description instead. If this file legitimately documents the rule "
        "rather than being an artifact, add its path to ALLOWED in "
        "tests/test_repo_hygiene.py."
    )


# ---------------------------------------------------------------------------
# detection (pure — no repo state)
# ---------------------------------------------------------------------------


def test_detects_a_showboat_document():
    doc = f"# Issue 119 test run\n\n{SHOWBOAT_MARKER} 9bd762ee -->\n"
    assert is_showboat_document(doc) is True


def test_ignores_ordinary_markdown():
    assert is_showboat_document("# README\n\nWe capture runs with showboat.\n") is False


def test_find_reports_the_offending_path(tmp_path):
    (tmp_path / "demo.md").write_text(f"{SHOWBOAT_MARKER} abc -->\n")
    (tmp_path / "README.md").write_text("# fine\n")

    assert find_showboat_artifacts(tmp_path, ["demo.md", "README.md"]) == ["demo.md"]


@pytest.mark.parametrize("name", ["walkthrough.mdx", "demo.html", "RUNBOOK"])
def test_find_is_not_fooled_by_the_extension(tmp_path, name):
    """An allowlist of 'text' suffixes is how a guard silently stops guarding."""
    (tmp_path / name).write_text(f"{SHOWBOAT_MARKER} abc -->\n")

    assert find_showboat_artifacts(tmp_path, [name]) == [name]


def test_find_skips_binaries_and_the_allowlist(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_repo_hygiene.py").write_text(f"{SHOWBOAT_MARKER} x -->")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00" + f"{SHOWBOAT_MARKER} x -->".encode())

    paths = ["tests/test_repo_hygiene.py", "logo.png"]
    assert find_showboat_artifacts(tmp_path, paths) == []


def test_message_names_the_escape_hatch():
    """Whoever trips this needs to know ALLOWED exists, or they delete a good doc."""
    message = _offender_message(["CONTRIBUTING.md"])

    assert "CONTRIBUTING.md" in message
    assert "ALLOWED" in message
    assert "metaframework#289" in message


# ---------------------------------------------------------------------------
# the guard itself
# ---------------------------------------------------------------------------


def test_no_showboat_artifact_is_tracked():
    root = repo_root()
    offenders = find_showboat_artifacts(root, tracked_files(root))

    assert offenders == [], _offender_message(offenders)


def test_the_historical_stray_stays_gone():
    """sandy#154's artifact, by name.

    Tracked-only, deliberately: an untracked local test-run.md is a normal step
    in the showboat workflow and must not block a commit.
    """
    assert HISTORICAL_STRAY not in tracked_files(repo_root()), (
        f"{HISTORICAL_STRAY} is tracked again. It is showboat evidence and "
        "belongs in the PR body (tclancy/metaframework#289), not the repo."
    )
