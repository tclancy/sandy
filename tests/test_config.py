"""Tests for sandy.config — TOML config loader."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sandy.config import apply_env, is_active, load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "sandy.toml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_returns_empty_when_no_file():
    with patch("sandy.config.find_config_path", return_value=None):
        assert load_config() == {}


def test_load_config_reads_toml(tmp_path):
    p = _write_toml(tmp_path, '[spotify]\nactive = "yes"\nSPOTIPY_CLIENT_ID = "abc"')
    config = load_config(p)
    assert config["spotify"]["active"] == "yes"
    assert config["spotify"]["SPOTIPY_CLIENT_ID"] == "abc"


def test_load_config_explicit_path(tmp_path):
    p = _write_toml(tmp_path, "GLOBAL_KEY = 42")
    config = load_config(p)
    assert config["GLOBAL_KEY"] == 42


# ---------------------------------------------------------------------------
# apply_env
# ---------------------------------------------------------------------------


def test_apply_env_sets_global_uppercase(monkeypatch):
    monkeypatch.delenv("MY_TOKEN", raising=False)
    apply_env({"MY_TOKEN": "secret", "lower_key": "ignored"})
    assert os.environ["MY_TOKEN"] == "secret"
    assert "lower_key" not in os.environ


def test_apply_env_sets_plugin_uppercase(monkeypatch):
    monkeypatch.delenv("PLUGIN_SECRET", raising=False)
    apply_env({"myplugin": {"PLUGIN_SECRET": "val", "active": "yes"}})
    assert os.environ["PLUGIN_SECRET"] == "val"
    assert "active" not in os.environ


def test_apply_env_does_not_override_existing(monkeypatch):
    monkeypatch.setenv("EXISTING_VAR", "original")
    apply_env({"EXISTING_VAR": "new"})
    assert os.environ["EXISTING_VAR"] == "original"


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("yes", True),
        ("Yes", True),
        ("YES", True),
        ("no", False),
        ("No", False),
        ("NO", False),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("off", False),
        ("Off", False),
    ],
)
def test_is_active_yes_no_variants(value, expected):
    config = {"myplugin": {"active": value}}
    assert is_active(config, "myplugin") is expected


def test_is_active_defaults_to_true_when_no_section():
    assert is_active({}, "myplugin") is True


def test_is_active_defaults_to_true_when_no_active_key():
    assert is_active({"myplugin": {"SOME_KEY": "val"}}, "myplugin") is True


def test_is_active_section_not_a_dict():
    # Edge case: section value is a scalar, not a table
    assert is_active({"myplugin": "yes"}, "myplugin") is True
