"""Tests for sandy/plugins/health.py."""

from __future__ import annotations

import sandy.plugins.health as health_plugin


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
    # health plugin should appear in the list
    assert "health" in result["text"]


def test_handle_lists_dispatch_plugin():
    """Dispatch plugin (a stable neighbor) should appear in health output."""
    result = health_plugin.handle("health", "tom")
    assert "dispatch" in result["text"]


def test_handle_shows_commands():
    """Each plugin entry should include at least one command."""
    result = health_plugin.handle("health", "tom")
    # backtick-wrapped commands should appear for health itself
    assert "`health`" in result["text"]


def test_handle_actor_ignored():
    """Actor parameter doesn't affect health output."""
    result_tom = health_plugin.handle("health", "tom")
    result_other = health_plugin.handle("health", "michelle")
    assert result_tom["text"] == result_other["text"]
