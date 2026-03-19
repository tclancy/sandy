"""Sports schedule plugin for Sandy.

Returns the next upcoming game (within 2 weeks) for Tom's favorite teams:
  - Boston Red Sox (MLB)
  - New England Patriots (NFL)
  - Boston Celtics (NBA)
  - Boston Bruins (NHL)
  - Everton (Premier League)

Data sources:
  - US sports: ESPN unofficial API (site.api.espn.com)
  - Soccer: football-data.org (requires FOOTBALL_DATA_API_KEY in env/config)

Game times are converted to the local system timezone.
"""

import os
from datetime import datetime, timezone, timedelta

import requests

name = "sports"
commands = ["sports", "game today", "next game", "schedule", "games"]

# Days ahead to search; if no game within this window the team is "out of season"
LOOKAHEAD_DAYS = 14

# ESPN team IDs per sport/league
_ESPN_TEAMS = [
    {"label": "Red Sox", "sport": "baseball", "league": "mlb", "team_id": "2"},
    {"label": "Patriots", "sport": "football", "league": "nfl", "team_id": "17"},
    {"label": "Celtics", "sport": "basketball", "league": "nba", "team_id": "2"},
    {"label": "Bruins", "sport": "hockey", "league": "nhl", "team_id": "1"},
]

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# football-data.org Everton team ID (Premier League)
_EVERTON_TEAM_ID = 62
_FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"


def _fetch_espn_schedule(sport: str, league: str, team_id: str) -> list[dict]:
    """Return raw ESPN schedule events for a team, or [] on error."""
    url = f"{_ESPN_BASE}/{sport}/{league}/teams/{team_id}/schedule"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json().get("events", [])
    except Exception:
        return []


def _parse_espn_next_game(events: list[dict], label: str) -> dict | None:
    """Find the next scheduled game from ESPN events within LOOKAHEAD_DAYS.

    Returns a normalised game dict, or None if no game is found soon enough.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=LOOKAHEAD_DAYS)

    for event in events:
        status = event.get("status", {}).get("type", {}).get("description", "")
        if status == "Final":
            continue

        date_str = event.get("date", "")
        if not date_str:
            continue
        try:
            game_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        if game_dt < now or game_dt > cutoff:
            continue

        competitions = event.get("competitions", [])
        venue = competitions[0].get("venue", {}).get("fullName", "") if competitions else ""
        name_str = event.get("name", label)
        local_dt = game_dt.astimezone()

        return {
            "team": label,
            "game": name_str,
            "date": local_dt.strftime("%A %b %-d, %-I:%M %p %Z"),
            "venue": venue,
        }

    return None


def _fetch_football_data_next_game(api_key: str) -> dict | None:
    """Return Everton's next upcoming PL match within LOOKAHEAD_DAYS, or None."""
    url = f"{_FOOTBALL_DATA_BASE}/teams/{_EVERTON_TEAM_ID}/matches"
    params = {"status": "SCHEDULED", "limit": 5}
    headers = {"X-Auth-Token": api_key}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
    except Exception:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=LOOKAHEAD_DAYS)

    for match in matches:
        date_str = match.get("utcDate", "")
        if not date_str:
            continue
        try:
            game_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        if game_dt < now or game_dt > cutoff:
            continue

        home = match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("name", "?")
        competition = match.get("competition", {}).get("name", "Premier League")
        local_dt = game_dt.astimezone()

        return {
            "team": "Everton",
            "game": f"{home} vs {away} ({competition})",
            "date": local_dt.strftime("%A %b %-d, %-I:%M %p %Z"),
            "venue": match.get("venue", ""),
        }

    return None


def _format_game(g: dict) -> str:
    """Format a game dict into a display line."""
    line = f"**{g['team']}**: {g['game']}"
    if g["date"]:
        line += f" — {g['date']}"
    if g["venue"]:
        line += f" @ {g['venue']}"
    return line


def handle(text: str, actor: str, progress=None) -> dict:
    games = []

    for team in _ESPN_TEAMS:
        if progress:
            progress(f"Checking {team['label']}…")
        events = _fetch_espn_schedule(team["sport"], team["league"], team["team_id"])
        game = _parse_espn_next_game(events, team["label"])
        if game:
            games.append(game)

    # Everton via football-data.org
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if progress:
        progress("Checking Everton…")
    if api_key:
        game = _fetch_football_data_next_game(api_key)
        if game:
            games.append(game)
    else:
        # Key not configured — note it but don't fail
        games.append(
            {"team": "Everton", "game": "FOOTBALL_DATA_API_KEY not set", "date": "", "venue": ""}
        )

    if not games:
        return {"text": f"No games in the next {LOOKAHEAD_DAYS} days for any of your teams."}

    return {
        "title": "Upcoming games (next 2 weeks):",
        "text": "\n".join(_format_game(g) for g in games),
    }
