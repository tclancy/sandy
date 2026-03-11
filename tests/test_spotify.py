from unittest.mock import patch, MagicMock
from sandy.plugins import spotify


def _mock_spotify_client(tracks):
    """Create a mock spotipy.Spotify client that returns given tracks."""
    mock_sp = MagicMock()
    mock_sp.current_user_playlists.return_value = {
        "items": [
            {"name": "Release Radar", "id": "release-radar-id"}
        ]
    }
    mock_sp.playlist_items.return_value = {
        "items": [
            {
                "track": {
                    "name": track["name"],
                    "artists": [{"name": track["artist"]}],
                    "album": {"name": track["album"]},
                    "external_urls": {"spotify": track["url"]},
                }
            }
            for track in tracks
        ]
    }
    return mock_sp


def test_spotify_name():
    assert spotify.name == "spotify"


def test_spotify_commands():
    assert "find me new music" in spotify.commands
    assert "new music" in spotify.commands


def test_handle_returns_formatted_tracks():
    tracks = [
        {
            "name": "Song A",
            "artist": "Artist A",
            "album": "Album A",
            "url": "https://open.spotify.com/track/aaa",
        },
        {
            "name": "Song B",
            "artist": "Artist B",
            "album": "Album B",
            "url": "https://open.spotify.com/track/bbb",
        },
    ]
    mock_sp = _mock_spotify_client(tracks)
    with patch.object(spotify, "_get_spotify_client", return_value=mock_sp):
        result = spotify.handle("find me new music", "tom")
    assert "Artist A" in result
    assert "Song A" in result
    assert "Album A" in result
    assert "https://open.spotify.com/track/aaa" in result
    assert "Artist B" in result


def test_handle_no_release_radar():
    mock_sp = MagicMock()
    mock_sp.current_user_playlists.return_value = {"items": []}
    with patch.object(spotify, "_get_spotify_client", return_value=mock_sp):
        result = spotify.handle("find me new music", "tom")
    assert "couldn't find" in result.lower() or "no release radar" in result.lower()


def test_handle_empty_playlist():
    mock_sp = MagicMock()
    mock_sp.current_user_playlists.return_value = {
        "items": [{"name": "Release Radar", "id": "rr-id"}]
    }
    mock_sp.playlist_items.return_value = {"items": []}
    with patch.object(spotify, "_get_spotify_client", return_value=mock_sp):
        result = spotify.handle("find me new music", "tom")
    assert "empty" in result.lower() or "no tracks" in result.lower()


def test_handle_auth_failure():
    with patch.object(spotify, "_get_spotify_client", side_effect=Exception("no credentials")):
        result = spotify.handle("find me new music", "tom")
    assert "auth failed" in result.lower()
