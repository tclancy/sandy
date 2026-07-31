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
  file is read — binaries are skipped by attempting to *decode* the head rather
  than by trusting an extension allowlist, because an allowlist is exactly how a
  guard ends up passing while an artifact sits in the tree.

  That decode replaced a plain "is there a NUL in the first 4KB?" sniff, which
  had two holes (sandy#165). Showboat's whole job is capturing arbitrary command
  stdout, so a doc quoting `git ls-files -z` carries NULs and was skipped as
  binary; and a doc saved as UTF-16 is half NUL bytes by construction. Both are
  text and both must be caught, so the classifier now asks "does this decode as
  mostly-readable text under any plausible encoding?" instead.

- Only **tracked** files are examined. Generating a showboat doc, pasting it
  into a PR, and deleting it is the intended workflow, so an untracked scratch
  file in the working directory must never block a commit.

A file that legitimately quotes the marker — documentation explaining this very
rule, including this module — goes in ALLOWED. The failure message says so,
because the message is this guard's entire UX for whoever trips it later.

These run inside the repo's existing pre-commit `pytest` hook, so the guard is
enforced at commit time and in CI without any new hook wiring.
"""

import io
import string
import subprocess
from pathlib import Path
from typing import IO, Protocol

import pytest

SHOWBOAT_MARKER = "<!-- showboat-id:"

# How much of a file's head is examined before deciding text-vs-binary. Also the
# read ceiling for a file that turns out to *be* binary: the sniff decides on
# this much and stops, so rejecting a large tracked asset costs one bounded read
# rather than the whole file.
NUL_SNIFF_BYTES = 4096

# Encodings a committed showboat document might plausibly be written in, tried
# in this order. UTF-16 is in the list because sandy#165 hole 2 is that half the
# bytes of ASCII-in-UTF-16 are NUL, which the old sniff read as "binary".
# `utf-16` (BOM'd) is not listed separately: its BOM decodes cleanly under
# whichever byte order matches, so the two explicit forms cover all three
# spellings.
TEXT_ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")

# Fraction of decoded characters that must look like text for the head to be
# accepted as that encoding.
MIN_TEXT_RATIO = 0.90

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


class Openable(Protocol):
    """The one capability `read_text_or_none` needs of a path.

    Narrower than Path on purpose: it lets a test substitute a double that
    records how much of the file was actually read, without the annotation
    lying about what is accepted.
    """

    def open(self, mode: str = "rb") -> IO[bytes]: ...


def head_text_ratio(head: bytes, encoding: str) -> float:
    """How textual `head` looks when read as `encoding`. 0.0–1.0.

    The single decode path used by classification, so a test can assert on the
    same bytes the guard judges. Asserting against a locally-written
    `head.decode(...)` instead would leave `errors=` unpinned — the first
    version of the margin test did exactly that, and the `replace` -> `ignore`
    mutation sailed through it.
    """
    return _text_ratio(
        # `errors="replace"`, never `"ignore"` — see the U+FFFD note below.
        head.decode(encoding, errors="replace"),
        ascii_only=encoding != "utf-8",
    )


def _text_ratio(decoded: str, *, ascii_only: bool) -> float:
    """Fraction of `decoded` that looks like human-readable text.

    `ascii_only` is the whole reason this takes a flag rather than being one
    function. Decoding arbitrary binary as UTF-16 yields mostly *printable*
    code points — CJK, Cyrillic, dingbats — so a permissive "is it printable?"
    test says yes to a PNG and the guard starts flagging assets. Real UTF-16
    documents in this repo are ASCII-dominant, so the UTF-16 passes demand ASCII
    and the UTF-8 pass stays permissive enough for accented and CJK prose.
    """
    if not decoded:
        return 1.0
    if ascii_only:
        textual = sum(1 for ch in decoded if ch in string.printable)
    else:
        # U+FFFD is what `errors="replace"` leaves behind for an undecodable
        # byte. Counting it as non-text is what makes binary fail this pass.
        # `errors="ignore"` would DELETE those bytes instead, leaving a short and
        # far more printable string: measured on assets/vintage-logo.png, the
        # ratio goes 0.40 -> 0.78 against a 0.90 floor, i.e. it does not flip the
        # verdict today but it burns four fifths of the safety margin. Pinned by
        # test_binary_stays_well_clear_of_the_text_floor.
        textual = sum(
            1 for ch in decoded if ch != "\ufffd" and (ch.isprintable() or ch in "\t\n\r")
        )
    return textual / len(decoded)


def detect_text_encoding(head: bytes) -> str | None:
    """The encoding that reads `head` as text, or None if it looks binary.

    Replaces the old `b"\0" in head` sniff, which was correct for genuine
    assets and wrong for two realistic documents (sandy#165): a showboat doc
    whose *captured output* contains a NUL, and any doc saved as UTF-16.
    """
    for encoding in TEXT_ENCODINGS:
        # No odd-length trim before the UTF-16 passes: it was here, and mutation
        # testing showed it inert. `errors="replace"` already turns a dangling
        # final byte into one U+FFFD, and one character cannot move a 4096-byte
        # head across MIN_TEXT_RATIO. Verified against a UTF-16 doc plus a stray
        # trailing byte — trimmed and untrimmed both classify `utf-16-le`. A
        # redundant guard is an untested guard, so it is gone rather than
        # decorative.
        if head_text_ratio(head, encoding) >= MIN_TEXT_RATIO:
            return encoding
    return None


def read_text_or_none(path: Openable) -> str | None:
    """Decoded contents, or None if the file is unreadable or binary.

    Binary detection is extension-blind, so a marker in a `.mdx`, `.html`, or
    suffixless file is still found.

    The classification reads NUL_SNIFF_BYTES and decides on that alone; a file
    that turns out to be binary costs exactly that one read. `read_bytes()`
    pulled an entire tracked binary into memory to reject it on its first 4KB
    (claude[bot] on PR #155) — for this repo's largest tracked asset that was a
    646KB read to look at 4KB.

    Text files then rewind and are read whole, in a single buffer. The bound is
    on the *decision*, not on the scan: concatenating the head with the tail
    instead would hold three copies at once and cost ~50% more peak memory than
    the version this replaced, on the 43 tracked files that exceed the window —
    a regression dressed as an optimization, and the reason for the `seek(0)`.
    """
    try:
        with path.open("rb") as handle:
            encoding = detect_text_encoding(handle.read(NUL_SNIFF_BYTES))
            if encoding is None:
                return None
            handle.seek(0)
            raw = handle.read()
    except OSError:
        return None
    return raw.decode(encoding, errors="ignore")


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


def test_find_skips_the_allowlist(tmp_path):
    """This module quotes the marker to document the rule; it is not an artifact.

    The binary half of this test moved to `test_a_genuine_binary_is_still_skipped`
    with a realistic payload. Its old fixture — `b"\\x89PNG\\x00\\x00"` glued to a
    printable marker — is 88% ASCII, i.e. a text file carrying a couple of NULs,
    which sandy#165 hole 1 says must now be CAUGHT. Asserting both here would
    have pinned the two requirements against each other.
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_repo_hygiene.py").write_text(f"{SHOWBOAT_MARKER} x -->")

    assert find_showboat_artifacts(tmp_path, ["tests/test_repo_hygiene.py"]) == []


class _CountingFile:
    """Stand-in for a path, recording how many of its bytes were actually read.

    Counts `read()` and `read_bytes()` only. `read_bytes` exists purely so that
    reverting `read_text_or_none` to the pre-#155 implementation fails on the
    byte count — the assertion under test — rather than on a missing attribute,
    which would be a pass/fail for the wrong reason.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.bytes_read = 0

    def open(self, mode: str = "rb") -> io.BytesIO:
        owner = self

        class _Reader(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                chunk = super().read(size)
                owner.bytes_read += len(chunk)
                return chunk

        return _Reader(self._data)

    def read_bytes(self) -> bytes:
        self.bytes_read += len(self._data)
        return self._data


def test_binary_rejection_reads_only_the_sniff_window():
    """A tracked binary is rejected on its head, not pulled fully into memory.

    Fails against `path.read_bytes()`, which reads everything before looking at
    the first 4KB — the note claude[bot] left on PR #155.

    Asserted as `==`, not `<=`: an implementation that read *nothing* and
    returned None unconditionally would satisfy `<=` while destroying the guard,
    so the loose form can pass for the wrong reason.
    """
    big_binary = _CountingFile(b"\x89PNG\x00\x00" + b"\xff" * (NUL_SNIFF_BYTES * 20))

    assert read_text_or_none(big_binary) is None
    assert big_binary.bytes_read == NUL_SNIFF_BYTES


def test_a_marker_past_the_sniff_window_is_still_found(tmp_path):
    """The bound is on the binary *decision*, not on the content scan.

    This does not describe showboat's current output — measured against showboat
    0.6.1, the id comment lands at byte 67 and stays there as the document grows.
    It pins the invariant instead: the scan is unbounded, so the guard does not
    quietly depend on where a generator chooses to put its marker. An
    "optimization" that matched only within NUL_SNIFF_BYTES would look correct
    against every artifact showboat writes today and fail on the first one with a
    long preamble.
    """
    artifact = tmp_path / "walkthrough.md"
    artifact.write_text("padding\n" * NUL_SNIFF_BYTES + f"{SHOWBOAT_MARKER} abc -->\n")
    assert artifact.stat().st_size > NUL_SNIFF_BYTES

    assert find_showboat_artifacts(tmp_path, ["walkthrough.md"]) == ["walkthrough.md"]


def test_a_showboat_doc_with_a_nul_in_its_head_is_caught(tmp_path):
    """sandy#165 hole 1: showboat captures arbitrary stdout, including NULs.

    `showboat exec ... "git ls-files -z"` embeds NUL bytes in the captured
    output. Under the old "any NUL in the first 4KB means binary" sniff, such a
    document was skipped outright — so the one generator whose entire job is
    capturing untrusted bytes could produce an artifact this guard could not see.
    """
    doc = tmp_path / "walkthrough.md"
    doc.write_bytes(
        b"# Issue 165 test run\n\n$ git ls-files -z\n"
        + b"tests/conftest.py\x00tests/test_repo_hygiene.py\x00\n\n"
        + f"{SHOWBOAT_MARKER} 9bd762ee -->\n".encode()
    )
    assert b"\x00" in doc.read_bytes()[:NUL_SNIFF_BYTES]

    assert find_showboat_artifacts(tmp_path, ["walkthrough.md"]) == ["walkthrough.md"]


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_a_utf16_showboat_doc_is_caught(tmp_path, encoding):
    """sandy#165 hole 2: every other byte of UTF-16 ASCII is NUL.

    Parametrised over the BOM'd form and both explicit byte orders, because
    `utf-16` writes a BOM and `utf-16-le` does not — a BOM-only detector would
    pass the first and miss the other two.
    """
    doc = tmp_path / "demo.md"
    doc.write_bytes(f"# Demo\n\n{SHOWBOAT_MARKER} abc -->\n".encode(encoding))

    assert find_showboat_artifacts(tmp_path, ["demo.md"]) == ["demo.md"]


def test_a_genuine_binary_is_still_skipped(tmp_path):
    """DoD 3: real assets stay out of the scan.

    The payload is high-entropy rather than the handful of ASCII bytes the
    previous fixture used, because a few binary bytes wrapped around a printable
    string is not a binary — it is a text file with NULs, which is exactly what
    hole 1 above says must now be caught. Keeping the old fixture would have
    forced the two requirements into contradiction.
    """
    logo = tmp_path / "logo.png"
    logo.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + bytes((i * 7 + 11) % 256 for i in range(NUL_SNIFF_BYTES * 2))
        + f"{SHOWBOAT_MARKER} x -->".encode()
    )

    assert find_showboat_artifacts(tmp_path, ["logo.png"]) == []


def test_the_real_tracked_binaries_are_still_classified_binary():
    """DoD 3, against the actual tree rather than a fixture.

    A synthetic PNG proves the heuristic answers correctly on bytes I chose.
    This proves it on the bytes the repo actually has, which is the claim the
    definition of done makes.
    """
    root = repo_root()
    binaries = [
        rel
        for rel in tracked_files(root)
        if (root / rel).is_file() and b"\x00" in (root / rel).read_bytes()[:NUL_SNIFF_BYTES]
    ]
    assert binaries, "expected at least one tracked binary (assets/vintage-logo.png)"

    assert [rel for rel in binaries if read_text_or_none(root / rel) is not None] == []


def test_binary_stays_well_clear_of_the_text_floor():
    """The binary verdict must hold with margin, not by a hair.

    `detect_text_encoding` returning None is a boolean, and a boolean cannot
    distinguish "comfortably binary" from "one tweak away from being read as
    text". Switching `errors="replace"` to `errors="ignore"` takes this repo's
    only tracked binary from 0.40 to 0.78 against a 0.90 floor — still the right
    answer, so every boolean assertion in this module stays green, while four
    fifths of the margin is gone. That mutation survived the first pass of this
    suite; this is the assertion that kills it.
    """
    root = repo_root()
    logo = root / "assets" / "vintage-logo.png"
    assert logo.is_file(), "expected assets/vintage-logo.png to be tracked"

    with logo.open("rb") as handle:
        head = handle.read(NUL_SNIFF_BYTES)
    ratio = head_text_ratio(head, "utf-8")

    assert ratio < MIN_TEXT_RATIO / 2, (
        f"binary head scored {ratio:.2f} against a {MIN_TEXT_RATIO} floor — the "
        "margin has narrowed, which usually means the decoder now discards "
        "undecodable bytes instead of replacing them"
    )


def test_international_text_is_not_mistaken_for_binary(tmp_path):
    """The ratio heuristic must not reject legitimate non-ASCII prose."""
    doc = tmp_path / "notes.md"
    doc.write_text("# Notas\n\nCafé, naïve, 日本語のテキスト, emoji 🎉\n" * 40)

    assert read_text_or_none(doc) is not None


def test_unreadable_paths_are_skipped_not_fatal(tmp_path):
    """A tracked-but-absent path (a stale index entry) must not abort the scan."""
    (tmp_path / "demo.md").write_text(f"{SHOWBOAT_MARKER} abc -->\n")

    assert find_showboat_artifacts(tmp_path, ["gone.md", "demo.md"]) == ["demo.md"]


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
