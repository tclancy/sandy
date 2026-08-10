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
import os
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
# accepted as that encoding. Nothing tracked lands near it — every text file in
# the tree scores 1.00 and the one binary scores 0.40 — so the boundary is
# pinned by test_the_text_ratio_boundary_is_where_it_claims rather than by any
# real file. Getting it wrong is no longer catastrophic in either direction:
# too low and a binary gets decoded, too high and a text file falls through to
# `scan_bytes_for_marker`, which finds the marker anyway.
MIN_TEXT_RATIO = 0.90

# The marker as raw bytes, for the binary fallback. UTF-32 is included even
# though nothing observed emits it: the check is two `in` tests against a
# 64KB window, so covering it costs nothing and its absence would be another
# silent miss.
MARKER_SPELLINGS = tuple(
    SHOWBOAT_MARKER.encode(codec)
    for codec in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
)

# Read size for the streaming fallback. Peak memory is one chunk plus the
# straddle overlap, not the file.
SCAN_CHUNK_BYTES = 64 * 1024

# Files allowed to contain the marker because describing the rule requires
# naming it. Repo-root-relative POSIX paths.
ALLOWED = frozenset({"tests/test_repo_hygiene.py"})

# The artifact that prompted sandy#154, pinned by name so a re-add is
# unmistakable even if it were somehow stripped of its marker.
HISTORICAL_STRAY = "test-run.md"


def git_env() -> dict[str, str]:
    """The ambient environment with every inherited `GIT_*` variable removed.

    `GIT_DIR` beats both `cwd=` and `-C`, and git exports it — along with
    `GIT_INDEX_FILE` — into the environment of every hook it runs. This suite
    runs from a hook: `.pre-commit-config.yaml` defines a `pytest-cov` hook with
    `always_run: true` (sandy#173).

    What each hook environment actually carries, measured on git 2.51.0 with a
    `pre-commit` hook that echoes its own environment:

    | commit made in | `GIT_DIR` | `GIT_INDEX_FILE` |
    |---|---|---|
    | plain checkout | *unset* | `.git/index` — **relative** |
    | linked worktree | `<repo>/.git/worktrees/<name>` | same, **absolute** |

    So the live trigger is the **worktree** commit, and `agent.md` mandates
    ephemeral worktrees for metaframework shift work while the fleet uses them
    routinely elsewhere. The plain-checkout row is benign, but not for the
    reason sandy#173 gives — it says `GIT_DIR` is "not set — looks safe", and
    `GIT_INDEX_FILE` *is* set there. It is harmless only because it is relative
    and `ls-files` runs with `cwd` at the repo root, where `.git/index`
    resolves to the real index. Move that call to a subdirectory and the plain
    checkout becomes a live case too. That is a thin margin to be standing on
    by accident, and scrubbing removes the dependence entirely.

    Measured on git 2.51.0, cwd `tests/`, pointed at a decoy repo. The two
    calls this module makes fail in **different directions**, and the two
    variables git exports are **not interchangeable** — which is why the whole
    `GIT_*` namespace goes rather than the one variable sandy#173 names:

    | inherited | `rev-parse --show-toplevel` | `ls-files -z` |
    |---|---|---|
    | *(nothing)* | the repo root | this repo's files |
    | `GIT_DIR` | **cwd** — `tests/`, not the decoy | **the decoy's files** |
    | `GIT_INDEX_FILE` | the repo root — *correct* | **empty** |

    Two corrections to the ticket fall out of that table. First, sandy#173
    describes both calls as answering "about the repository `GIT_DIR` names";
    that is true of `ls-files` and not of `rev-parse`, which degrades to cwd
    because with no `GIT_WORK_TREE` alongside it git takes the current
    directory as the work tree. Second, and worse: `GIT_INDEX_FILE` **on its
    own** — with no `GIT_DIR` at all — empties the file list while leaving the
    root correct. Nothing about that state looks wrong from the inside, and
    scrubbing only `GIT_DIR` would leave it live.

    Every route ends in the same false green. With a foreign file list,
    `find_showboat_artifacts` joins the decoy's *relative paths* onto the wrong
    root, every one misses, `OSError` is swallowed by design
    (`test_unreadable_paths_are_skipped_not_fatal`), and the sweep reports no
    offenders having read none of this repo's files. With an *empty* one it
    reports no offenders having read nothing at all. An empty result and a
    clean tree are the same output.

    Scrubbed **here**, in the helper that runs git, rather than only in
    `conftest.py`: a conftest scrub is undone by any test that sets `GIT_DIR`
    itself, which is exactly what the guards below do. See the caveat in
    `tests/conftest.py` — this is the half that makes the function correct
    rather than merely the suite quiet. Every command here reads local history
    only, so dropping the whole `GIT_*` namespace costs nothing.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root: Path, *args: str) -> str:
    """Run a read-only git command, surfacing stderr if it fails."""
    out = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=git_env()
    )
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

    "Stricter" is not true on every axis: `string.printable` contains `\\x0b` and
    `\\x0c`, which the UTF-8 branch rejects as non-printable. Harmless — nothing
    hinges on vertical tab — but the asymmetry is real, so do not read the
    ASCII branch as a subset of the other.
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

    Replaces the old `b"\\0" in head` sniff, which was correct for genuine
    assets and wrong for two realistic documents (sandy#165): a showboat doc
    whose *captured output* contains a NUL, and any doc saved as UTF-16.
    """
    for encoding in TEXT_ENCODINGS:
        # No odd-length trim before the UTF-16 passes: it was here, and mutation
        # testing showed it inert. `errors="replace"` already turns a dangling
        # final byte into one U+FFFD. On a *full* 4096-byte head one character
        # cannot cross MIN_TEXT_RATIO; on a very short head it can (an 8-char
        # UTF-16 doc plus a stray byte scores 0.889, a 9-char one 0.900), but a
        # real showboat doc carries the 17-character marker and clears it either
        # way. Verified trimmed and untrimmed on a UTF-16 doc plus a stray byte:
        # both classify `utf-16-le`. And since #165 a misclassified head is no
        # longer fatal — `scan_bytes_for_marker` still reads the file. A
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


def scan_bytes_for_marker(handle: IO[bytes]) -> bool:
    """True if the marker appears anywhere in `handle`, in any spelling.

    The fallback for a file the decoder called binary. Encoding detection
    decides *how to decode*, never *whether to look* — gating the marker search
    on decodability is a silent false negative, and this module exists to
    prevent exactly that.

    Streams in chunks with an overlap, so peak memory is one chunk regardless of
    file size. Total bytes read does grow to the file size for binaries, which
    is a deliberate trade against PR #155's read bound: #155 optimised the cost
    of rejecting an asset, and sandy#165 observes that a false positive here
    costs one line in ALLOWED while a false negative is invisible forever.
    """
    overlap = max(len(spelling) for spelling in MARKER_SPELLINGS) - 1
    tail = b""
    while chunk := handle.read(SCAN_CHUNK_BYTES):
        window = tail + chunk
        if any(spelling in window for spelling in MARKER_SPELLINGS):
            return True
        # Carry the boundary so a marker straddling two chunks is still found.
        tail = window[-overlap:]
    return False


def path_holds_marker(path: Openable) -> bool:
    """True if this file is a committed showboat document, by any route."""
    text = read_text_or_none(path)
    if text is not None:
        return is_showboat_document(text)
    try:
        with path.open("rb") as handle:
            return scan_bytes_for_marker(handle)
    except OSError:
        return False


def find_showboat_artifacts(root: Path, paths: list[str]) -> list[str]:
    """Tracked paths that are committed showboat documents."""
    offenders = []
    for rel in paths:
        if rel in ALLOWED:
            continue
        if path_holds_marker(root / rel):
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
    with a high-entropy payload. Its old fixture — `b"\\x89PNG\\x00\\x00"` glued to
    a printable marker — scores 0.8966, i.e. it sat 0.003 under the floor, so a
    one-character change to the marker id would have flipped it from binary to
    text and silently changed what this test asserted.

    An earlier revision of this docstring claimed the old fixture "must now be
    CAUGHT" and that keeping it would pin two requirements against each other.
    That was wrong and the code review caught it: the deleted assertion still
    passes against this implementation. The real reason to replace it is
    brittleness, which is a weaker claim and the true one.
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

    A genuine asset carries no marker in any spelling, so neither the decode
    path nor the byte-scan fallback has anything to find. That — not the
    binary classification on its own — is what keeps assets out of the report.
    """
    logo = tmp_path / "logo.png"
    logo.write_bytes(
        b"\x89PNG\r\n\x1a\n" + bytes((i * 7 + 11) % 256 for i in range(NUL_SNIFF_BYTES * 2))
    )

    assert find_showboat_artifacts(tmp_path, ["logo.png"]) == []


def test_a_binary_that_really_does_carry_the_marker_is_reported(tmp_path):
    """The deliberate false positive, pinned so nobody 'fixes' it later.

    sandy#165 weighs the two errors explicitly: a false positive costs one line
    in ALLOWED, a false negative is silent forever. So once a file contains the
    marker bytes, it is reported whatever its head looks like. This is the
    assertion the old `logo.png` fixture used to contradict.
    """
    odd = tmp_path / "weird.bin"
    odd.write_bytes(
        bytes((i * 31 + 7) % 256 for i in range(NUL_SNIFF_BYTES * 2))
        + f"{SHOWBOAT_MARKER} x -->".encode()
    )

    assert find_showboat_artifacts(tmp_path, ["weird.bin"]) == ["weird.bin"]


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


@pytest.mark.parametrize(
    "label,payload",
    [
        # Each of these was CAUGHT by the pre-#165 NUL sniff and MISSED by the
        # first version of the decode classifier, which returned None for an
        # undecodable head and never looked at the file. Found by code review:
        # the fix for two narrow false negatives had opened five broader ones.
        (
            "latin-1 prose, 11% accented",
            ("# Café\n" + "é" * 110 + "a" * 890).encode("latin-1") + MARKER_SPELLINGS[0],
        ),
        (
            "cp1251 prose",
            ("# Отчёт\n" + "Привет мир. " * 90).encode("cp1251") + MARKER_SPELLINGS[0],
        ),
        (
            "ANSI progress-bar capture",
            ("# run\n" + "\x1b[32m#\x1b[0m" * 400).encode() + MARKER_SPELLINGS[0],
        ),
        (
            "captured raw binary blob",
            b"# capture\n$ xxd thing\n" + bytes(range(256)) * 3 + MARKER_SPELLINGS[0],
        ),
        # The marker itself must be in the document's own encoding, or the case
        # is satisfied by the ASCII spelling and proves nothing about UTF-32 —
        # which is exactly how the first version of this test let a
        # "drop UTF-32" mutation survive.
        ("UTF-32-LE document", f"# Demo\n{SHOWBOAT_MARKER} abc -->\n".encode("utf-32-le")),
        ("UTF-32-BE document", f"# Demo\n{SHOWBOAT_MARKER} abc -->\n".encode("utf-32-be")),
    ],
)
def test_a_marker_is_found_whatever_the_head_looks_like(tmp_path, label, payload):
    """Encoding detection decides HOW to decode, never WHETHER to scan.

    Showboat captures arbitrary command stdout, so the content most likely to
    defeat a decoder is exactly the content this guard most needs to read.
    Gating the marker search on decodability makes the guard worse at its one
    job than the NUL sniff it replaced.
    """
    doc = tmp_path / "capture.md"
    doc.write_bytes(payload)

    assert find_showboat_artifacts(tmp_path, ["capture.md"]) == ["capture.md"]


def test_a_marker_straddling_two_scan_chunks_is_found(tmp_path):
    """The streaming fallback carries an overlap; without it this is a miss.

    Padding is sized so the marker begins one byte before the first chunk
    boundary, which is the only offset at which the bug appears — a scan written
    without the overlap passes every other test in this module.
    """
    doc = tmp_path / "big.bin"
    marker = f"{SHOWBOAT_MARKER} abc -->".encode()
    padding = bytes((i * 31 + 7) % 256 for i in range(SCAN_CHUNK_BYTES - 1))
    doc.write_bytes(padding + marker + b"\x00" * 10)
    assert read_text_or_none(doc) is None, "fixture must take the binary path"

    assert find_showboat_artifacts(tmp_path, ["big.bin"]) == ["big.bin"]


def test_the_scan_fallback_holds_one_chunk_not_the_file(tmp_path):
    """Peak memory, which is the property PR #155 actually argued for.

    Total bytes read does grow to the file size on the fallback path — that is
    the deliberate #165 trade. What must not regress is pulling a whole asset
    into memory at once.
    """
    doc = tmp_path / "big.bin"
    doc.write_bytes(bytes((i * 31 + 7) % 256 for i in range(SCAN_CHUNK_BYTES * 8)))
    peak = 0

    with doc.open("rb") as handle:
        original = handle.read

        def watched(size=-1):
            nonlocal peak
            chunk = original(size)
            peak = max(peak, len(chunk))
            return chunk

        handle.read = watched
        assert scan_bytes_for_marker(handle) is False

    assert peak <= SCAN_CHUNK_BYTES, f"read {peak} bytes at once, over the {SCAN_CHUNK_BYTES} chunk"


@pytest.mark.parametrize(
    "ratio,expected", [(0.95, "utf-8"), (0.91, "utf-8"), (0.89, None), (0.50, None)]
)
def test_the_text_ratio_boundary_is_where_it_claims(ratio, expected):
    """No tracked file sits near MIN_TEXT_RATIO, so nothing else pins it.

    Every text file in the tree scores 1.00 and the one binary scores 0.40, so
    the constant could be moved a long way in either direction with the rest of
    this suite still green.
    """
    total = 1000
    head = (b"a" * int(total * ratio)) + (b"\x81" * (total - int(total * ratio)))

    assert detect_text_encoding(head) == expected


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_a_utf16_document_decodes_rather_than_falling_through(tmp_path, encoding):
    """The decode layer must actually decode UTF-16, not lean on the backstop.

    `find_showboat_artifacts` would catch these anyway via
    `scan_bytes_for_marker`, so every *guard* assertion stays green if UTF-16 is
    dropped from TEXT_ENCODINGS — two mutations survived on exactly that. But
    `read_text_or_none`'s contract is "decoded contents", and a caller that got
    `None` (or UTF-8 mojibake) for a perfectly readable document would be wrong
    regardless of what the guard concludes. This is the assertion that makes the
    decode layer load-bearing instead of decorative.

    The two layers are deliberate: decoding is the fast, typical path and keeps
    PR #155's bounded rejection for ordinary assets; the byte scan is the
    backstop for everything a decoder cannot make sense of.
    """
    doc = tmp_path / "demo.md"
    doc.write_bytes(f"# Demo\n\n{SHOWBOAT_MARKER} abc -->\n".encode(encoding))

    text = read_text_or_none(doc)

    assert text is not None, "a readable UTF-16 document decoded to None"
    assert "# Demo" in text, f"decoded as mojibake: {text[:40]!r}"
    assert is_showboat_document(text)


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


def _make_decoy_repo(path: Path) -> None:
    """A throwaway repo standing in for the checkout a hook would hand us.

    Built with `env=git_env()` rather than the ambient environment, and never
    with a bare `git init` in an inherited one. An `init` that follows a stray
    `GIT_DIR` writes to the repository that variable names — in homelab#330 the
    identical fixture shape flipped `core.bare` on the real checkout (PR #337).
    The bug this module guards against is read-only; the fixture proving it
    need not be.
    """
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ("init", "--initial-branch=main"),
        ("config", "user.email", "decoy@example.com"),
        ("config", "user.name", "decoy"),
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, env=git_env())
    (path / "decoy-only-file.md").write_text("# not this repo\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True, env=git_env())
    subprocess.run(
        ["git", "commit", "-m", "decoy: the wrong repo"],
        cwd=path,
        check=True,
        capture_output=True,
        env=git_env(),
    )


def _point_git_at(decoy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Export the two variables git hands to a hook, as a hook would.

    Set *after* conftest's `_scrub_git_env` autouse fixture has run, so these
    tests exercise the redirect the scrub is there to absorb rather than being
    silently neutralised by it.
    """
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))


def test_git_dir_in_the_environment_cannot_redirect_the_root(tmp_path, monkeypatch):
    """sandy#173: `GIT_DIR` beats `cwd=`, and this suite runs from a git hook.

    Asserted on the **resolved root**, not on a downstream pass/fail, so it
    fails on a developer machine as much as on a runner. A downstream assertion
    would be satisfied by the redirect itself — the whole defect is that the
    sweep goes green while reading the wrong tree.

    Measured pre-fix on git 2.51.0: this returns `<repo>/tests`, i.e. the *cwd*
    `repo_root` passes, not the decoy's root — `--show-toplevel` takes the
    current directory as the work tree when `GIT_DIR` arrives without
    `GIT_WORK_TREE`. So the wrong answer is a plausible-looking path inside
    this repo, which is precisely why nothing noticed.
    """
    _make_decoy_repo(tmp_path / "decoy")
    _point_git_at(tmp_path / "decoy", monkeypatch)

    root = repo_root()

    assert (root / "sandy").is_dir() and (root / "pyproject.toml").is_file(), (
        f"repo_root() resolved to {root}, which is not this repo — an inherited "
        "GIT_DIR redirected it. tests/test_repo_hygiene.py:git_env must scrub GIT_*."
    )
    assert root == Path(__file__).resolve().parent.parent


def test_git_dir_in_the_environment_cannot_redirect_the_file_list(tmp_path, monkeypatch):
    """The other half, which fails in the opposite direction from the root.

    `ls-files` follows `GIT_DIR` all the way — unlike `rev-parse
    --show-toplevel`, it really does enumerate the decoy. Pinning only the root
    would leave this uncovered, and it is the call that decides *what gets
    scanned*: an empty or foreign file list is the same output as a clean tree.
    """
    _make_decoy_repo(tmp_path / "decoy")
    _point_git_at(tmp_path / "decoy", monkeypatch)

    tracked = tracked_files(repo_root())

    assert "decoy-only-file.md" not in tracked, (
        "tracked_files() enumerated the decoy repository — an inherited GIT_DIR "
        "redirected `git ls-files`."
    )
    assert "tests/test_repo_hygiene.py" in tracked, (
        "tracked_files() did not return this repo's own files; the sweep would "
        "pass having read nothing."
    )


def test_git_index_file_alone_cannot_empty_the_file_list(tmp_path, monkeypatch):
    """The row `GIT_DIR`-only scrubbing would leave live.

    Git exports `GIT_INDEX_FILE` beside `GIT_DIR`, and on its own it redirects
    `ls-files` to a foreign index while `rev-parse --show-toplevel` keeps
    returning the correct root. Measured: the file list comes back **empty**.

    That is the most dangerous shape this module has, because it is the one
    that looks healthiest — the root is right, no path is obviously foreign,
    and the sweep's green is indistinguishable from a genuinely clean tree.
    Pinned separately from the `GIT_DIR` guards so that narrowing the scrub to
    `GIT_DIR` fails here rather than silently.
    """
    _make_decoy_repo(tmp_path / "decoy")
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "decoy" / ".git" / "index"))

    root = repo_root()
    tracked = tracked_files(root)

    assert tracked, (
        "tracked_files() returned an empty list — an inherited GIT_INDEX_FILE "
        "redirected `git ls-files` to a foreign index. The sweep would report a "
        "clean tree having scanned nothing."
    )
    assert "tests/test_repo_hygiene.py" in tracked


def test_the_guard_still_reads_this_repo_under_a_redirect(tmp_path, monkeypatch):
    """End-to-end, and non-vacuously: the sweep must *find* the planted artifact.

    `offenders == []` is the guard's green, and it is also what a guard reading
    an empty file list returns — the two are indistinguishable from the outside.
    So this plants a marker in a tracked file's place and asserts it is
    reported: a redirected sweep cannot see it, and a working one must.
    """
    _make_decoy_repo(tmp_path / "decoy")
    _point_git_at(tmp_path / "decoy", monkeypatch)

    root = repo_root()
    tracked = tracked_files(root)
    planted = "tests/test_repo_hygiene.py"
    assert planted in tracked, "fixture assumes this module is tracked"

    offenders = find_showboat_artifacts(root, [p for p in tracked if p == planted])

    # This module is in ALLOWED, so a *working* sweep reports nothing for it —
    # assert on the file list reaching the scan instead, which is the step a
    # redirect actually breaks.
    assert offenders == []
    assert (root / planted).is_file(), (
        "the path handed to the scan does not exist on disk — the sweep was "
        "reading one repo's file names against another repo's tree."
    )


def test_the_conftest_scrub_is_registered_and_actually_scrubs(monkeypatch):
    """The safety net needs its own negative control, or it is decorative.

    Nothing else in this suite can fail if `_scrub_git_env` is deleted: the
    guards above set `GIT_DIR` themselves *after* it runs, and `git_env` scrubs
    independently. So the fixture's whole value is for code that does not exist
    yet, and it would rot silently.

    Asserting "no `GIT_*` in `os.environ` during a test" would be the obvious
    check and is worthless — on a developer machine nothing exports `GIT_DIR`
    in the first place, so it passes against a deleted fixture. The two things
    that can actually break are pinned instead: that it is still **autouse**
    (registration), and that it removes the variables when there are some to
    remove (behaviour).
    """
    from tests import conftest

    # pytest 8.4 wraps a fixture in `FixtureFunctionDefinition`; the decorator's
    # arguments live on `_fixture_function_marker` and the undecorated callable
    # on `_fixture_function`. Both are private, so this assertion is pinned to a
    # pytest internal on purpose — the alternative (asserting on os.environ) is
    # the vacuous check described above. If a pytest bump breaks these two
    # attributes, that is a loud failure telling you to re-point them, which is
    # the correct outcome for a guard whose subject is a fixture's registration.
    marker = conftest._scrub_git_env._fixture_function_marker
    assert marker.autouse is True, (
        "_scrub_git_env is no longer autouse — it now protects nothing, and "
        "every test that shells out to git is redirectable again."
    )

    monkeypatch.setenv("GIT_DIR", "/nonexistent/decoy/.git")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nonexistent/decoy/.git/index")
    inner = pytest.MonkeyPatch()
    try:
        conftest._scrub_git_env._fixture_function(inner)
        assert "GIT_DIR" not in os.environ
        assert "GIT_INDEX_FILE" not in os.environ
    finally:
        inner.undo()


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
