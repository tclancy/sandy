# Spotify Auth Notes

## OAuth Setup

Credentials go in `.env` (gitignored):

```env
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

Scope required: `user-follow-read`

The redirect URI must be exactly `http://127.0.0.1:8888/callback` (not `localhost`) in both
`.env` and the Spotify Developer Dashboard (App Settings → Redirect URIs).

## First Run / Re-auth

Spotipy caches the token in `.cache` in the project root. On first run, or if the cache is
stale or has the wrong scope, delete it and re-run:

```bash
rm .cache
export $(grep -v '^#' .env | xargs) && .venv/bin/sandy "find me new music"
```

The browser will open for a one-time auth. After approving, `.cache` is written and subsequent
runs are silent.

## Why Not Release Radar

Spotify removed access to algorithmic/personalized playlists (Release Radar, Discover Weekly)
from the Web API in November 2024:
[Spotify API changes Nov 2024](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)

The plugin instead fetches recent releases from artists the user follows — more personal anyway.
