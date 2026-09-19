"""The suite never reads the machine's own config file.

`conftest._isolate_config` is what makes that true, and it is autouse — so it
guards every test written from now on without anyone remembering it. These
tests guard the guard.

The property is an *absence* ("no config was discovered"), and an absence
assertion passes just as happily when the thing it names was never reachable
in the first place. So the pin test below is paired with a control that
removes the pin and confirms the very same file **is** found. Without that
pair, a typo in the filename, a `tmp_path` that never got written, or a
`chdir` that silently failed would all read as a clean pass.
"""

import os
from pathlib import Path

import pytest

import sandy.config as config_module
from sandy.config import load_config

CONFIG_WITH_A_SECRET = 'SENTINEL_TOKEN = "xoxb-not-a-real-token"\n'


def _plant_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a config file and make *tmp_path* the working directory.

    `_SEARCH_PATHS` holds `Path("sandy.toml")` unresolved, so discovery is
    relative to the process working directory. Planting the file and moving
    into the directory is therefore the whole of what it takes to be found.
    """
    config = tmp_path / "sandy.toml"
    config.write_text(CONFIG_WITH_A_SECRET)
    monkeypatch.chdir(tmp_path)
    return config


def test_a_config_file_in_the_working_directory_is_not_discovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the autouse pin in force, a real config file is invisible."""
    _plant_config(tmp_path, monkeypatch)

    assert config_module.find_config_path() is None
    assert load_config() == {}


def test_the_same_file_is_discovered_once_the_pin_is_lifted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reachability control: prove the absence above is caused by the pin.

    `monkeypatch` is function-scoped, so the autouse fixture and this test
    share one instance — `undo()` therefore drops the fixture's `setattr` and
    restores the real `_SEARCH_PATHS`. That is asserted rather than assumed: if
    it ever stops being true, the assertion names the reason instead of leaving
    a bare `None == Path(...)` for someone to diagnose.

    (`undo()` also restores the `GIT_*` variables `_scrub_git_env` removed.
    Harmless here — nothing in this module shells out to git.)
    """
    monkeypatch.undo()
    assert config_module._SEARCH_PATHS, "undo() did not lift the autouse pin"
    planted = _plant_config(tmp_path, monkeypatch)

    # Drop the absolute entry. `_SEARCH_PATHS[0]` is `~/.config/sandy/sandy.toml`,
    # which `sandy.toml.example` calls the *recommended* location — so on a
    # machine that followed the project's own setup instructions it exists, wins
    # the search ahead of the relative entry, and reds this test. Depending on a
    # developer's home directory being empty is the machine-dependence this
    # module exists to remove; `chdir` already isolates the relative entry.
    monkeypatch.setattr(
        config_module,
        "_SEARCH_PATHS",
        [p for p in config_module._SEARCH_PATHS if not p.is_absolute()],
    )

    assert config_module.find_config_path() == Path("sandy.toml")
    assert load_config() == {"SENTINEL_TOKEN": "xoxb-not-a-real-token"}
    assert planted.exists()


def test_uppercase_keys_from_an_ambient_config_never_reach_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harm the pin exists to prevent, asserted at the point it would land.

    `find_config_path` returning None is the mechanism; a credential sitting in
    `os.environ` for the rest of the run is the damage. Assert the damage too,
    via the production call path (`load_config` then `apply_env`) rather than
    by re-implementing it.

    `apply_env` writes to `os.environ` unconditionally, so this test would
    *perform* the leak it guards against on the day the pin breaks — a failure
    that then cascades into every test after it. Swapping in a copy keeps the
    blast radius inside this function while still exercising the real call.
    """
    monkeypatch.setattr(os, "environ", dict(os.environ))
    _plant_config(tmp_path, monkeypatch)

    config_module.apply_env(load_config())

    assert "SENTINEL_TOKEN" not in os.environ
