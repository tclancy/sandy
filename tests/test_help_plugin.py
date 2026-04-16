"""Tests for sandy/plugins/help.py (renamed from health.py)."""

from __future__ import annotations

import textwrap

import sandy.config as config_module
import sandy.plugins.help as help_plugin


def test_name():
    assert help_plugin.name == "help"


def test_commands_include_help():
    assert "help" in help_plugin.commands


def test_commands_include_health_backward_compat():
    assert "health" in help_plugin.commands


def test_handle_returns_title_and_text():
    result = help_plugin.handle("help", "tom")
    assert "title" in result
    assert result["title"] == "Sandy Help"
    assert "text" in result
    assert isinstance(result["text"], str)


def test_handle_lists_itself():
    result = help_plugin.handle("help", "tom")
    assert "help" in result["text"]


def test_handle_shows_commands():
    result = help_plugin.handle("help", "tom")
    assert "`help`" in result["text"]


def test_handle_no_permissions_shows_all(tmp_path, monkeypatch):
    """Without permissions config, all actors see all plugins (backward compat)."""
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text("")
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])

    result_tom = help_plugin.handle("help", "tom")
    result_other = help_plugin.handle("help", "someone")
    assert result_tom["text"] == result_other["text"]


def test_handle_hides_private_plugins(tmp_path, monkeypatch):
    """Non-owner actors should not see private plugins."""
    toml_content = textwrap.dedent("""\
        [sandy]
        owner = "tom"

        [actors.tom]
        aliases = ["tclancy"]

        [actors.alice]
        aliases = ["alice"]

        [permissions]
        default_access = "private"

        [permissions.plugins.help]
        access = "public"

        [permissions.plugins.sports]
        access = "public"
    """)
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text(toml_content)
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])

    result_tom = help_plugin.handle("help", "tom")
    result_alice = help_plugin.handle("help", "alice")

    assert "dispatch" in result_tom["text"] or "help" in result_tom["text"]
    assert "dispatch" not in result_alice["text"]


def test_dispatch_not_shown_when_inactive(tmp_path, monkeypatch):
    toml_content = textwrap.dedent("""\
        [dispatch]
        active = "no"
    """)
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text(toml_content)
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])

    result = help_plugin.handle("help", "tom")
    assert "dispatch" not in result["text"]


def test_dispatch_shown_when_active(tmp_path, monkeypatch):
    toml_content = textwrap.dedent("""\
        [dispatch]
        active = "yes"
    """)
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text(toml_content)
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])

    result = help_plugin.handle("help", "tom")
    assert "dispatch" in result["text"]
