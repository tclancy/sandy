from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from sandy.plugins import spotify


def _make_artist(artist_id, name):
    return {"id": artist_id, "name": name}


def _make_album(name, album_type, release_date, url="https://open.spotify.com/album/x"):
    return {
        "name": name,
        "album_type": album_type,
        "release_date": release_date,
        "external_urls": {"spotify": url},
    }


def test_spotify_name():
    assert spotify.name == "spotify"


def test_spotify_commands():
    assert "find me new music" in spotify.commands
    assert "new music" in spotify.commands


def test_handle_auth_failure():
    with patch.object(spotify, "_get_spotify_client", side_effect=Exception("no credentials")):
        result = spotify.handle("find me new music", "tom")
    assert "auth failed" in result["text"].lower()


def test_handle_no_followed_artists():
    with patch.object(spotify, "_get_spotify_client"):
        with patch.object(spotify, "_get_followed_artists", return_value=[]):
            result = spotify.handle("find me new music", "tom")
    assert "don't follow" in result["text"].lower()


def test_handle_no_recent_releases():
    artists = [_make_artist("a1", "The Wipers")]
    with patch.object(spotify, "_get_spotify_client"):
        with patch.object(spotify, "_get_followed_artists", return_value=artists):
            with patch.object(spotify, "_get_recent_releases", return_value=[]):
                result = spotify.handle("find me new music", "tom")
    assert "no new releases" in result["text"].lower()


def test_handle_returns_formatted_releases():
    artists = [_make_artist("a1", "Slift"), _make_artist("a2", "Kikagaku Moyo")]
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    date_str = recent.strftime("%Y-%m-%d")
    slift_album = _make_album("Ilion", "album", date_str, "https://open.spotify.com/album/slift")

    def fake_recent_releases(sp, artist_id, since):
        return [slift_album] if artist_id == "a1" else []

    with patch.object(spotify, "_get_spotify_client"):
        with patch.object(spotify, "_get_followed_artists", return_value=artists):
            with patch.object(spotify, "_get_recent_releases", side_effect=fake_recent_releases):
                result = spotify.handle("find me new music", "tom")

    text = result["text"]
    assert "Slift" in text
    assert "Ilion" in text
    assert "https://open.spotify.com/album/slift" in text
    assert "Kikagaku Moyo" not in text


def test_parse_release_date_full():
    dt = spotify._parse_release_date("2024-03-15")
    assert dt == datetime(2024, 3, 15, tzinfo=timezone.utc)


def test_parse_release_date_year_month():
    dt = spotify._parse_release_date("2024-03")
    assert dt == datetime(2024, 3, 1, tzinfo=timezone.utc)


def test_parse_release_date_year_only():
    dt = spotify._parse_release_date("2024")
    assert dt == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_parse_release_date_invalid():
    assert spotify._parse_release_date("garbage") is None


def test_get_recent_releases_filters_by_date():
    mock_sp = MagicMock()
    old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    new_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
    mock_sp.artist_albums.return_value = {
        "items": [
            _make_album("Old Record", "album", old_date),
            _make_album("Fresh Single", "single", new_date),
        ]
    }
    since = datetime.now(timezone.utc) - timedelta(days=30)
    results = spotify._get_recent_releases(mock_sp, "artist-id", since)
    assert len(results) == 1
    assert results[0]["name"] == "Fresh Single"


def test_get_followed_artists_paginates():
    mock_sp = MagicMock()
    mock_sp.current_user_followed_artists.side_effect = [
        {"artists": {"items": [_make_artist("a1", "Wire")], "cursors": {"after": "cursor1"}}},
        {"artists": {"items": [_make_artist("a2", "Gang of Four")], "cursors": {"after": None}}},
    ]
    artists = spotify._get_followed_artists(mock_sp)
    assert [a["name"] for a in artists] == ["Wire", "Gang of Four"]
