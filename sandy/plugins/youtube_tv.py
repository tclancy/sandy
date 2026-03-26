"""YouTubeTV Sandy plugin.

Tunes the Living Room TV (Google TV / Chromecast with Google TV) to a
YouTubeTV channel via ADB (Android Debug Bridge) over the network.

ADB must be enabled on the TV:
  Settings → System → About → Enable developer options → USB debugging
  (or ADB over network via Android TV Remote Service)

Commands:
  "watch ESPN"          — tune to ESPN
  "tune to CNN"         — tune to CNN
  "put on NBC"          — tune to NBC
  "what's on ESPN"      — tune to ESPN (alias)

Configuration (sandy.toml [youtube_tv] section):
  YOUTUBE_TV_ADB_HOST   — IP address of the Google TV on the LAN (required)
  YOUTUBE_TV_ADB_PORT   — ADB port on the TV (default: 5555)
  YOUTUBE_TV_ADB_PATH   — path to the adb binary (default: "adb" on PATH)

Channel codes rotate every few days to months — Tom should update
CHANNEL_CODES when a channel stops working. To find the current code:
  1. Open YouTube TV on the TV
  2. Navigate to the channel
  3. Run: adb shell dumpsys window | grep "mCurrentFocus"
  or check https://github.com/nicjansma/yttv-channel-ids (community-maintained)
"""

from __future__ import annotations

import os
import re
import subprocess

name = "youtube_tv"
commands = ["watch ", "tune to ", "put on ", "what's on "]

# YTTV channel codes — these rotate; update when a channel stops working.
# Format: friendly_name_lower -> yttv_video_id
# Source: community lists + manual verification.
CHANNEL_CODES: dict[str, str] = {
    # Sports
    "espn": "bj3v-DQPnNs",
    "espn2": "mN4oc_JUNEg",
    "espn news": "s-9DBBG2UMU",
    "fox sports 1": "U3vCrn_ZHaI",
    "fs1": "U3vCrn_ZHaI",
    "fox sports 2": "K0Ys3-X9mKc",
    "fs2": "K0Ys3-X9mKc",
    "nbc sports": "GSEhgzVRJLY",
    "nbc sports boston": "HMIqXrQ1AyI",
    "tnt": "Fk7UqKBCb3I",
    "tbs": "2yPFgSxMKOs",
    "mlb network": "ZLCuO4GKZA8",
    "nhl network": "nYFIv_Cid14",
    "nba tv": "x1oNLLElVWc",
    "golf channel": "d3KNXrLkEtY",
    # News
    "cnn": "HkN68Q91kCQ",
    "fox news": "F0pKlRUhGDs",
    "msnbc": "EWVYGpwuR2c",
    "nbc news now": "wMMuY32XMEA",
    "cnbc": "nF-4ZETXRQE",
    "bbc world news": "JJ6sOsEsFC4",
    "pbs newshour": "uxCwhX3HEIM",
    # Network
    "abc": "m4igcNHNpVk",
    "nbc": "8e-BIAXUb5Q",
    "cbs": "PUcRAfBD6hY",
    "fox": "GUE_FBFmAVw",
    "pbs": "GQcMW-dgHgM",
    "the cw": "bZjWNaOHNZQ",
    # Entertainment
    "amc": "0KGMPj7Lqok",
    "fx": "K5gbPTL2J48",
    "fxx": "D-nLZGkf7vM",
    "usa": "tRUDdPLb8Pk",
    "bravo": "c9FJZ6Hkpkw",
    "lifetime": "CqEuGBYOqvo",
    "hallmark": "z6HoJv5_tMI",
    "hgtv": "F5G7aQvdOig",
    "food network": "aAvWcXxZ6Mk",
    "tlc": "mh5e4kBfNmA",
    "discovery": "iGk5bTbFCeQ",
    "history": "0e_iFM-MBBM",
    "a&e": "J_aSjcsPIkA",
    "animal planet": "DLCqmFm93aE",
    "comedy central": "jJuJeukujJ8",
    "cartoon network": "6BtR4YyjFCw",
    "disney channel": "tITYJXQn5bM",
    # Kids
    "nickelodeon": "L49vH47A6zo",
    "nick jr": "vDHFNqtjrkY",
    "disney jr": "SQjkCXGbkY0",
}

_YTTV_PACKAGE = "com.google.android.apps.youtube.unplugged"
_YTTV_ACTIVITY = (
    f"{_YTTV_PACKAGE}/com.google.android.apps.youtube.tvunplugged.activity.MainActivity"
)
_WATCH_RE = re.compile(
    r"(?:watch|tune to|put on|what'?s on)\s+(.+?)(?:\s+now|please|for me)?$",
    re.IGNORECASE,
)


def _adb_host() -> str:
    return os.environ.get("YOUTUBE_TV_ADB_HOST", "")


def _adb_port() -> str:
    return os.environ.get("YOUTUBE_TV_ADB_PORT", "5555")


def _adb_path() -> str:
    return os.environ.get("YOUTUBE_TV_ADB_PATH", "adb")


def _resolve_channel(query: str) -> tuple[str | None, str | None]:
    """Return (channel_name, channel_code) for a query, or (None, None) if not found."""
    q = query.strip().lower()
    # Exact match first
    if q in CHANNEL_CODES:
        return q, CHANNEL_CODES[q]
    # Prefix / substring match
    for chan, code in CHANNEL_CODES.items():
        if q in chan or chan in q:
            return chan, code
    return None, None


def _adb_tune(channel_code: str) -> tuple[bool, str]:
    """Connect via ADB and launch YTTV channel. Return (success, message)."""
    host = _adb_host()
    if not host:
        return False, (
            "YOUTUBE_TV_ADB_HOST is not set. "
            "Add it to sandy.toml [youtube_tv] section with the TV's IP address."
        )

    adb = _adb_path()
    target = f"{host}:{_adb_port()}"

    # Connect (idempotent — safe to re-run if already connected)
    try:
        result = subprocess.run(
            [adb, "connect", target],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 and "connected" not in result.stdout.lower():
            return False, f"ADB connect failed: {result.stderr.strip() or result.stdout.strip()}"
    except FileNotFoundError:
        return False, f"adb binary not found at '{adb}'. Install Android Platform Tools."
    except subprocess.TimeoutExpired:
        return False, "ADB connect timed out. Is the TV on the same LAN?"

    # Launch YTTV with channel deeplink
    deep_link = f"https://tv.youtube.com/watch/{channel_code}"
    try:
        result = subprocess.run(
            [
                adb,
                "-s",
                target,
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                deep_link,
                "-n",
                _YTTV_ACTIVITY,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False, f"ADB launch failed: {result.stderr.strip() or result.stdout.strip()}"
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out launching YTTV."

    return True, deep_link


def handle(text: str, actor: str, progress=None) -> dict:
    m = _WATCH_RE.search(text.strip())
    if not m:
        return {
            "title": "YouTube TV",
            "text": "Usage: 'watch ESPN', 'tune to CNN', 'put on NBC Sports'.",
        }

    query = m.group(1).strip()
    channel_name, channel_code = _resolve_channel(query)

    if channel_name is None:
        known = ", ".join(sorted(CHANNEL_CODES))
        return {
            "title": "YouTube TV",
            "text": f"Channel '{query}' not found. Known channels: {known}.",
        }

    if progress:
        progress(f"Tuning to {channel_name.title()} via ADB...")

    success, detail = _adb_tune(channel_code)
    if not success:
        return {
            "title": "YouTube TV",
            "text": f"Failed to tune to {channel_name.title()}: {detail}",
        }

    return {
        "title": "YouTube TV",
        "text": f"Tuning to {channel_name.title()} on the Living Room TV.",
    }
