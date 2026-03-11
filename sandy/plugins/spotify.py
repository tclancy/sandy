import spotipy
from spotipy.oauth2 import SpotifyOAuth

name = "spotify"
commands = ["find me new music", "new music"]


def _get_spotify_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client.

    Requires environment variables: SPOTIPY_CLIENT_ID,
    SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI.
    Spotipy handles token caching and refresh automatically.
    """
    auth_manager = SpotifyOAuth(scope="playlist-read-private")
    return spotipy.Spotify(auth_manager=auth_manager)


def _find_release_radar(sp: spotipy.Spotify) -> str | None:
    """Find the Release Radar playlist ID from user's playlists."""
    playlists = sp.current_user_playlists()
    for playlist in playlists.get("items", []):
        if playlist["name"] == "Release Radar":
            return playlist["id"]
    return None


def handle(text: str, actor: str) -> str:
    try:
        sp = _get_spotify_client()
    except Exception as e:
        return f"Spotify auth failed: {e}"

    playlist_id = _find_release_radar(sp)
    if playlist_id is None:
        return "Couldn't find your Release Radar playlist."

    items = sp.playlist_items(playlist_id)
    tracks = items.get("items", [])

    if not tracks:
        return "Your Release Radar is empty this week."

    lines = ["New music from Release Radar:", ""]
    for item in tracks:
        track = item.get("track")
        if track is None:
            continue
        artist = track["artists"][0]["name"]
        album = track["album"]["name"]
        song = track["name"]
        url = track["external_urls"].get("spotify", "")
        lines.append(f"- {artist} - {album} - {song} ({url})")

    return "\n".join(lines)
