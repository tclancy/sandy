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

import shlex
import tomllib
from pathlib import Path

import yaml

from tests.test_ruff_format_scope import declared_ruff_floor


REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
LOCKFILE = REPO_ROOT / "uv.lock"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

RUFF_HOOK_REPO = "https://github.com/astral-sh/ruff-pre-commit"
RUFF_HOOK_IDS = ("ruff", "ruff-format")


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


def _uv_sync_commands() -> list[list[str]]:
    """Every `uv sync ...` invocation in the CI workflow, as argv lists.

    Parsed out of the workflow's real YAML and then through `shlex`, so a step
    that gains a flag or moves to another job is still seen. Reading the file as
    text and grepping for the literal string would pass on a commented-out step.
    """
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    commands = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if not run:
                continue
            for line in run.splitlines():
                argv = shlex.split(line)
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
    assert RUFF_HOOK_REPO not in _third_party_hook_repos(), (
        f"{RUFF_HOOK_REPO} is pinned in .pre-commit-config.yaml again. That is a "
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
    """
    hooks = _local_hooks()
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
        assert hooks[hook_id]["language"] == "system", (
            f"hook {hook_id!r} must be `language: system` — it invokes the `uv` "
            "already on PATH rather than asking pre-commit to build an isolated env"
        )


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


def test_dependabot_watches_the_pip_ecosystem() -> None:
    """ruff now lives in exactly one place Dependabot can watch, so it must.

    Under #161 this was half of a pair; with the hook rev gone, `pip`
    (pyproject + uv.lock) is the *only* thing that moves ruff, which makes this
    assertion more load-bearing than it was, not less.
    """
    configured = {u["package-ecosystem"] for u in yaml.safe_load(DEPENDABOT.read_text())["updates"]}
    assert "pip" in configured, (
        f"dependabot.yml does not watch the 'pip' ecosystem; configured: {sorted(configured)}. "
        "That is where ruff is pinned, so without it the single pin never moves."
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
