"""Sports schedule plugin for Sandy.

Returns today's results / live scores (top section) plus the next upcoming
game (within 2 weeks) for Tom's favorite teams:
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
commands = ["sports", "game today", "next game", "schedule", "games", "scores"]

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


def _extract_espn_score(competitors: list[dict]) -> str:
    """Extract 'Away 2–Home 3' style score string from ESPN competitors list."""
    if len(competitors) < 2:
        return ""
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return ""
    hs = home.get("score", "")
    as_ = away.get("score", "")
    if not hs or not as_:
        return ""
    ht = home.get("team", {}).get("abbreviation") or home.get("team", {}).get("displayName", "")
    at = away.get("team", {}).get("abbreviation") or away.get("team", {}).get("displayName", "")
    return f"{at} {as_}–{ht} {hs}"


def _parse_espn_today_results(events: list[dict], label: str) -> list[dict]:
    """Find finished or in-progress games from the last 24 hours in ESPN events.

    Uses the same event list already fetched for the upcoming-game query — no
    extra API call needed.
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)

    results = []
    for event in events:
        date_str = event.get("date", "")
        if not date_str:
            continue
        try:
            game_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        # Only games that started in the last 24 hours
        if not (lookback <= game_dt <= now):
            continue

        status = event.get("status", {}).get("type", {}).get("description", "")
        if status in ("Scheduled", "Postponed", "Cancelled", "Delayed"):
            continue

        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        score_str = _extract_espn_score(competitors)
        status_label = "Final" if status == "Final" else "In Progress"

        results.append(
            {
                "team": label,
                "game": event.get("name", label),
                "score": score_str,
                "status": status_label,
            }
        )

    return results


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


def _fetch_football_data_today_results(api_key: str) -> list[dict]:
    """Fetch Everton's in-progress or finished matches from today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"{_FOOTBALL_DATA_BASE}/teams/{_EVERTON_TEAM_ID}/matches"
    params = {"dateFrom": today, "dateTo": today}
    headers = {"X-Auth-Token": api_key}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
    except Exception:
        return []

    results = []
    for match in matches:
        status = match.get("status", "")
        if status in ("SCHEDULED", "TIMED", "CANCELLED", "POSTPONED"):
            continue

        home = match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("name", "?")
        competition = match.get("competition", {}).get("name", "Premier League")

        ft = match.get("score", {}).get("fullTime", {})
        hs = ft.get("home")
        as_ = ft.get("away")
        score_str = f"{hs}–{as_}" if hs is not None and as_ is not None else ""
        status_label = "Final" if status == "FINISHED" else "In Progress"

        results.append(
            {
                "team": "Everton",
                "game": f"{home} vs {away} ({competition})",
                "score": score_str,
                "status": status_label,
            }
        )

    return results


def _format_game(g: dict) -> str:
    """Format an upcoming game dict into a display line."""
    line = f"**{g['team']}**: {g['game']}"
    if g["date"]:
        line += f" — {g['date']}"
    if g["venue"]:
        line += f" @ {g['venue']}"
    return line


def _format_today_result(g: dict) -> str:
    """Format a today's result/live-score dict into a display line."""
    status = g["status"]
    score = g.get("score", "")
    line = f"**{g['team']}** ({status}): {g['game']}"
    if score:
        line += f" — {score}"
    return line


def _build_response(today_games: list[dict], upcoming_games: list[dict]) -> dict:
    """Assemble the final response dict from collected game lists."""
    sections = []
    if today_games:
        lines = [_format_today_result(g) for g in today_games]
        sections.append("*Today's Results & Live Scores:*\n" + "\n".join(lines))
    if upcoming_games:
        lines = [_format_game(g) for g in upcoming_games]
        header = f"*Upcoming (next {LOOKAHEAD_DAYS} days):*" if today_games else ""
        sections.append((header + "\n" + "\n".join(lines)).lstrip() if header else "\n".join(lines))
    if not sections:
        return {"text": f"No games today or in the next {LOOKAHEAD_DAYS} days."}
    return {"title": "Sports Update", "text": "\n\n".join(sections)}


def handle(text: str, actor: str, progress=None) -> dict:
    today_games: list[dict] = []
    upcoming_games: list[dict] = []

    for team in _ESPN_TEAMS:
        if progress:
            progress(f"Checking {team['label']}…")
        events = _fetch_espn_schedule(team["sport"], team["league"], team["team_id"])
        today_games.extend(_parse_espn_today_results(events, team["label"]))
        game = _parse_espn_next_game(events, team["label"])
        if game:
            upcoming_games.append(game)

    # Everton via football-data.org
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if progress:
        progress("Checking Everton…")
    if api_key:
        today_games.extend(_fetch_football_data_today_results(api_key))
        game = _fetch_football_data_next_game(api_key)
        if game:
            upcoming_games.append(game)
    else:
        upcoming_games.append(
            {"team": "Everton", "game": "FOOTBALL_DATA_API_KEY not set", "date": "", "venue": ""}
        )

    return _build_response(today_games, upcoming_games)
