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


def _recent_iso(hours=2):
    """Return an ISO timestamp N hours ago (within today's results window)."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _too_far_iso(days=20):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_espn_event(
    date: str,
    name: str = "Red Sox at Yankees",
    status: str = "Scheduled",
    venue: str = "Fenway",
    competitors: list | None = None,
):
    comp = {"venue": {"fullName": venue}}
    if competitors is not None:
        comp["competitors"] = competitors
    return {
        "date": date,
        "name": name,
        "status": {"type": {"description": status}},
        "competitions": [comp],
    }


def _make_competitors(home_abbr="BOS", home_score="5", away_abbr="NYY", away_score="3"):
    return [
        {"homeAway": "home", "team": {"abbreviation": home_abbr}, "score": home_score},
        {"homeAway": "away", "team": {"abbreviation": away_abbr}, "score": away_score},
    ]


def _make_football_data_match(
    date: str,
    home: str = "Everton FC",
    away: str = "Arsenal FC",
    status: str = "SCHEDULED",
    home_score=None,
    away_score=None,
):
    return {
        "utcDate": date,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "competition": {"name": "Premier League"},
        "venue": "Goodison Park",
        "status": status,
        "score": {"fullTime": {"home": home_score, "away": away_score}},
    }


# ---- Module attributes ----


def test_name():
    assert sports.name == "sports"


def test_commands():
    assert "sports" in sports.commands
    assert "next game" in sports.commands
    assert "schedule" in sports.commands
    assert "scores" in sports.commands


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


# ---- _extract_espn_score ----


def test_extract_espn_score_returns_score():
    competitors = _make_competitors("BOS", "5", "NYY", "3")
    result = sports._extract_espn_score(competitors)
    assert "BOS" in result
    assert "NYY" in result
    assert "5" in result
    assert "3" in result


def test_extract_espn_score_empty_when_no_scores():
    competitors = [
        {"homeAway": "home", "team": {"abbreviation": "BOS"}, "score": ""},
        {"homeAway": "away", "team": {"abbreviation": "NYY"}, "score": ""},
    ]
    result = sports._extract_espn_score(competitors)
    assert result == ""


def test_extract_espn_score_empty_when_too_few_competitors():
    result = sports._extract_espn_score([])
    assert result == ""


# ---- _parse_espn_today_results ----


def test_parse_espn_today_results_returns_final_game():
    competitors = _make_competitors("BOS", "5", "NYY", "3")
    events = [_make_espn_event(_recent_iso(hours=3), status="Final", competitors=competitors)]
    results = sports._parse_espn_today_results(events, "Red Sox")
    assert len(results) == 1
    assert results[0]["status"] == "Final"
    assert results[0]["team"] == "Red Sox"
    assert "BOS" in results[0]["score"]


def test_parse_espn_today_results_returns_in_progress():
    competitors = _make_competitors("BOS", "2", "NYY", "1")
    events = [_make_espn_event(_recent_iso(hours=1), status="In Progress", competitors=competitors)]
    results = sports._parse_espn_today_results(events, "Red Sox")
    assert len(results) == 1
    assert results[0]["status"] == "In Progress"


def test_parse_espn_today_results_skips_future_games():
    events = [_make_espn_event(_future_iso(hours=2), status="Scheduled")]
    results = sports._parse_espn_today_results(events, "Red Sox")
    assert results == []


def test_parse_espn_today_results_skips_old_games():
    events = [_make_espn_event(_past_iso(days=2), status="Final")]
    results = sports._parse_espn_today_results(events, "Red Sox")
    assert results == []


def test_parse_espn_today_results_skips_scheduled_recent():
    # A game scheduled to start soon (within 24h) but not yet started
    events = [_make_espn_event(_recent_iso(hours=0), status="Scheduled")]
    results = sports._parse_espn_today_results(events, "Red Sox")
    assert results == []


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


# ---- _fetch_football_data_today_results ----


def test_fetch_football_data_today_results_finished():
    payload = {
        "matches": [
            _make_football_data_match(
                _recent_iso(hours=2),
                status="FINISHED",
                home_score=2,
                away_score=1,
            )
        ]
    }
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        results = sports._fetch_football_data_today_results("fake-key")
    assert len(results) == 1
    assert results[0]["status"] == "Final"
    assert "2" in results[0]["score"]


def test_fetch_football_data_today_results_in_play():
    payload = {
        "matches": [
            _make_football_data_match(
                _recent_iso(hours=1),
                status="IN_PLAY",
                home_score=1,
                away_score=0,
            )
        ]
    }
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        results = sports._fetch_football_data_today_results("fake-key")
    assert len(results) == 1
    assert results[0]["status"] == "In Progress"


def test_fetch_football_data_today_results_skips_scheduled():
    payload = {"matches": [_make_football_data_match(_future_iso(hours=3), status="SCHEDULED")]}
    with patch("sandy.plugins.sports.requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status.return_value = None
        results = sports._fetch_football_data_today_results("fake-key")
    assert results == []


def test_fetch_football_data_today_results_returns_empty_on_error():
    with patch("sandy.plugins.sports.requests.get", side_effect=Exception("network down")):
        results = sports._fetch_football_data_today_results("fake-key")
    assert results == []


# ---- handle ----


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
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        result = sports.handle("sports", "tom")

    assert "title" in result
    assert "text" in result
    assert "Everton" in result["text"]


def test_handle_shows_today_section_when_games_played():
    espn_events = [
        _make_espn_event(
            _recent_iso(hours=3),
            name="Celtics at Knicks",
            status="Final",
            competitors=_make_competitors("BOS", "108", "NYK", "115"),
        )
    ]
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=espn_events),
        patch.object(sports, "_fetch_football_data_next_game", return_value=None),
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        result = sports.handle("sports", "tom")

    assert "Today" in result["text"]
    assert "Final" in result["text"]


def test_handle_no_games():
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=[]),
        patch.object(sports, "_fetch_football_data_next_game", return_value=None),
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
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
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        sports.handle("sports", "tom", progress=progress_calls.append)

    assert len(progress_calls) == 5  # 4 ESPN teams + Everton


def test_handle_separates_today_and_upcoming_sections():
    """When there are both today's results and upcoming games, both sections appear."""
    recent_game = _make_espn_event(
        _recent_iso(hours=4),
        name="Bruins vs Leafs",
        status="Final",
        competitors=_make_competitors("BOS", "3", "TOR", "2"),
    )
    future_game = _make_espn_event(_future_iso(days=3), name="Bruins at Rangers")
    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=[recent_game, future_game]),
        patch.object(sports, "_fetch_football_data_next_game", return_value=None),
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        result = sports.handle("sports", "tom")

    assert "Today" in result["text"]
    assert "Upcoming" in result["text"]


# ---- _to_tz ----


def test_to_tz_converts_to_valid_iana_timezone():
    """A known IANA timezone name produces a tz-aware datetime in that zone."""
    from datetime import timezone as dt_tz
    from zoneinfo import ZoneInfo

    utc_dt = datetime(2026, 7, 4, 17, 0, tzinfo=dt_tz.utc)  # noon ET (UTC-4 in summer)
    result = sports._to_tz(utc_dt, "America/New_York")
    assert result.tzinfo is not None
    assert result.utcoffset() == ZoneInfo("America/New_York").utcoffset(utc_dt)
    # 17:00 UTC = 13:00 ET (UTC-4 during DST)
    assert result.hour == 13


def test_to_tz_falls_back_to_local_on_invalid_tz():
    """An unrecognised timezone string falls back to the system local timezone."""
    from datetime import timezone as dt_tz

    utc_dt = datetime(2026, 7, 4, 17, 0, tzinfo=dt_tz.utc)
    result = sports._to_tz(utc_dt, "Not/A/Real/TZ")
    # Should return a localised datetime without raising
    assert result.tzinfo is not None


def test_to_tz_with_none_returns_local():
    """Passing tz=None falls back to the system local timezone."""
    from datetime import timezone as dt_tz

    utc_dt = datetime(2026, 7, 4, 17, 0, tzinfo=dt_tz.utc)
    result = sports._to_tz(utc_dt, None)
    assert result.tzinfo is not None


# ---- timezone propagation in _parse_espn_next_game ----


def test_parse_espn_next_game_uses_requested_timezone():
    """_parse_espn_next_game formats dates in the requested timezone."""
    from datetime import timezone as dt_tz

    # Game at 17:00 UTC on a weekday in summer: 13:00 ET, 10:00 PT
    game_utc = (datetime.now(dt_tz.utc) + timedelta(days=3)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    iso = game_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    events = [_make_espn_event(iso, name="Red Sox at Yankees")]

    et_game = sports._parse_espn_next_game(events, "Red Sox", tz="America/New_York")
    pt_game = sports._parse_espn_next_game(events, "Red Sox", tz="America/Los_Angeles")

    assert et_game is not None
    assert pt_game is not None
    # The TZ abbreviation in the formatted string should differ
    assert et_game["date"] != pt_game["date"]


# ---- timezone propagation in handle ----


def test_handle_passes_tz_to_espn_parser():
    """handle() with tz= passes the timezone to _parse_espn_next_game."""
    espn_events = [_make_espn_event(_future_iso(days=2), name="Red Sox at Yankees")]
    captured = {}

    def mock_parse(events, label, tz=None):
        captured["tz"] = tz
        return None

    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=espn_events),
        patch.object(sports, "_parse_espn_next_game", side_effect=mock_parse),
        patch.object(sports, "_fetch_football_data_next_game", return_value=None),
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
        patch.object(sports, "_parse_espn_today_results", return_value=[]),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        sports.handle("sports", "tom", tz="America/Chicago")

    assert captured["tz"] == "America/Chicago"


def test_handle_passes_tz_to_football_data():
    """handle() with tz= passes the timezone to _fetch_football_data_next_game."""
    captured = {}

    def mock_fetch(api_key, tz=None):
        captured["tz"] = tz
        return None

    with (
        patch.object(sports, "_fetch_espn_schedule", return_value=[]),
        patch.object(sports, "_parse_espn_today_results", return_value=[]),
        patch.object(sports, "_parse_espn_next_game", return_value=None),
        patch.object(sports, "_fetch_football_data_today_results", return_value=[]),
        patch.object(sports, "_fetch_football_data_next_game", side_effect=mock_fetch),
        patch.dict("os.environ", {"FOOTBALL_DATA_API_KEY": "fake-key"}),
    ):
        sports.handle("sports", "tom", tz="Europe/London")

    assert captured["tz"] == "Europe/London"
