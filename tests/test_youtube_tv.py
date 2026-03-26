"""Tests for the youtube_tv plugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sandy.plugins import youtube_tv


# ---------------------------------------------------------------------------
# _resolve_channel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_name",
    [
        ("ESPN", "espn"),
        ("espn", "espn"),
        ("ESPN2", "espn2"),
        ("cnn", "cnn"),
        ("Fox News", "fox news"),
        ("fox news", "fox news"),
        ("nbc sports", "nbc sports"),
        ("NBC", "nbc"),
    ],
)
def test_resolve_channel_known(query, expected_name):
    name, code = youtube_tv._resolve_channel(query)
    assert name == expected_name
    assert code == youtube_tv.CHANNEL_CODES[expected_name]


def test_resolve_channel_unknown():
    name, code = youtube_tv._resolve_channel("BobTV")
    assert name is None
    assert code is None


def test_resolve_channel_partial_match():
    # "espn" is in "espn2" — substring match should work both ways
    name, code = youtube_tv._resolve_channel("espn news")
    assert name == "espn news"
    assert code is not None


# ---------------------------------------------------------------------------
# _adb_host / _adb_port / _adb_path
# ---------------------------------------------------------------------------


def test_adb_host_default(monkeypatch):
    monkeypatch.delenv("YOUTUBE_TV_ADB_HOST", raising=False)
    assert youtube_tv._adb_host() == ""


def test_adb_host_from_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    assert youtube_tv._adb_host() == "192.168.1.50"


def test_adb_port_default(monkeypatch):
    monkeypatch.delenv("YOUTUBE_TV_ADB_PORT", raising=False)
    assert youtube_tv._adb_port() == "5555"


def test_adb_port_from_env(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_PORT", "5556")
    assert youtube_tv._adb_port() == "5556"


def test_adb_path_default(monkeypatch):
    monkeypatch.delenv("YOUTUBE_TV_ADB_PATH", raising=False)
    assert youtube_tv._adb_path() == "adb"


# ---------------------------------------------------------------------------
# _adb_tune
# ---------------------------------------------------------------------------


def _mock_run(returncode=0, stdout="connected", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_adb_tune_no_host(monkeypatch):
    monkeypatch.delenv("YOUTUBE_TV_ADB_HOST", raising=False)
    success, msg = youtube_tv._adb_tune("some-code")
    assert not success
    assert "YOUTUBE_TV_ADB_HOST" in msg


def test_adb_tune_adb_not_found(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    with patch("subprocess.run", side_effect=FileNotFoundError):
        success, msg = youtube_tv._adb_tune("some-code")
    assert not success
    assert "adb binary not found" in msg


def test_adb_tune_connect_timeout(monkeypatch):
    import subprocess

    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 10)):
        success, msg = youtube_tv._adb_tune("some-code")
    assert not success
    assert "timed out" in msg.lower()


def test_adb_tune_connect_failure(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    with patch(
        "subprocess.run",
        return_value=_mock_run(returncode=1, stdout="error", stderr="refused"),
    ):
        success, msg = youtube_tv._adb_tune("some-code")
    assert not success
    assert "refused" in msg


def test_adb_tune_launch_failure(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    connect_ok = _mock_run(returncode=0, stdout="connected to 192.168.1.50:5555")
    launch_fail = _mock_run(returncode=1, stderr="ActivityManager: Error type 3")

    with patch("subprocess.run", side_effect=[connect_ok, launch_fail]):
        success, msg = youtube_tv._adb_tune("some-code")
    assert not success
    assert "launch failed" in msg.lower()


def test_adb_tune_success(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    connect_ok = _mock_run(returncode=0, stdout="connected to 192.168.1.50:5555")
    launch_ok = _mock_run(
        returncode=0, stdout="Starting: Intent { act=android.intent.action.VIEW }"
    )

    with patch("subprocess.run", side_effect=[connect_ok, launch_ok]) as mock_run:
        success, detail = youtube_tv._adb_tune("bj3v-DQPnNs")

    assert success
    assert "bj3v-DQPnNs" in detail
    # Verify the ADB launch command uses the correct deep link
    launch_call_args = mock_run.call_args_list[1][0][0]
    assert "https://tv.youtube.com/watch/bj3v-DQPnNs" in launch_call_args


def test_adb_tune_uses_configured_port(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "10.0.0.5")
    monkeypatch.setenv("YOUTUBE_TV_ADB_PORT", "5556")
    connect_ok = _mock_run(returncode=0, stdout="connected")
    launch_ok = _mock_run(returncode=0, stdout="Starting:")

    with patch("subprocess.run", side_effect=[connect_ok, launch_ok]) as mock_run:
        youtube_tv._adb_tune("some-code")

    connect_args = mock_run.call_args_list[0][0][0]
    assert "10.0.0.5:5556" in connect_args


# ---------------------------------------------------------------------------
# handle
# ---------------------------------------------------------------------------


def test_handle_no_match():
    result = youtube_tv.handle("hello there", actor="tom")
    assert result["title"] == "YouTube TV"
    assert "Usage" in result["text"]


def test_handle_unknown_channel():
    result = youtube_tv.handle("watch BobTV", actor="tom")
    assert "not found" in result["text"]
    assert "BobTV" in result["text"]


def test_handle_known_channel_success(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    connect_ok = _mock_run(returncode=0, stdout="connected")
    launch_ok = _mock_run(returncode=0, stdout="Starting:")

    with patch("subprocess.run", side_effect=[connect_ok, launch_ok]):
        result = youtube_tv.handle("watch ESPN", actor="tom")

    assert result["title"] == "YouTube TV"
    assert "Espn" in result["text"] or "ESPN" in result["text"].upper()


def test_handle_known_channel_adb_failure(monkeypatch):
    monkeypatch.delenv("YOUTUBE_TV_ADB_HOST", raising=False)
    result = youtube_tv.handle("tune to CNN", actor="tom")
    assert "Failed" in result["text"]
    assert "YOUTUBE_TV_ADB_HOST" in result["text"]


def test_handle_progress_called(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    connect_ok = _mock_run(returncode=0, stdout="connected")
    launch_ok = _mock_run(returncode=0, stdout="Starting:")
    progress_calls = []

    with patch("subprocess.run", side_effect=[connect_ok, launch_ok]):
        youtube_tv.handle("put on Fox News", actor="tom", progress=progress_calls.append)

    assert len(progress_calls) > 0
    assert any("Fox News" in c or "fox news" in c.lower() for c in progress_calls)


def test_handle_tune_to_variant(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    connect_ok = _mock_run(returncode=0, stdout="connected")
    launch_ok = _mock_run(returncode=0, stdout="Starting:")

    with patch("subprocess.run", side_effect=[connect_ok, launch_ok]):
        result = youtube_tv.handle("tune to NBC", actor="tom")

    assert "NBC" in result["text"].upper()


def test_handle_put_on_variant(monkeypatch):
    monkeypatch.setenv("YOUTUBE_TV_ADB_HOST", "192.168.1.50")
    connect_ok = _mock_run(returncode=0, stdout="connected")
    launch_ok = _mock_run(returncode=0, stdout="Starting:")

    with patch("subprocess.run", side_effect=[connect_ok, launch_ok]):
        result = youtube_tv.handle("put on HGTV", actor="tom")

    assert "Hgtv" in result["text"] or "HGTV" in result["text"].upper()


# ---------------------------------------------------------------------------
# Module-level attributes
# ---------------------------------------------------------------------------


def test_plugin_name():
    assert youtube_tv.name == "youtube_tv"


def test_plugin_commands():
    assert isinstance(youtube_tv.commands, list)
    assert len(youtube_tv.commands) > 0
    assert all(isinstance(c, str) for c in youtube_tv.commands)


def test_channel_codes_not_empty():
    assert len(youtube_tv.CHANNEL_CODES) > 0
