"""Tests for sandy.voice — the tiny flourishes that make Sandy feel like a person.

The behaviour under test comes straight from Eugene Wei's *I Want Sandy* post
(linked in CLAUDE.md): a 3 a.m. reply that opened with "Wow! You're up late!"
was "simple to code, powerfully effective". The design constraint that keeps it
from turning into noise is the *silence* — Sandy remarks only on hours a person
would remark on, and says nothing at 2 p.m.
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sandy import voice

pytestmark = pytest.mark.real_voice


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 24, hour, minute)


def _first(options):
    """Deterministic stand-in for random.choice."""
    return options[0]


class TestTimeOfDayAside:
    def test_remarks_on_the_small_hours(self):
        aside = voice.time_of_day_aside(_at(3), "tom", choice=_first)

        assert aside is not None
        assert "late" in aside.lower()

    @pytest.mark.parametrize("hour", [7, 9, 12, 14, 17, 20, 22])
    def test_says_nothing_during_ordinary_hours(self, hour):
        assert voice.time_of_day_aside(_at(hour), "tom", choice=_first) is None

    def test_remarks_before_dawn_too_but_differently(self):
        night = voice.time_of_day_aside(_at(3), "tom", choice=_first)
        dawn = voice.time_of_day_aside(_at(5), "tom", choice=_first)

        assert dawn is not None
        assert dawn != night
        assert "early" in dawn.lower()

    def test_addresses_the_actor_by_name_capitalised(self):
        assert "Tom" in voice.time_of_day_aside(_at(2), "tom", choice=_first)

    def test_falls_back_to_a_nameless_phrasing_for_an_empty_actor(self):
        aside = voice.time_of_day_aside(_at(2), "", choice=_first)

        assert aside is not None
        assert "{" not in aside
        assert "  " not in aside
        assert ", ." not in aside

    def test_leaves_an_already_capitalised_name_alone(self):
        assert "McTavish" in voice.time_of_day_aside(_at(2), "McTavish", choice=_first)

    def test_offers_more_than_one_phrasing_per_window(self):
        """A single fixed string would read as a template on the second use."""
        variants = {
            voice.time_of_day_aside(_at(3), "tom", choice=lambda opts: opts[i])
            for i in range(len(voice.LATE_NIGHT))
        }

        assert len(variants) > 1

    def test_the_23rd_hour_counts_as_late(self):
        assert voice.time_of_day_aside(_at(23, 30), "tom", choice=_first) is not None

    def test_the_7th_hour_does_not_count_as_early(self):
        assert voice.time_of_day_aside(_at(7, 0), "tom", choice=_first) is None


class TestAttachAside:
    def test_carries_the_aside_in_its_own_field(self):
        """Not spliced into ``text`` — that broke three things in Slack at once:
        code-fence promotion, block ordering, and the 3000-char budget."""
        result = voice.attach_aside({"text": "42 tracks added."}, "You're up late.")

        assert result["aside"] == "You're up late."
        assert result["text"] == "42 tracks added."

    def test_the_aside_leads_so_renderers_that_iterate_keys_put_it_first(self):
        result = voice.attach_aside({"title": "Music", "text": "Done."}, "You're up late.")

        assert next(iter(result)) == "aside"

    def test_a_missing_aside_returns_the_response_untouched(self):
        response = {"text": "42 tracks added."}

        assert voice.attach_aside(response, None) == response
        assert "aside" not in voice.attach_aside(response, None)

    def test_does_not_mutate_the_caller_s_response(self):
        response = {"text": "42 tracks added."}

        voice.attach_aside(response, "You're up late.")

        assert response == {"text": "42 tracks added."}

    def test_preserves_the_other_fields(self):
        result = voice.attach_aside(
            {"title": "Music", "text": "Done.", "links": [{"label": "x", "url": "y"}]},
            "You're up late.",
        )

        assert result["title"] == "Music"
        assert result["links"] == [{"label": "x", "url": "y"}]


class TestDidNotUnderstand:
    def test_quotes_back_what_was_said(self):
        assert "wibble the frobnitz" in voice.did_not_understand("wibble the frobnitz")

    def test_points_at_help_so_the_reply_is_actionable(self):
        assert "help" in voice.did_not_understand("wibble").lower()

    def test_truncates_an_absurdly_long_command(self):
        reply = voice.did_not_understand("x" * 5000)

        assert len(reply) < 400

    def test_copes_with_an_empty_command(self):
        assert voice.did_not_understand("").strip() != ""

    def test_defuses_slack_mentions_in_the_echo(self):
        """Slack delivers ``@channel`` as ``<!channel>``. Echoing it verbatim
        would make Sandy ping the channel to say she didn't understand."""
        reply = voice.did_not_understand("<!channel> <@U123> do the thing")

        assert "<!channel>" not in reply
        assert "<@U123>" not in reply
        assert "do the thing" in reply


class TestOpeningAside:
    def test_resolves_the_hour_in_the_requesting_user_s_timezone(self):
        """09:00 UTC is 05:00 in New York — early there, ordinary in London."""
        now = datetime(2026, 8, 24, 9, 0, tzinfo=ZoneInfo("UTC"))

        ny = voice.opening_aside("tom", tz="America/New_York", now=now, choice=_first)
        london = voice.opening_aside("tom", tz="Europe/London", now=now, choice=_first)

        assert ny is not None
        assert london is None

    def test_falls_back_to_the_config_timezone(self):
        now = datetime(2026, 8, 24, 9, 0, tzinfo=ZoneInfo("UTC"))
        config = {"sandy": {"timezone": "America/New_York"}}

        assert voice.opening_aside("tom", config=config, now=now, choice=_first) is not None

    def test_an_unknown_timezone_does_not_raise(self):
        now = datetime(2026, 8, 24, 3, 0, tzinfo=ZoneInfo("UTC"))

        assert voice.opening_aside("tom", tz="Mars/Olympus", now=now, choice=_first) is not None

    def test_the_default_clock_is_the_machine_s_own_when_no_zone_is_given(self):
        """With no tz anywhere, Sandy must read the local clock.

        Defaulting to UTC silently shifts the whole window: on US Eastern it
        would greet you at 8pm and stay silent at 3am — the one case the
        feature exists for. Masked during manual testing because the repo's
        own ``sandy.toml`` sets a timezone (sandy#183 review).
        """
        original = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Auckland"
        time.tzset()
        try:
            resolved = voice._resolve_now(None, None)
            assert resolved.tzinfo is not None
            assert resolved.utcoffset() == datetime.now(ZoneInfo("Pacific/Auckland")).utcoffset()
        finally:
            if original is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = original
            time.tzset()

    def test_a_non_string_timezone_does_not_raise(self):
        """Slack hands us whatever is in the user profile's ``tz`` field."""
        now = datetime(2026, 8, 24, 3, 0, tzinfo=ZoneInfo("UTC"))

        assert voice.opening_aside("tom", tz=5, now=now, choice=_first) is not None

    def test_the_default_clock_lands_in_the_requested_zone(self):
        """A naive ``datetime.now()`` silently ignores tz — 3am ET greeted a
        London user at 8am on the first real CLI run (sandy#183)."""
        auckland = voice._resolve_now("Pacific/Auckland", None)
        london = voice._resolve_now("Europe/London", None)

        assert auckland.tzinfo is not None
        assert london.tzinfo is not None
        assert auckland.utcoffset() != london.utcoffset()
        assert auckland.hour != london.hour

    def test_a_naive_clock_is_taken_to_already_be_in_the_target_zone(self):
        """``_at(3)`` with tz='America/New_York' means 3am in New York, not UTC."""
        naive = datetime(2026, 8, 24, 3, 0)

        assert voice._resolve_now("America/New_York", naive) == naive

    def test_a_malformed_sandy_section_leaves_flourishes_on(self):
        """A hand-edited TOML shouldn't be able to silence Sandy by accident."""
        assert voice.flourishes_enabled({"sandy": "not-a-table"}) is True

    def test_is_silent_when_flourishes_are_switched_off(self):
        """Wei's own caveat: 'perhaps you could choose whether to turn it on or off.'"""
        now = datetime(2026, 8, 24, 3, 0, tzinfo=ZoneInfo("UTC"))
        config = {"sandy": {"flourishes": "no"}}

        assert voice.opening_aside("tom", config=config, now=now, choice=_first) is None

    def test_is_on_by_default(self):
        now = datetime(2026, 8, 24, 3, 0, tzinfo=ZoneInfo("UTC"))

        assert voice.opening_aside("tom", config={}, now=now, choice=_first) is not None
