"""Repo hygiene guards — things that must never be committed to this tree.

Showboat artifacts are the live case (#154). agent.md's "Completing a task" step
requires test-run evidence to be inlined in the **PR body** (#289); a copy
committed to the repo goes stale the moment the suite grows and then quietly
misinforms whoever opens it. `test-run.md` sat at the repo root for seven weeks
and was named in three consecutive Daily Briefings before anyone removed it,
which is why this guard exists instead of a one-off deletion.

The check keys on **content, not filename**. `test-run.md` was one arbitrary
name; the next stray is just as likely to be `demo.md` or `artifact.md`.
Showboat stamps every document it generates with an HTML-comment id, so the
marker identifies the artifact wherever it lands and under whatever name.

These run inside the repo's existing pre-commit `pytest` hook, so the guard is
enforced at commit time without any new hook wiring.
"""

import subprocess
from pathlib import Path

import pytest

# Assembled from two pieces rather than written as one literal so that this
# guard file is not itself an instance of the thing it forbids.
SHOWBOAT_MARKER = "<!--" + " showboat-id:"

# Suffixes worth reading as text. Anything else (images, archives, fonts) can't
# carry the marker in a form that matters and may be large.
TEXT_SUFFIXES = frozenset(
    {".md", ".markdown", ".txt", ".rst", ".py", ".toml", ".yaml", ".yml", ".cfg", ".ini"}
)

# Files allowed to contain the marker because describing the rule requires
# naming it. Repo-root-relative POSIX paths.
ALLOWED = frozenset({"tests/test_repo_hygiene.py"})


def repo_root() -> Path:
    """Absolute path to the git repo containing this test file."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def tracked_files(root: Path) -> list[str]:
    """Repo-root-relative POSIX paths of every file git is tracking."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def is_showboat_document(text: str) -> bool:
    """True if this content is a generated showboat document."""
    return SHOWBOAT_MARKER in text


def find_showboat_artifacts(root: Path, paths: list[str]) -> list[str]:
    """Tracked paths that are committed showboat documents.

    Unreadable files are skipped rather than raised on: this guard's job is to
    catch a stray artifact, not to fail the suite over an odd encoding.
    """
    offenders = []
    for rel in paths:
        if rel in ALLOWED or Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if is_showboat_document(text):
            offenders.append(rel)
    return offenders


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


def test_find_skips_allowlisted_and_non_text(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_repo_hygiene.py").write_text(f"{SHOWBOAT_MARKER} x -->")
    (tmp_path / "logo.png").write_bytes(f"{SHOWBOAT_MARKER} x -->".encode())

    assert find_showboat_artifacts(tmp_path, ["tests/test_repo_hygiene.py", "logo.png"]) == []


# ---------------------------------------------------------------------------
# the guard itself
# ---------------------------------------------------------------------------


def test_no_showboat_artifact_is_tracked():
    root = repo_root()
    offenders = find_showboat_artifacts(root, tracked_files(root))

    assert offenders == [], (
        "Showboat test-run evidence is committed to the repo: "
        + ", ".join(offenders)
        + ". It belongs inline in the PR body, not in the tree (#289) — the "
        "committed copy goes stale as soon as the suite changes. Delete the "
        "file and paste the showboat doc into the pull request description."
    )


@pytest.mark.parametrize("name", ["test-run.md", "testrun.md"])
def test_the_historical_stray_stays_gone(name):
    """#154's specific artifact, pinned by name so a re-add is unmistakable."""
    assert not (repo_root() / name).exists()
