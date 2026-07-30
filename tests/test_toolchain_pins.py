"""The linter pre-commit runs and the linter CI runs must be the same binary (#161).

`.pre-commit-config.yaml` pins `astral-sh/ruff-pre-commit` at a `rev:`, and
pre-commit installs *that tag's* ruff into its own isolated environment. CI, by
contrast, runs `uv run ruff`, which is whatever `uv.lock` resolves. Nothing
connects the two, so they drift apart silently and the first symptom is a branch
where the hook passes and CI fails — the same "local says green, CI says red"
shape that cost a week on #159.

The drift is structural, not accidental: Dependabot treats `pip` and
`pre-commit` as separate ecosystems, so a ruff release always arrives as two
independent PRs. They cannot land atomically. This test is what makes the
window between them visible instead of silent.

It reads both pins with real parsers rather than regexing the raw text — a
hand-rolled matcher is how a version check ends up passing on a file it never
actually understood.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
LOCKFILE = REPO_ROOT / "uv.lock"
PYPROJECT = REPO_ROOT / "pyproject.toml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

RUFF_HOOK_REPO = "https://github.com/astral-sh/ruff-pre-commit"


def _hook_rev(repo_url: str) -> str:
    """The `rev:` pinned for *repo_url* in .pre-commit-config.yaml."""
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text())
    revs = [r["rev"] for r in config["repos"] if r.get("repo") == repo_url]
    assert len(revs) == 1, f"expected exactly one {repo_url} block, found {len(revs)}"
    return revs[0]


def _locked_version(package: str) -> str:
    """The version `uv.lock` resolves *package* to — what CI actually installs."""
    lock = tomllib.loads(LOCKFILE.read_text())
    versions = [p["version"] for p in lock["package"] if p["name"] == package]
    assert len(versions) == 1, f"expected exactly one {package} in uv.lock, found {len(versions)}"
    return versions[0]


def test_ruff_pre_commit_rev_matches_the_locked_ruff() -> None:
    """The hook's tag and the lockfile's version must name the same release.

    `ruff-pre-commit` tags mirror ruff's own versions with a `v` prefix, so the
    comparison is exact rather than a floor check — a hook one patch behind is
    still a different linter, and ruff has shipped behaviour changes in patch
    releases (0.16.0 taught the *formatter* to read Markdown, which is what
    broke this repo's `main` on 07-28).
    """
    rev = _hook_rev(RUFF_HOOK_REPO)
    assert rev.startswith("v"), f"unexpected tag shape {rev!r} — expected a leading 'v'"
    assert rev[1:] == _locked_version("ruff"), (
        f"pre-commit runs ruff {rev[1:]} but uv.lock installs {_locked_version('ruff')}; "
        "bump .pre-commit-config.yaml's rev (or the lock) so local and CI lint alike"
    )


def test_locked_ruff_satisfies_the_declared_floor() -> None:
    """`uv.lock` can only be trusted as the CI version if it honours pyproject.

    Guards the third way these can disagree: someone raises the `ruff>=X` floor
    in pyproject without re-locking, so the lockfile — and therefore CI, and
    therefore this file's other assertion — is pinned below what the project
    says it needs.
    """
    project = tomllib.loads(PYPROJECT.read_text())
    dev_deps = project["dependency-groups"]["dev"]
    spec = next(d for d in dev_deps if d.replace("-", "_").startswith("ruff"))
    floor = re.search(r">=\s*([0-9][0-9a-zA-Z.]*)", spec)
    assert floor, f"no >= floor in {spec!r} — this test assumes one is declared"

    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(n) for n in v.split(".") if n.isdigit())

    assert parts(_locked_version("ruff")) >= parts(floor.group(1)), (
        f"uv.lock pins ruff {_locked_version('ruff')} below pyproject's floor {floor.group(1)}"
    )


@pytest.mark.parametrize("ecosystem", ["pip", "pre-commit"])
def test_dependabot_watches_both_places_ruff_is_pinned(ecosystem: str) -> None:
    """A pin Dependabot cannot see is a pin that only moves when someone notices.

    `pip` covers pyproject/uv.lock; `pre-commit` covers the hook rev. With only
    the first configured — the state this repo was in — ruff advanced in the dev
    group every few weeks while the hook sat on one tag indefinitely, and the
    gap widened without ever announcing itself.
    """
    config = yaml.safe_load(DEPENDABOT.read_text())
    configured = {u["package-ecosystem"] for u in config["updates"]}
    assert ecosystem in configured, (
        f"dependabot.yml does not watch the {ecosystem!r} ecosystem; "
        f"configured: {sorted(configured)}"
    )
