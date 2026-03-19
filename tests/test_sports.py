"""Tests for the sports schedule plugin."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from sandy.plugins import sports


def _future_iso(days=3, hours=19):
    """Return an ISO timestamp N days from now."""
    dt = datetime.now(timezone.utc) + timedelta(days=days, hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_iso(days=2):
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _too_far_iso(days=20):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_espn_event(
    date: str,
    name: str = "Red Sox at Yankees",
    status: str = "Scheduled",
    venue: str = "Fenway",
):
    return {
        "date": date,
        "name": name,
        "status": {"type": {"description": status}},
        "competitions": [{"venue": {"fullName": venue}}],
    }


def _make_football_data_match(date: str, home: str = "Everton FC", away: str = "Arsenal FC"):
    return {
        "utcDate": date,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "competition": {"name": "Premier League"},
        "venue": "Goodison Park",
    }


# ---- Module attributes ----


def test_name():
    assert sports.name == "sports"


def test_commands():
    assert "sports" in sports.commands
    assert "next game" in sports.commands
    assert "schedule" in sports.commands


# ---- _fetch_espn_schedule ----


def test_fetch_espn_schedule_returns_events():
    payload = {"events": [_make_espn_event(_future_iso())]}
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        result = sports._fetch_espn_schedule("baseball", "mlb", "2")
    assert len(result) == 1


def test_fetch_espn_schedule_returns_empty_on_error():
    with patch("sandy.plugins.sports.requests.get", side_effect=Exception("network down")):
        result = sports._fetch_espn_schedule("baseball", "mlb", "2")
    assert result == []


# ---- _parse_espn_next_game ----


def test_parse_espn_next_game_returns_upcoming():
    events = [_make_espn_event(_future_iso(days=3))]
    game = sports._parse_espn_next_game(events, "Red Sox")
    assert game is not None
    assert game["team"] == "Red Sox"
    assert "Red Sox" in game["game"]
    assert game["date"]


def test_parse_espn_next_game_skips_past_games():
    events = [_make_espn_event(_past_iso(days=2))]
    game = sports._parse_espn_next_game(events, "Red Sox")
    assert game is None


def test_parse_espn_next_game_skips_too_far_future():
    events = [_make_espn_event(_too_far_iso(days=20))]
    game = sports._parse_espn_next_game(events, "Red Sox")
    assert game is None


def test_parse_espn_next_game_skips_final():
    events = [_make_espn_event(_future_iso(days=1), status="Final")]
    game = sports._parse_espn_next_game(events, "Red Sox")
    assert game is None


def test_parse_espn_next_game_returns_first_upcoming():
    events = [
        _make_espn_event(_past_iso(), status="Final", name="Game 1"),
        _make_espn_event(_future_iso(days=2), name="Game 2"),
        _make_espn_event(_future_iso(days=5), name="Game 3"),
    ]
    game = sports._parse_espn_next_game(events, "Red Sox")
    assert game["game"] == "Game 2"


def test_parse_espn_next_game_includes_venue():
    events = [_make_espn_event(_future_iso(), venue="Fenway Park")]
    game = sports._parse_espn_next_game(events, "Red Sox")
    assert game["venue"] == "Fenway Park"


# ---- _fetch_football_data_next_game ----


def test_fetch_football_data_returns_game():
    payload = {"matches": [_make_football_data_match(_future_iso(days=4))]}
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        game = sports._fetch_football_data_next_game("fake-key")
    assert game is not None
    assert game["team"] == "Everton"
    assert "Everton FC" in game["game"]


def test_fetch_football_data_returns_none_on_error():
    with patch("sandy.plugins.sports.requests.get", side_effect=Exception("network down")):
        game = sports._fetch_football_data_next_game("fake-key")
    assert game is None


def test_fetch_football_data_skips_too_far():
    payload = {"matches": [_make_football_data_match(_too_far_iso(days=25))]}
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        game = sports._fetch_football_data_next_game("fake-key")
    assert game is None


def test_fetch_football_data_includes_venue():
    payload = {"matches": [_make_football_data_match(_future_iso(days=3))]}
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        game = sports._fetch_football_data_next_game("fake-key")
    assert game["venue"] == "Goodison Park"


# ---- handle ----


def _make_espn_side_effect(games_by_team: dict):
    """Return a side_effect for _fetch_espn_schedule calls."""
    call_order = [
        ("baseball", "mlb", "2"),
        ("football", "nfl", "17"),
        ("basketball", "nba", "2"),
        ("hockey", "nhl", "1"),
    ]
    responses = []
    for sport, league, team_id in call_order:
        labels = {
            "baseball": "Red Sox",
            "football": "Patriots",
            "basketball": "Celtics",
            "hockey": "Bruins",
        }
        label = labels[sport]
        if label in games_by_team:
            responses.append([_make_espn_event(games_by_team[label], name=f"{label} game")])
        else:
            responses.append([])
    return responses


def test_handle_returns_upcoming_games():
    espn_events = [_make_espn_event(_future_iso(days=2), name="Red Sox at Yankees")]
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=espn_events),
        patch.object(
            sports,
            "_fetch_football_data_next_game",
            return_value={
                "team": "Everton",
                "game": "Everton vs Arsenal",
                "date": "Saturday Mar 22, 3:00 PM EDT",
                "venue": "Goodison Park",
            },
        ),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        result = sports.handle("sports", "tom")

    assert "title" in result
    assert "text" in result
    assert "Everton" in result["text"]


def test_handle_no_games():
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=[]),
        patch.object(sports, "_fetch_football_data_next_game", return_value=None),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        result = sports.handle("sports", "tom")

    assert "No games" in result["text"]


def test_handle_missing_football_data_key():
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=[]),
        patch.dict("os.environ", {}, clear=True),
    ):
        result = sports.handle("sports", "tom")

    assert "FOOTBALL_DATA_API_KEY not set" in result["text"]


def test_handle_calls_progress():
    progress_calls = []
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=[]),
        patch.object(sports, "_fetch_football_data_next_game", return_value=None),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        sports.handle("sports", "tom", progress=progress_calls.append)

    assert len(progress_calls) == 5  # 4 ESPN teams + Everton
