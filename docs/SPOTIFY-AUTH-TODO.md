# Spotify Auth Issues (2026-03-11)

## Problem 1: Redirect URI mismatch

Spotify Developer Dashboard requires `http://127.0.0.1:8888/callback` (not `localhost`)
due to SSL issues with `localhost`. The `.env` has been updated but spotipy cached a token
from an earlier auth that used `localhost`. When the token expires and spotipy tries to
re-authorize, it will hit "INVALID_CLIENT: Invalid redirect URI".

### To fix
1. Delete `.cache` in project root (spotipy token cache)
2. Ensure `.env` has `SPOTIPY_REDIRECT_URI="http://127.0.0.1:8888/callback"`
3. Ensure the same URI is registered in [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) → App Settings → Redirect URIs
4. Run `sandy "find me new music"` — should open browser for fresh auth
5. If it doesn't prompt for auth, the old token is still being reused from somewhere

## Problem 2: Release Radar not found

Auth succeeds but `_find_release_radar()` can't find the playlist. Two likely causes:

1. **Pagination**: `current_user_playlists()` only returns first 50 playlists. If Tom has 50+ playlists, Release Radar may be on a later page. Fix: paginate through all results.
2. **Playlist name**: Release Radar might have a different name in some locales or Spotify versions.

### To fix
- Add pagination to `_find_release_radar()` in `sandy/plugins/spotify.py`
- Consider searching by playlist description or owner (`spotify`) instead of exact name match
