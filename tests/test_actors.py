"""Tests for sandy/actors.py — identity resolution, permissions, and caps."""

from sandy.actors import can_use_plugin, get_owner, resolve_actor, resolve_caps


# ---------------------------------------------------------------------------
# Fixtures: config dicts
# ---------------------------------------------------------------------------

EMPTY_CONFIG: dict = {}

MINIMAL_CONFIG = {
    "sandy": {"owner": "tom"},
    "actors": {
        "tom": {"aliases": ["tclancy", "tpcii"]},
        "michelle": {"aliases": ["michelle", "mclancy"]},
    },
    "permissions": {
        "default_access": "private",
        "plugins": {
            "real_men": {"access": "public"},
            "cryptics": {"access": "public"},
            "help": {"access": "public"},
            "dispatch": {"access": "private", "allowed_actors": ["michelle"]},
        },
        "actions": {
            "print": {"actors": ["tom"]},
            "cast": {"actors": ["tom"]},
        },
    },
}


# ---------------------------------------------------------------------------
# get_owner
# ---------------------------------------------------------------------------


def test_get_owner_present():
    assert get_owner({"sandy": {"owner": "tom"}}) == "tom"


def test_get_owner_missing():
    assert get_owner({}) is None


def test_get_owner_empty_string():
    assert get_owner({"sandy": {"owner": ""}}) is None


def test_get_owner_strips_whitespace():
    assert get_owner({"sandy": {"owner": "  tom  "}}) == "tom"


# ---------------------------------------------------------------------------
# resolve_actor — backward compat (no actors config)
# ---------------------------------------------------------------------------


def test_resolve_no_actors_section():
    assert resolve_actor("anyone", EMPTY_CONFIG) == "anyone"


def test_resolve_empty_actors_section():
    assert resolve_actor("anyone", {"actors": {}}) == "anyone"


def test_resolve_empty_raw_string():
    assert resolve_actor("", EMPTY_CONFIG) is None


# ---------------------------------------------------------------------------
# resolve_actor — with actors configured
# ---------------------------------------------------------------------------


def test_resolve_owner_directly():
    assert resolve_actor("tom", MINIMAL_CONFIG) == "tom"


def test_resolve_by_alias():
    assert resolve_actor("tclancy", MINIMAL_CONFIG) == "tom"


def test_resolve_second_alias():
    assert resolve_actor("tpcii", MINIMAL_CONFIG) == "tom"


def test_resolve_other_actor():
    assert resolve_actor("michelle", MINIMAL_CONFIG) == "michelle"


def test_resolve_other_actor_alias():
    assert resolve_actor("mclancy", MINIMAL_CONFIG) == "michelle"


def test_resolve_unknown_actor():
    assert resolve_actor("stranger", MINIMAL_CONFIG) is None


def test_resolve_canonical_name_directly():
    assert resolve_actor("michelle", MINIMAL_CONFIG) == "michelle"


# ---------------------------------------------------------------------------
# can_use_plugin — backward compat
# ---------------------------------------------------------------------------


def test_can_use_no_permissions():
    assert can_use_plugin("anyone", "anything", EMPTY_CONFIG) is True


def test_can_use_unknown_actor_rejected():
    assert can_use_plugin(None, "real_men", MINIMAL_CONFIG) is False


# ---------------------------------------------------------------------------
# can_use_plugin — with permissions
# ---------------------------------------------------------------------------


def test_owner_can_use_private():
    assert can_use_plugin("tom", "dispatch", MINIMAL_CONFIG) is True


def test_owner_can_use_public():
    assert can_use_plugin("tom", "real_men", MINIMAL_CONFIG) is True


def test_non_owner_can_use_public():
    assert can_use_plugin("michelle", "real_men", MINIMAL_CONFIG) is True


def test_non_owner_blocked_from_private():
    assert can_use_plugin("michelle", "itguy", MINIMAL_CONFIG) is False


def test_non_owner_with_allowed_actors():
    assert can_use_plugin("michelle", "dispatch", MINIMAL_CONFIG) is True


def test_non_owner_not_in_allowed_actors():
    config = {
        "sandy": {"owner": "tom"},
        "actors": {"alice": {"aliases": []}},
        "permissions": {
            "default_access": "private",
            "plugins": {"dispatch": {"access": "private", "allowed_actors": ["michelle"]}},
        },
    }
    assert can_use_plugin("alice", "dispatch", config) is False


def test_default_access_public():
    config = {
        "sandy": {"owner": "tom"},
        "actors": {"bob": {"aliases": []}},
        "permissions": {"default_access": "public"},
    }
    assert can_use_plugin("bob", "any_plugin", config) is True


def test_unlisted_plugin_uses_default_access():
    assert can_use_plugin("michelle", "hardcover", MINIMAL_CONFIG) is False


# ---------------------------------------------------------------------------
# resolve_caps
# ---------------------------------------------------------------------------


def test_caps_unknown_actor():
    assert resolve_caps(None, MINIMAL_CONFIG) == frozenset()


def test_caps_owner_gets_all():
    caps = resolve_caps("tom", MINIMAL_CONFIG)
    assert "print" in caps
    assert "cast" in caps


def test_caps_non_owner_gets_none():
    caps = resolve_caps("michelle", MINIMAL_CONFIG)
    assert caps == frozenset()


def test_caps_non_owner_explicitly_granted():
    config = {
        "sandy": {"owner": "tom"},
        "permissions": {
            "actions": {"print": {"actors": ["tom", "michelle"]}},
        },
    }
    caps = resolve_caps("michelle", config)
    assert "print" in caps


def test_caps_no_permissions_owner():
    caps = resolve_caps("tom", {"sandy": {"owner": "tom"}})
    assert "print" in caps
    assert "cast" in caps


def test_caps_no_permissions_non_owner():
    caps = resolve_caps("bob", {"sandy": {"owner": "tom"}})
    assert caps == frozenset()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_resolve_case_insensitive():
    assert resolve_actor("TClancy", MINIMAL_CONFIG) == "tom"
    assert resolve_actor("TCLANCY", MINIMAL_CONFIG) == "tom"
    assert resolve_actor("Tom", MINIMAL_CONFIG) == "tom"


def test_resolve_alias_collision_with_canonical():
    """If an alias matches another actor's canonical name, first match wins (insertion order)."""
    config = {
        "sandy": {"owner": "tom"},
        "actors": {
            "alice": {"aliases": ["bob"]},
            "bob": {"aliases": []},
        },
    }
    assert resolve_actor("bob", config) == "alice"
