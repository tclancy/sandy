"""Tests for sandy/plugins/health.py."""

from __future__ import annotations

import textwrap


import sandy.plugins.health as health_plugin
import sandy.config as config_module


def test_name():
    assert health_plugin.name == "health"


def test_commands():
    assert "health" in health_plugin.commands


def test_handle_returns_title_and_text():
    result = health_plugin.handle("health", "tom")
    assert "title" in result
    assert result["title"] == "Sandy Health"
    assert "text" in result
    assert isinstance(result["text"], str)


def test_handle_lists_itself():
    """Health plugin must be visible in its own output."""
    result = health_plugin.handle("health", "tom")
    assert "health" in result["text"]


def test_handle_shows_commands():
    """Each plugin entry should include at least one command."""
    result = health_plugin.handle("health", "tom")
    assert "`health`" in result["text"]


def test_handle_actor_ignored():
    """Actor parameter doesn't affect health output."""
    result_tom = health_plugin.handle("health", "tom")
    result_other = health_plugin.handle("health", "michelle")
    assert result_tom["text"] == result_other["text"]


def test_dispatch_not_shown_when_inactive(tmp_path, monkeypatch):
    """Dispatch plugin (active=no by default) must not appear in health output."""
    toml_content = textwrap.dedent("""\
        [dispatch]
        active = "no"
    """)
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text(toml_content)
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])

    result = health_plugin.handle("health", "tom")
    assert "dispatch" not in result["text"]


def test_dispatch_shown_when_active(tmp_path, monkeypatch):
    """Dispatch plugin appears in health output when explicitly enabled."""
    toml_content = textwrap.dedent("""\
        [dispatch]
        active = "yes"
    """)
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text(toml_content)
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])

    result = health_plugin.handle("health", "tom")
    assert "dispatch" in result["text"]
