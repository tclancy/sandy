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


def test_handle_spotify_auth_failure_reports_to_sentry(monkeypatch, sentry_events):
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
                    music_discovery,
                    "_get_spotify_client",
                    side_effect=RuntimeError("no credentials"),
                ):
                    music_discovery.handle("find me new music", "tom")
    assert len(sentry_events) == 1
    assert sentry_events[0]["tags"]["plugin"] == "music_discovery"


def test_save_playlist_source_read_failure_reports_to_sentry(sentry_events):
    mock_sp = MagicMock()
    with patch.object(
        music_discovery, "_get_playlist_track_uris", side_effect=RuntimeError("api down")
    ):
        result = music_discovery._save_playlist(mock_sp, "src-id", "New Mix")
    assert "Could not read source playlist" in result["text"]
    assert len(sentry_events) == 1
    assert sentry_events[0]["tags"]["plugin"] == "music_discovery"


def test_handle_login_auth_manager_failure_reports_to_sentry(monkeypatch, sentry_events):
    monkeypatch.setenv("SPOTIPY_REDIRECT_URI", "https://sandy.example/callback")
    with patch.object(music_discovery.oauth_server, "get_configured_port", return_value=8080):
        with patch.object(music_discovery, "SpotifyOAuth", side_effect=RuntimeError("bad config")):
            result = music_discovery.handle("music login", "tom")
    assert "Could not create Spotify auth manager" in result["text"]
    assert len(sentry_events) == 1
    assert sentry_events[0]["tags"]["plugin"] == "music_discovery"


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
    # Two-step clear-then-add: first call clears, second adds new tracks
    mock_sp.playlist_replace_items.assert_called_once_with("2tYYHWuJGXtgbAn3OIwRKj", [])
    mock_sp.playlist_add_items.assert_called_once_with(
        "2tYYHWuJGXtgbAn3OIwRKj",
        ["spotify:track:abc", "spotify:track:def"],
    )


def test_handle_clears_existing_tracks(monkeypatch):
    """Existing playlist tracks are cleared before new ones are added (#97)."""
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "playlist-with-old-tracks")

    mock_sp = MagicMock()
    call_order = []
    mock_sp.playlist_replace_items.side_effect = lambda *a, **kw: call_order.append(
        ("replace", a[1])
    )
    mock_sp.playlist_add_items.side_effect = lambda *a, **kw: call_order.append(("add", a[1]))

    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Friend of the Night")],
            ):
                with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
                    with patch.object(
                        music_discovery,
                        "_search_spotify_track",
                        return_value="spotify:track:new",
                    ):
                        result = music_discovery.handle("new music", "tom")

    # Clear must come before add
    assert call_order[0] == ("replace", []), "playlist must be cleared first"
    assert call_order[1] == ("add", ["spotify:track:new"]), "new tracks added second"
    assert result["title"] == "Music Discovery"


def test_handle_spotify_clear_error(monkeypatch):
    """Spotify API error during playlist clear returns an error message."""
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")

    mock_sp = MagicMock()
    mock_sp.playlist_replace_items.side_effect = Exception("403 Forbidden")

    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Friend of the Night")],
            ):
                with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
                    with patch.object(
                        music_discovery,
                        "_search_spotify_track",
                        return_value="spotify:track:abc",
                    ):
                        result = music_discovery.handle("new music", "tom")

    assert "playlist update failed" in result["text"].lower()
    assert "403 Forbidden" in result["text"]
    # Clear failed, so old tracks still exist — no empty-playlist warning needed
    assert "cleared" not in result["text"].lower()


def test_handle_spotify_add_error_warns_playlist_empty(monkeypatch):
    """If add fails after a successful clear, the error message warns the playlist is empty."""
    monkeypatch.setenv("LASTFM_USERNAME", "yerfatma")
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")

    mock_sp = MagicMock()
    mock_sp.playlist_replace_items.return_value = None  # clear succeeds
    mock_sp.playlist_add_items.side_effect = Exception("500 Server Error")

    with patch.object(music_discovery, "_get_lastfm_network"):
        with patch.object(music_discovery, "_get_top_artists", return_value=["Radiohead"]):
            with patch.object(
                music_discovery,
                "_collect_candidate_tracks",
                return_value=[("Mogwai", "Friend of the Night")],
            ):
                with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
                    with patch.object(
                        music_discovery,
                        "_search_spotify_track",
                        return_value="spotify:track:abc",
                    ):
                        result = music_discovery.handle("new music", "tom")

    assert "playlist update failed" in result["text"].lower()
    assert "500 Server Error" in result["text"]
    # Must warn the user the playlist was cleared so they know it's empty
    assert "cleared" in result["text"].lower()


# ---------------------------------------------------------------------------
# music save command
# ---------------------------------------------------------------------------


def test_handle_save_no_playlist_id(monkeypatch):
    """save returns error when SPOTIFY_PLAYLIST_ID is not set."""
    monkeypatch.delenv("SPOTIFY_PLAYLIST_ID", raising=False)
    result = music_discovery.handle("music save My Playlist", "tom")
    assert "SPOTIFY_PLAYLIST_ID" in result["text"]


def test_handle_save_no_name(monkeypatch):
    """save without a name returns usage hint."""
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    result = music_discovery.handle("music save", "tom")
    assert "Usage" in result["text"]


def test_handle_save_spotify_auth_failure(monkeypatch):
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    with patch.object(music_discovery, "_get_spotify_client", side_effect=Exception("no creds")):
        result = music_discovery.handle("music save My Mix", "tom")
    assert "Spotify auth failed" in result["text"]


def test_handle_save_empty_source_playlist(monkeypatch):
    """save returns error when source playlist has no tracks."""
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    mock_sp = MagicMock()
    with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
        with patch.object(music_discovery, "_get_playlist_track_uris", return_value=[]):
            result = music_discovery.handle("music save My Mix", "tom")
    assert "empty" in result["text"].lower()


def test_handle_save_creates_new_playlist(monkeypatch):
    """save creates a new playlist and copies tracks from source."""
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "source-playlist-id")

    mock_sp = MagicMock()
    mock_sp.me.return_value = {"id": "spotify-user-123"}
    mock_sp.user_playlist_create.return_value = {"id": "new-playlist-id"}

    with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
        with patch.object(
            music_discovery,
            "_get_playlist_track_uris",
            return_value=["spotify:track:aaa", "spotify:track:bbb"],
        ):
            result = music_discovery.handle("music save April Discoveries", "tom")

    assert result["title"] == "Playlist Saved"
    assert "2" in result["text"]
    assert "April Discoveries" in result["text"]
    assert "new-playlist-id" in result["links"][0]["url"]
    mock_sp.user_playlist_create.assert_called_once_with(
        "spotify-user-123", "April Discoveries", public=False
    )
    mock_sp.playlist_add_items.assert_called_once_with(
        "new-playlist-id", ["spotify:track:aaa", "spotify:track:bbb"]
    )


def test_handle_save_playlist_creation_error(monkeypatch):
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    mock_sp = MagicMock()
    mock_sp.user_playlist_create.side_effect = Exception("403 Forbidden")
    with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
        with patch.object(
            music_discovery,
            "_get_playlist_track_uris",
            return_value=["spotify:track:aaa"],
        ):
            result = music_discovery.handle("music save Fail Playlist", "tom")
    assert "Could not create playlist" in result["text"]
    assert "403 Forbidden" in result["text"]


def test_handle_save_add_tracks_error(monkeypatch):
    monkeypatch.setenv("SPOTIFY_PLAYLIST_ID", "someplaylist")
    mock_sp = MagicMock()
    mock_sp.me.return_value = {"id": "user123"}
    mock_sp.user_playlist_create.return_value = {"id": "new-id"}
    mock_sp.playlist_add_items.side_effect = Exception("500 Server Error")
    with patch.object(music_discovery, "_get_spotify_client", return_value=mock_sp):
        with patch.object(
            music_discovery,
            "_get_playlist_track_uris",
            return_value=["spotify:track:aaa"],
        ):
            result = music_discovery.handle("music save Partial Save", "tom")
    assert "could not add tracks" in result["text"].lower()


def test_commands_include_save():
    assert "music save" in music_discovery.commands


def test_commands_include_login():
    assert "music login" in music_discovery.commands


# ---------------------------------------------------------------------------
# music login command
# ---------------------------------------------------------------------------


def test_handle_login_no_oauth_port(monkeypatch):
    """login returns error when OAuth server is not configured."""
    monkeypatch.delenv("OAUTH_SERVER_PORT", raising=False)
    result = music_discovery.handle("music login", "tom")
    assert "OAuth server is not running" in result["text"]


def test_handle_login_no_redirect_uri(monkeypatch):
    monkeypatch.setenv("OAUTH_SERVER_PORT", "8888")
    monkeypatch.delenv("SPOTIPY_REDIRECT_URI", raising=False)
    result = music_discovery.handle("music login", "tom")
    assert "SPOTIPY_REDIRECT_URI" in result["text"]


def test_handle_login_returns_auth_url(monkeypatch):
    """login returns the authorization URL and registers pending oauth with a state token."""
    monkeypatch.setenv("OAUTH_SERVER_PORT", "8888")
    monkeypatch.setenv("SPOTIPY_REDIRECT_URI", "https://sandy.tomclancy.info/callback")

    mock_manager = MagicMock()
    mock_manager.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?code=test"

    with patch("sandy.plugins.music_discovery.SpotifyOAuth", return_value=mock_manager) as mock_cls:
        with patch("sandy.plugins.music_discovery.oauth_server") as mock_oauth:
            mock_oauth.get_configured_port.return_value = 8888
            mock_oauth.set_pending_oauth = MagicMock()

            result = music_discovery.handle("music login", "tom")

    assert result["title"] == "Spotify Login"
    assert "links" in result
    assert "accounts.spotify.com" in result["links"][0]["url"]
    # SpotifyOAuth must be constructed with a state= argument (CSRF protection)
    _, kwargs = mock_cls.call_args
    assert "state" in kwargs and kwargs["state"], "SpotifyOAuth must receive a non-empty state"
    # set_pending_oauth must be called with both the manager and the same state value
    mock_oauth.set_pending_oauth.assert_called_once_with(mock_manager, kwargs["state"])


def test_handle_login_auth_manager_creation_failure(monkeypatch):
    """If SpotifyOAuth construction fails, return an error."""
    monkeypatch.setenv("OAUTH_SERVER_PORT", "8888")
    monkeypatch.setenv("SPOTIPY_REDIRECT_URI", "https://sandy.tomclancy.info/callback")

    with patch("sandy.plugins.music_discovery.SpotifyOAuth", side_effect=Exception("bad creds")):
        with patch("sandy.plugins.music_discovery.oauth_server") as mock_oauth:
            mock_oauth.get_configured_port.return_value = 8888

            result = music_discovery.handle("music login", "tom")

    assert "Could not create Spotify auth manager" in result["text"]


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
    called_uris = mock_sp.playlist_add_items.call_args[0][1]
    assert called_uris.count("spotify:track:same_uri") == 1
