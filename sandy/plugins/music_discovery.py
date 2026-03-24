"""Music Discovery Sandy plugin.

Pulls Tom's top artists from Last.fm, finds similar artists,
fetches their top tracks, then clears and repopulates a Spotify
playlist with discovered tracks.

Required environment variables (set via [music_discovery] in sandy.toml):
    LASTFM_API_KEY          — Last.fm API key
    LASTFM_API_SECRET       — Last.fm API secret
    LASTFM_USERNAME         — Last.fm username to base recommendations on
    SPOTIPY_CLIENT_ID       — Spotify app client ID
    SPOTIPY_CLIENT_SECRET   — Spotify app client secret
    SPOTIPY_REDIRECT_URI    — Spotify OAuth redirect URI
    SPOTIFY_PLAYLIST_ID     — Spotify playlist ID to populate
"""

import os

import pylast
import spotipy
from spotipy.oauth2 import SpotifyOAuth

name = "music_discovery"
commands = ["find me new music", "discover music", "new music"]

# How many of the user's top artists to seed from
TOP_ARTISTS_LIMIT = 10
# How many similar artists to explore per top artist
SIMILAR_ARTISTS_LIMIT = 5
# How many top tracks to pull per similar artist
TRACKS_PER_ARTIST = 5
# Target number of tracks in the final playlist
DISCOVERY_LIMIT = 50


def _get_lastfm_network() -> pylast.LastFMNetwork:
    """Create an authenticated Last.fm network client."""
    return pylast.LastFMNetwork(
        api_key=os.environ["LASTFM_API_KEY"],
        api_secret=os.environ["LASTFM_API_SECRET"],
    )


def _get_spotify_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client with playlist write scope."""
    auth_manager = SpotifyOAuth(
        scope="playlist-modify-public playlist-modify-private",
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def _get_top_artists(network: pylast.LastFMNetwork, username: str) -> list[str]:
    """Return the user's top artist names from the last 3 months."""
    user = network.get_user(username)
    top_artists = user.get_top_artists(period=pylast.PERIOD_3MONTHS, limit=TOP_ARTISTS_LIMIT)
    return [item.item.name for item in top_artists]


def _get_similar_artists(network: pylast.LastFMNetwork, artist_name: str) -> list[str]:
    """Return similar artist names for a given artist."""
    try:
        artist = network.get_artist(artist_name)
        similar = artist.get_similar(limit=SIMILAR_ARTISTS_LIMIT)
        return [item.item.name for item in similar]
    except pylast.WSError:
        return []


def _get_top_tracks(network: pylast.LastFMNetwork, artist_name: str) -> list[tuple[str, str]]:
    """Return (artist, track) tuples for an artist's top tracks."""
    try:
        artist = network.get_artist(artist_name)
        top_tracks = artist.get_top_tracks(limit=TRACKS_PER_ARTIST)
        return [(artist_name, item.item.title) for item in top_tracks]
    except pylast.WSError:
        return []


def _search_spotify_track(sp: spotipy.Spotify, artist: str, track: str) -> str | None:
    """Search Spotify for a track by artist+title. Returns URI or None."""
    query = f"artist:{artist} track:{track}"
    results = sp.search(q=query, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if items:
        return items[0]["uri"]
    # Fallback: search by track name only
    results = sp.search(q=track, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    return items[0]["uri"] if items else None


def _collect_candidate_tracks(
    network: pylast.LastFMNetwork,
    top_artists: list[str],
    progress=None,
) -> list[tuple[str, str]]:
    """Build a deduplicated list of (artist, track) candidates via Last.fm."""
    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[str, str]] = []

    for i, artist_name in enumerate(top_artists):
        if progress:
            progress(f"Exploring similar artists for {artist_name} ({i + 1}/{len(top_artists)})…")

        similar_names = _get_similar_artists(network, artist_name)
        # Exclude the seed artist itself — we want *discovery*, not familiar tracks
        similar_names = [n for n in similar_names if n.lower() != artist_name.lower()]

        for similar_name in similar_names:
            for artist, track in _get_top_tracks(network, similar_name):
                key = (artist.lower(), track.lower())
                if key not in seen:
                    seen.add(key)
                    candidates.append((artist, track))
                    if len(candidates) >= DISCOVERY_LIMIT * 2:
                        return candidates

    return candidates


def _get_lastfm_candidates(username: str, progress=None) -> tuple[list[tuple[str, str]], str]:
    """Fetch candidate (artist, track) pairs from Last.fm.

    Returns (candidates, error_message). On success error_message is "".
    """
    try:
        network = _get_lastfm_network()
    except KeyError as e:
        return [], f"Last.fm config missing: {e}"

    if progress:
        progress("Fetching your top artists from Last.fm…")

    try:
        top_artists = _get_top_artists(network, username)
    except pylast.WSError as e:
        return [], f"Last.fm error: {e}"

    if not top_artists:
        return [], "No top artists found on Last.fm for the last 3 months."

    candidates = _collect_candidate_tracks(network, top_artists, progress=progress)
    if not candidates:
        return [], "No candidate tracks found via Last.fm similarity search."

    return candidates, ""


def _resolve_spotify_uris(
    sp: spotipy.Spotify, candidates: list[tuple[str, str]], progress=None
) -> list[str]:
    """Search Spotify for each candidate and return deduplicated URIs."""
    if progress:
        progress(f"Searching Spotify for {len(candidates)} candidate tracks…")

    uris: list[str] = []
    for artist, track in candidates:
        if len(uris) >= DISCOVERY_LIMIT:
            break
        uri = _search_spotify_track(sp, artist, track)
        if uri and uri not in uris:
            uris.append(uri)
    return uris


def handle(text: str, actor: str, progress=None) -> dict:
    """Discover new music via Last.fm and populate a Spotify playlist."""
    username = os.environ.get("LASTFM_USERNAME", "")
    playlist_id = os.environ.get("SPOTIFY_PLAYLIST_ID", "")

    if not username:
        return {"text": "LASTFM_USERNAME not configured."}
    if not playlist_id:
        return {"text": "SPOTIFY_PLAYLIST_ID not configured."}

    candidates, error = _get_lastfm_candidates(username, progress=progress)
    if error:
        return {"text": error}

    try:
        sp = _get_spotify_client()
    except Exception as e:
        return {"text": f"Spotify auth failed: {e}"}

    uris = _resolve_spotify_uris(sp, candidates, progress=progress)
    if not uris:
        return {"text": "Could not find any candidate tracks on Spotify."}

    if progress:
        progress(f"Populating playlist with {len(uris)} tracks…")

    sp.playlist_replace_items(playlist_id, uris)

    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
    return {
        "title": "Music Discovery",
        "text": f"Added {len(uris)} discovered tracks to your playlist.",
        "links": [{"label": "Open discovery playlist", "url": playlist_url}],
    }
