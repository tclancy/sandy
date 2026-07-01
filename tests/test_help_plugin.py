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


def test_handle_renders_command_groups_as_separate_rows(tmp_path, monkeypatch):
    """A plugin exposing ``command_groups`` should get one help row per group,
    with the group key hoisted out of the flat commands row. This is the
    itguy#131 fix (sandy#133 enabler): compound commands like `itguy arr`
    document their subcommands on their own line instead of appearing as a
    leaf next to real one-shot commands."""
    fake_plugin_dir = tmp_path / "plugins"
    fake_plugin_dir.mkdir()
    (fake_plugin_dir / "__init__.py").write_text("")
    (fake_plugin_dir / "itguy_stub.py").write_text(
        textwrap.dedent("""
            name = "itguy"
            commands = ["itguy list", "itguy arr", "itguy scan"]
            command_groups = {
                "itguy arr": ["itguy arr list", "itguy arr restart", "itguy arr logs"],
            }
            def handle(text, actor):
                return {"title": "IT Guy", "text": "stub"}
        """)
    )
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text("")
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])
    monkeypatch.setattr(help_plugin, "_plugin_dir", lambda: fake_plugin_dir)

    result = help_plugin.handle("help", "tom")
    text = result["text"]

    # Top row: `itguy arr` is de-duped OUT of the flat commands row
    # (it's rendered as its own group row below).
    assert "• *itguy*: `itguy list`, `itguy scan`" in text
    assert "`itguy arr`," not in text  # not in the flat row anymore

    # Group row: `itguy arr` and its subcommands on their own line.
    assert "• *itguy arr*: `itguy arr list`, `itguy arr restart`, `itguy arr logs`" in text


def test_handle_plugin_without_command_groups_unchanged(tmp_path, monkeypatch):
    """Back-compat: a plugin that doesn't declare command_groups should render
    exactly like before this change — no missing rows, no de-dup surprises."""
    fake_plugin_dir = tmp_path / "plugins"
    fake_plugin_dir.mkdir()
    (fake_plugin_dir / "__init__.py").write_text("")
    (fake_plugin_dir / "simple.py").write_text(
        textwrap.dedent("""
            name = "simple"
            commands = ["simple do", "simple undo"]
            def handle(text, actor):
                return {"title": "Simple", "text": "stub"}
        """)
    )
    cfg_file = tmp_path / "sandy.toml"
    cfg_file.write_text("")
    monkeypatch.setattr(config_module, "_SEARCH_PATHS", [cfg_file])
    monkeypatch.setattr(help_plugin, "_plugin_dir", lambda: fake_plugin_dir)

    result = help_plugin.handle("help", "tom")
    assert "• *simple*: `simple do`, `simple undo`" in result["text"]


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
