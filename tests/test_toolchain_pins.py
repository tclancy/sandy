"""There must be exactly one ruff pin in this repo, and it must be `uv.lock` (#166).

The linter pre-commit runs and the linter CI runs have to be the same binary, or
a branch reaches the "hook passes, CI fails" state that cost a week on #159.
#161 achieved that by pinning `astral-sh/ruff-pre-commit`'s `rev:` to the locked
ruff and adding a test that the two agree — which *managed* the duplication
rather than removing it, and the management had a recurring cost:

- `pip` and `pre-commit` are separate Dependabot ecosystems, so a ruff release
  always arrives as two independent PRs that cannot land atomically. The
  agreement test therefore went red on each PR individually, roughly weekly.
- CI's `uv sync --group dev` carried no `--locked`, so it re-resolved and
  rewrote `uv.lock` in the workspace before the test read it — meaning the
  weekly red could fire even when both files on disk were correct.

So this file no longer asserts that two pins agree. It asserts there is only
one: the ruff hooks are `local` and shell out to the project's own ruff, and CI
installs from the committed lockfile rather than re-resolving. Skew stops being
*detected* and starts being *impossible*.

Both halves matter. A local hook alone would be nominal — without `--locked`, CI
can still install a ruff that is not in `uv.lock`, and the hook's guarantee that
"local and CI run the same binary" would be a claim about a file nobody honours.

Everything here reads the real files with real parsers (`yaml`, `tomllib`,
`shlex`) rather than regexing raw text. A hand-rolled matcher is how a version
check ends up passing on a file it never actually understood — the trap #161's
own review found in an earlier draft of this module.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import pytest
import yaml

from tests.test_ruff_format_scope import declared_ruff_floor


REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
LOCKFILE = REPO_ROOT / "uv.lock"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Matched as a substring of the repo URL, not compared for equality: pre-commit
# accepts `…/ruff-pre-commit`, `….git` and the `git@github.com:` form alike, and
# an equality check goes green on any of the spellings it does not happen to
# name. Cheap to widen, and the string is distinctive enough not to false-fire.
RUFF_HOOK_REPO_MARKER = "ruff-pre-commit"
RUFF_HOOK_IDS = ("ruff", "ruff-format")

# The ecosystem that moves ruff. Deliberately NOT "pip": measured over this
# repo's own history, every one of the 15 `python-deps` commits bumped a floor
# in pyproject.toml and left uv.lock untouched, which is fatal once CI installs
# with --locked. See the comment in .github/dependabot.yml.
PYTHON_ECOSYSTEM = "uv"


def _pre_commit_config() -> dict:
    return yaml.safe_load(PRE_COMMIT_CONFIG.read_text())


def _local_hooks() -> dict[str, dict]:
    """Every hook declared under the `local` repo, keyed by id."""
    hooks: dict[str, dict] = {}
    for repo in _pre_commit_config()["repos"]:
        if repo.get("repo") == "local":
            hooks.update({hook["id"]: hook for hook in repo["hooks"]})
    return hooks


def _third_party_hook_repos() -> set[str]:
    """Pinned hook repos pre-commit clones — i.e. everything that isn't `local`."""
    return {r["repo"] for r in _pre_commit_config()["repos"] if r.get("repo") != "local"}


def _locked_version(package: str) -> str:
    """The version `uv.lock` resolves *package* to — what CI actually installs."""
    lock = tomllib.loads(LOCKFILE.read_text())
    versions = [p["version"] for p in lock["package"] if p["name"] == package]
    assert len(versions) == 1, f"expected exactly one {package} in uv.lock, found {len(versions)}"
    return versions[0]


def _shell_statements(script: str) -> list[list[str]]:
    """Split a workflow `run:` script into tokenised shell statements.

    Deliberately more forgiving than one `shlex.split` per line, because review
    found three ways the simple version was wrong and one that was worse than
    wrong:

    - A backslash continuation inside a `run: |` block — idiomatic Actions —
      made `shlex` *raise* `ValueError: No escaped character`, turning this
      module into an error with a message pointing at nothing.
    - So did any unbalanced quote anywhere in an unrelated step. A step as
      innocent as `echo don't forget to relock` broke the ruff-pin test.
    - `cd build && uv sync`, `UV_NO_CACHE=1 uv sync` and `set -e; uv sync` were
      all invisible, so an unlocked sync in any of those shapes passed.

    So: join continuations, split on the separators that start a new command,
    tokenise with a whitespace fallback when `shlex` cannot, and drop leading
    `VAR=value` assignments. A statement we cannot parse is still returned as
    tokens — never silently skipped, since skipping is what makes a guard green.
    """
    script = script.replace("\\\n", " ")
    statements: list[list[str]] = []
    for line in script.splitlines():
        for chunk in re.split(r"&&|\|\||[;|\n]", line):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                argv = shlex.split(chunk)
            except ValueError:
                argv = chunk.split()
            while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
                argv = argv[1:]
            if argv:
                statements.append(argv)
    return statements


def _uv_sync_commands() -> list[list[str]]:
    """Every `uv sync ...` invocation across ALL workflow files, as argv lists.

    Scans the whole `.github/workflows/` directory rather than `ci.yml` alone —
    a second workflow that installs dependencies is exactly as able to install
    an unlocked ruff, and this repo already has more than one workflow file.
    Parsed from real YAML so a commented-out step cannot satisfy the guard.
    """
    commands = []
    for path in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text())
        for job in (workflow or {}).get("jobs", {}).values():
            for step in job.get("steps", []) or []:
                if not step.get("run"):
                    continue
                for argv in _shell_statements(step["run"]):
                    if argv[:2] == ["uv", "sync"]:
                        commands.append(argv)
    return commands


def test_the_third_party_ruff_hook_is_gone() -> None:
    """The duplicate pin is removed, not merely kept in agreement.

    This is the assertion that makes skew structurally impossible: with no
    `ruff-pre-commit` block there is no second version of ruff anywhere in the
    repo for the lockfile to drift away from. If this block ever comes back,
    the weekly two-ecosystem Dependabot dance comes back with it (#166).
    """
    offenders = [r for r in _third_party_hook_repos() if RUFF_HOOK_REPO_MARKER in r]
    assert not offenders, (
        f"{offenders} is pinned in .pre-commit-config.yaml again. That is a "
        "second ruff version, independent of uv.lock, and it will drift (#166). "
        "Use the `local` hooks that shell out to `uv run --frozen ruff` instead."
    )


def test_ruff_hooks_shell_out_to_the_locked_ruff() -> None:
    """Both ruff hooks must resolve their binary through the committed lockfile.

    `--frozen` and not `--locked` is deliberate and the two are not synonyms: a
    bare `uv run` re-resolves against PyPI and rewrites the tracked `uv.lock` as
    a side effect, which pre-commit then fails as "files were modified by this
    hook". `--frozen` installs the committed lock silently, which is what a hook
    wants. `--locked` *exits non-zero* on a stale lock, which is what CI wants
    and what a pre-commit hook must not do — see the CI test below.

    The subcommand is asserted too, and that is not pedantry: review mutated the
    config so `id: ruff` ran the *formatter* and `id: ruff-format` ran the
    *linter*, and an assertion that stopped at the binary name stayed green
    while the repo did no linting at all on commit.

    `--force-exclude` and `types_or` are checked because this swap made them
    local declarations. Upstream's hook definition carried both and they could
    not be lost; now they are lines in our own file, and dropping
    `--force-exclude` re-arms #159 — pre-commit names files explicitly, and ruff
    treats an explicit path as an override of its exclude rules without it.
    """
    hooks = _local_hooks()
    subcommands = {"ruff": "check", "ruff-format": "format"}
    for hook_id in RUFF_HOOK_IDS:
        assert hook_id in hooks, (
            f"no `local` hook with id {hook_id!r} in .pre-commit-config.yaml; "
            "the ruff hooks must run the project's own ruff (#166)"
        )
        entry = shlex.split(hooks[hook_id]["entry"])
        assert entry[:4] == ["uv", "run", "--frozen", "ruff"], (
            f"hook {hook_id!r} has entry {hooks[hook_id]['entry']!r}; expected it to "
            "start with `uv run --frozen ruff` so the linter comes from uv.lock. "
            "A bare `uv run` re-resolves and rewrites the tracked lock, which "
            "pre-commit rejects as a modified file."
        )
        assert entry[4:5] == [subcommands[hook_id]], (
            f"hook {hook_id!r} runs `ruff {' '.join(entry[4:5]) or '(nothing)'}`, "
            f"expected `ruff {subcommands[hook_id]}`. Swapping these two leaves "
            "every hook present and the repo linting nothing."
        )
        assert "--force-exclude" in entry, (
            f"hook {hook_id!r} dropped --force-exclude. pre-commit names files "
            "explicitly, and ruff treats an explicit path as an override of its "
            "exclude rules — so without this the hook rewrites the Markdown that "
            "`[tool.ruff.format] exclude` protects (#159)."
        )
        assert hooks[hook_id].get("types_or") == ["python", "pyi", "jupyter"], (
            f"hook {hook_id!r} must declare types_or: [python, pyi, jupyter], the "
            "file set astral-sh/ruff-pre-commit declared at v0.16.0. Omitting it "
            "hands the hook every changed file in the repo."
        )
        assert hooks[hook_id]["language"] == "system", (
            f"hook {hook_id!r} must be `language: system` — it invokes the `uv` "
            "already on PATH rather than asking pre-commit to build an isolated env"
        )

    assert "--fix" in shlex.split(hooks["ruff"]["entry"]), (
        "the ruff check hook dropped --fix, which the replaced upstream hook "
        "declared as `args: [--fix]`. Not a correctness hole — the hook still "
        "fails on a lint error — but it is a behaviour change from the config "
        "this swap claims to be equivalent to, so make it deliberately."
    )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        # The shapes review proved the first draft could not see. Each one is a
        # real unlocked `uv sync` that has to be found, or the CI guard below is
        # green on a workflow that re-resolves the single pin.
        ("uv sync --group dev", True),
        ("cd subdir && uv sync --group docs", True),
        ("UV_NO_CACHE=1 uv sync --group docs", True),
        ("set -e; uv sync --group docs", True),
        ("uv sync \\\n  --group docs", True),
        ("uv sync --group a\nuv sync --group b", True),
        # ...and things that must NOT be mistaken for one.
        ("echo uv sync is not run here", False),
        ("uv run pytest", False),
        ("uv lock --check", False),
    ],
)
def test_shell_statement_parser_sees_every_uv_sync_shape(script: str, expected: bool) -> None:
    """The CI guard is only as good as the parser underneath it.

    A `run:` block is a shell script, not a command, and the obvious
    implementation (one `shlex.split` per line, match at argv[0]) misses four
    idiomatic shapes and *raises* on a fifth. A guard that cannot see the
    command it guards is worse than absent, because the green tick keeps
    arriving — so the parser gets its own tests rather than being trusted.
    """
    found = any(argv[:2] == ["uv", "sync"] for argv in _shell_statements(script))
    assert found is expected, f"parser returned {_shell_statements(script)} for {script!r}"


def test_shell_statement_parser_survives_an_unparseable_step() -> None:
    """An unbalanced quote anywhere in a workflow must not break this module.

    `shlex.split("echo don't")` raises `ValueError: No closing quotation`. In the
    first draft that turned an innocent, unrelated step into an ERROR in the
    ruff-pin test, with a message pointing at nothing. Falling back to a
    whitespace split keeps the guard running — and, critically, still finds a
    `uv sync` sitting in the same script.
    """
    statements = _shell_statements("echo don't forget\nuv sync --group dev")
    assert ["uv", "sync", "--group", "dev"] in statements


def test_ci_installs_from_the_committed_lock() -> None:
    """`--locked` is what makes the single-pin guarantee real rather than nominal.

    Without it CI's `uv sync` re-resolves against PyPI and can install a ruff
    that is not in `uv.lock` at all — so "the hook and CI run the same binary"
    would be true of the file and false of the machine. `--locked` fails the
    build on a stale lock instead of silently repairing it, which is correct for
    CI and wrong for a hook (see above).
    """
    commands = _uv_sync_commands()
    assert commands, (
        "no `uv sync` step found in .github/workflows/ci.yml — if CI stopped "
        "installing this way, this guard needs rewriting rather than deleting"
    )
    for argv in commands:
        assert "--locked" in argv, (
            f"CI step `{' '.join(argv)}` does not pass --locked, so it may install a "
            "ruff that is not in the committed uv.lock and the pre-commit hooks' "
            "single-source-of-truth guarantee stops holding (#166)"
        )


def test_locked_ruff_satisfies_the_declared_floor() -> None:
    """`uv.lock` can only be trusted as the one pin if it honours pyproject.

    Guards the remaining way these can disagree now that the hook rev is gone:
    someone raises the `ruff>=X` floor in pyproject without re-locking, so the
    lockfile — and therefore both CI and the hooks — sits below what the project
    says it needs.

    Reuses `declared_ruff_floor()` rather than parsing the spec again. A second
    parser here was anchored on `startswith("ruff")`, which would silently pick
    a `ruff-lsp>=…` floor and compare ruff against a different package; the
    existing helper's `re.fullmatch` cannot. Two parsers for one field is how a
    check ends up passing against something it never actually read.
    """
    floor = declared_ruff_floor()
    locked = tuple(int(n) for n in _locked_version("ruff").split(".") if n.isdigit())
    assert locked >= floor, (
        f"uv.lock pins ruff {'.'.join(map(str, locked))} below pyproject's "
        f"floor {'.'.join(map(str, floor))}"
    )


def test_dependabot_moves_the_single_pin_lockfile_and_all() -> None:
    """The ecosystem watching Python deps must be one that updates `uv.lock`.

    This is the assertion that makes `--locked` in CI survivable, and it is
    specifically NOT satisfied by `pip`. Dependabot's pip ecosystem bumps the
    floor in `pyproject.toml` and never touches the lockfile — measured over
    this repo's own history, all 15 `python-deps` commits have a one-file diff.
    While CI re-resolved at run time that merely meant "the linter CI ran was
    not the linter anyone tested with"; with `--locked` it becomes a hard
    failure at the install step of every weekly Dependabot PR, before lint or
    tests ever run. `uv.lock` records the *specifier*, so even a bump the pinned
    version already satisfies invalidates it.

    The `uv` ecosystem updates `pyproject.toml` and `uv.lock` together, so the
    single pin moves on its own. Confirmed in the fleet rather than assumed:
    canvasoptimizer has six Dependabot commits touching both files.
    """
    configured = {u["package-ecosystem"] for u in yaml.safe_load(DEPENDABOT.read_text())["updates"]}
    assert PYTHON_ECOSYSTEM in configured, (
        f"dependabot.yml does not watch the {PYTHON_ECOSYSTEM!r} ecosystem; "
        f"configured: {sorted(configured)}. uv.lock is the single ruff pin (#166) "
        "and CI installs it with --locked, so the ecosystem that moves it has to "
        "update the lockfile too."
    )
    assert "pip" not in configured, (
        "dependabot.yml watches the 'pip' ecosystem, which bumps pyproject.toml "
        "without re-locking. Alongside CI's `uv sync --locked` that hard-fails "
        "every Dependabot PR at the install step. Use 'uv' instead (#166)."
    )


def test_dependabot_watches_every_hook_repo_that_is_still_pinned() -> None:
    """A pin Dependabot cannot see is a pin that only moves when someone notices.

    Derived rather than hardcoded, because the reason for the `pre-commit`
    ecosystem changed under this ticket: it was added for ruff (#161) and ruff
    no longer lives there. It is still needed for whatever third-party hook
    repos remain — `pre-commit-hooks` today. If the last one is ever removed the
    requirement lapses on its own, and if a new one is added it is covered
    without anyone remembering to edit this test.
    """
    remaining = _third_party_hook_repos()
    if not remaining:
        return
    configured = {u["package-ecosystem"] for u in yaml.safe_load(DEPENDABOT.read_text())["updates"]}
    assert "pre-commit" in configured, (
        f".pre-commit-config.yaml still pins {sorted(remaining)} at a rev, but "
        f"dependabot.yml does not watch the 'pre-commit' ecosystem; "
        f"configured: {sorted(configured)}"
    )
