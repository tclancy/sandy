"""Tests for the music_discovery Sandy plugin."""

from unittest.mock import MagicMock, patch


from sandy.plugins import music_discovery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_top_artist(name: str):
    item = MagicMock()
    item.item.name = name
    return item


def _make_similar(name: str):
    item = MagicMock()
    item.item.name = name
    return item


def _make_top_track(artist: str, title: str):
    item = MagicMock()
    item.item.title = title
    return item


def _spotify_search_result(uri: str):
    return {"tracks": {"items": [{"uri": uri}]}}


def _empty_spotify_search():
    return {"tracks": {"items": []}}


# ---------------------------------------------------------------------------
# Module-level attribute tests
# ---------------------------------------------------------------------------


def test_name():
    assert music_discovery.name == "music_discovery"


def test_commands_include_discover():
    assert "find me new music" in music_discovery.commands
    assert "discover music" in music_discovery.commands
    assert "new music" in music_discovery.commands


# ---------------------------------------------------------------------------
# _get_top_artists
# ---------------------------------------------------------------------------


def test_get_top_artists_returns_names():
    mock_network = MagicMock()
    mock_network.get_user.return_value.get_top_artists.return_value = [
        _make_top_artist("Radiohead"),
        _make_top_artist("Slift"),
    ]
    result = music_discovery._get_top_artists(mock_network, "yerfatma")
    assert result == ["Radiohead", "Slift"]


# ---------------------------------------------------------------------------
# _get_similar_artists
# ---------------------------------------------------------------------------


def test_get_similar_artists_returns_names():
    mock_network = MagicMock()
    mock_network.get_artist.return_value.get_similar.return_value = [
        _make_similar("Godspeed You! Black Emperor"),
        _make_similar("Mogwai"),
    ]
    result = music_discovery._get_similar_artists(mock_network, "Radiohead")
    assert "Godspeed You! Black Emperor" in result
    assert "Mogwai" in result


def test_get_similar_artists_handles_ws_error():
    import pylast

    mock_network = MagicMock()
    mock_network.get_artist.return_value.get_similar.side_effect = pylast.WSError(
        "no network", "6", "Artist not found"
    )
    result = music_discovery._get_similar_artists(mock_network, "UnknownBand")
    assert result == []


# ---------------------------------------------------------------------------
# _get_top_tracks
# ---------------------------------------------------------------------------


def test_get_top_tracks_returns_tuples():
    mock_network = MagicMock()
    mock_network.get_artist.return_value.get_top_tracks.return_value = [
        _make_top_track("Mogwai", "Friend of the Night"),
        _make_top_track("Mogwai", "Mogwai Fear Satan"),
    ]
    result = music_discovery._get_top_tracks(mock_network, "Mogwai")
    assert ("Mogwai", "Friend of the Night") in result
    assert ("Mogwai", "Mogwai Fear Satan") in result


def test_get_top_tracks_handles_ws_error():
    import pylast

    mock_network = MagicMock()
    mock_network.get_artist.return_value.get_top_tracks.side_effect = pylast.WSError(
        "no network", "6", "Artist not found"
    )
    result = music_discovery._get_top_tracks(mock_network, "UnknownBand")
    assert result == []


# ---------------------------------------------------------------------------
# _search_spotify_track
# ---------------------------------------------------------------------------


def test_search_spotify_track_returns_uri_on_match():
    mock_sp = MagicMock()
    mock_sp.search.return_value = _spotify_search_result("spotify:track:abc123")
    uri = music_discovery._search_spotify_track(mock_sp, "Mogwai", "Friend of the Night")
    assert uri == "spotify:track:abc123"


def test_search_spotify_track_falls_back_to_track_only():
    mock_sp = MagicMock()
    # First call (artist+track) returns nothing; second call (track only) succeeds
    mock_sp.search.side_effect = [
        _empty_spotify_search(),
        _spotify_search_result("spotify:track:fallback"),
    ]
    uri = music_discovery._search_spotify_track(mock_sp, "Mogwai", "Friend of the Night")
    assert uri == "spotify:track:fallback"


def test_search_spotify_track_returns_none_when_no_results():
    mock_sp = MagicMock()
    mock_sp.search.return_value = _empty_spotify_search()
    uri = music_discovery._search_spotify_track(mock_sp, "NoArtist", "NoTrack")
    assert uri is None


# ---------------------------------------------------------------------------
# handle() — integration-level tests with mocked helpers
# ---------------------------------------------------------------------------


def test_handle_missing_lastfm_username(monkeypatch):
    monkeypatch.delenv("LASTFM_USERNAME", raising=False)
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    result = music_discovery.handle("find me new music", "tom")
    assert "LASTFM_USERNAME" in result["text"]


def test_handle_missing_playlist_id(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.delenv("SPOTIFY_PLAYLIST_ID", raising=False)
    result = music_discovery.handle("find me new music", "tom")
    assert "SPOTIFY_PLAYLIST_ID" in result["text"]


def test_handle_lastfm_config_error(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    # LASTFM_API_KEY missing from env → KeyError
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    with patch.object(
        music_discovery, "_get_lastfm_network", side_effect=KeyError("LASTFM_API_KEY")
    ):
        result = music_discovery.handle("find me new music", "tom")
    assert "Last.fm config missing" in result["text"]


def test_handle_no_top_artists(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=[]):
            result = music_discovery.handle("find me new music", "tom")
    assert "No top artists" in result["text"]


def test_handle_no_candidates(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(music_discovery, "_collect_candidate_tracks", return_value=[]):
                result = music_discovery.handle("find me new music", "tom")
    assert "No candidate tracks" in result["text"]


def test_handle_spotify_auth_failure(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Friend of the Night")],
            ):
                with patch.object(
                    music_discovery, "_get_spotify_client", side_effect=Exception("no credentials")
                ):
                    result = music_discovery.handle("find me new music", "tom")
    assert "Spotify auth failed" in result["text"]


def test_handle_no_spotify_uris(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Friend of the Night")],
            ):
                with patch.object(music_discovery, "_get_spotify_client"):
                    with patch.object(music_discovery, "_search_spotify_track", return_value=None):
                        result = music_discovery.handle("find me new music", "tom")
    assert "Could not find" in result["text"]


def test_handle_success(monkeypatch):
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "2tYYHWuJGXtgbAn3OIwRKj")

    mock_sp = MagicMock()

    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Friend of the Night"), ("Slift", "Ilion")],
            ):
                with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
                    with patch.object(
                        music_discovery,
                        "_search_spotify_track",
                        side_effect=["spotify:track:abc", "spotify:track:def"],
                    ):
                        result = music_discovery.handle("find me new music", "tom")

    assert result["title"] == "Music Discovery"
    assert "2" in result["text"]
    assert "links" in result
    assert "2tYYHWuJGXtgbAn3OIwRKj" in result["links"][0]["url"]
    mock_sp.playlist_replace_items.assert_called_once_with(
        "2tYYHWuJGXtgbAn3OIwRKj",
        ["spotify:track:abc", "spotify:track:def"],
    )


def test_handle_deduplicates_uris(monkeypatch):
    """Duplicate Spotify URIs from different Last.fm tracks are deduplicated."""
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")

    mock_sp = MagicMock()

    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Track A"), ("Slift", "Track B")],
            ):
                with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
                    with patch.object(
                        music_discovery,
                        "_search_spotify_track",
                        return_value="spotify:track:same_uri",  # same URI for both
                    ):
                        music_discovery.handle("find me new music", "tom")

    # Should only add 1 track, not 2 copies of the same URI
    called_uris = mock_sp.playlist_replace_items.call_args[0][1]
    assert called_uris.count("spotify:track:same_uri") == 1
