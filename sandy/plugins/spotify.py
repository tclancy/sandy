import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime, timedelta, timezone

name = "spotify"
commands = ["find me new music", "new music"]

LOOKBACK_DAYS = 30


def _get_spotify_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client.

    Requires environment variables: SPOTIPY_CLIENT_ID,
    SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI.
    """
    auth_manager = SpotifyOAuth(scope="user-follow-read")
    return spotipy.Spotify(auth_manager=auth_manager)


def _get_followed_artists(sp: spotipy.Spotify) -> list[dict]:
    """Get all artists the user follows, paginating via cursor."""
    artists = []
    response = sp.current_user_followed_artists(limit=50)
    while response:
        page = response.get("artists", {})
        artists.extend(page.get("items", []))
        cursor = page.get("cursors", {}).get("after")
        response = sp.current_user_followed_artists(limit=50, after=cursor) if cursor else None
    return artists


def _parse_release_date(release_date: str) -> datetime | None:
    """Parse Spotify release_date strings ('2024-03-15', '2024-03', '2024')."""
    utc = timezone.utc
    try:
        if len(release_date) == 4:
            return datetime(int(release_date), 1, 1, tzinfo=utc)
        if len(release_date) == 7:
            year, month = release_date.split("-")
            return datetime(int(year), int(month), 1, tzinfo=utc)
        return datetime.fromisoformat(release_date).replace(tzinfo=utc)
    except (ValueError, AttributeError):
        return None


def _get_recent_releases(sp: spotipy.Spotify, artist_id: str, since: datetime) -> list[dict]:
    """Get albums/singles released by an artist on or after `since`."""
    result = sp.artist_albums(artist_id, album_type="album,single", limit=10)
    releases = []
    for album in result.get("items", []):
        release_dt = _parse_release_date(album.get("release_date", ""))
        if release_dt and release_dt >= since:
            releases.append(album)
    return releases


def handle(text: str, actor: str) -> str:
    try:
        sp = _get_spotify_client()
    except Exception as e:
        return f"Spotify auth failed: {e}"

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    artists = _get_followed_artists(sp)

    if not artists:
        return "You don't follow any artists on Spotify."

    lines = [f"New releases from artists you follow (last {LOOKBACK_DAYS} days):", ""]
    found = 0

    for artist in artists:
        for album in _get_recent_releases(sp, artist["id"], since):
            album_type = album["album_type"].capitalize()
            url = album["external_urls"].get("spotify", "")
            entry = (
                f"- {artist['name']} \u2014 {album['name']}"
                f" ({album_type}, {album['release_date']}) {url}"
            )
            lines.append(entry)
            found += 1

    if found == 0:
        return f"No new releases from artists you follow in the last {LOOKBACK_DAYS} days."

    return "\n".join(lines)
