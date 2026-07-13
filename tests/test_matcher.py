from sandy.matcher import find_matches, normalize


class FakePlugin:
    def __init__(self, name, commands, match_mode=None):
        self.name = name
        self.commands = commands
        if match_mode is not None:
            self.match_mode = match_mode

    def handle(self, text, actor):
        return f"{self.name} handled it"


def test_find_matches_exact_phrase():
    plugin = FakePlugin("music", ["find me new music"])
    result = find_matches("find me new music", [plugin])
    assert result == [plugin]


def test_find_matches_substring():
    plugin = FakePlugin("music", ["new music"])
    result = find_matches("please find me new music today", [plugin])
    assert result == [plugin]


def test_find_matches_case_insensitive():
    plugin = FakePlugin("music", ["find me new music"])
    result = find_matches("FIND ME NEW MUSIC", [plugin])
    assert result == [plugin]


def test_find_matches_no_match():
    plugin = FakePlugin("music", ["find me new music"])
    result = find_matches("what is the weather", [plugin])
    assert result == []


def test_find_matches_multiple_plugins_match():
    alpha = FakePlugin("alpha", ["hello"])
    beta = FakePlugin("beta", ["hello"])
    result = find_matches("hello", [alpha, beta])
    assert result == [alpha, beta]


def test_find_matches_multiple_commands_on_plugin():
    plugin = FakePlugin("music", ["find me new music", "new music"])
    result = find_matches("new music", [plugin])
    assert result == [plugin]


def test_find_matches_plugin_not_duplicated():
    """A plugin matching on multiple commands should only appear once."""
    plugin = FakePlugin("music", ["new music", "music"])
    result = find_matches("new music", [plugin])
    assert result == [plugin]


def test_normalize_strips_punctuation():
    assert normalize("crossword, please!") == "crossword"


def test_normalize_strips_please_from_end():
    assert normalize("new music please") == "new music"


def test_normalize_strips_please_from_start():
    assert normalize("please find me a crossword") == "find me a crossword"


def test_normalize_strips_thanks():
    assert normalize("new music thanks") == "new music"


def test_normalize_strips_thank_you():
    assert normalize("new music thank you") == "new music"


def test_normalize_case_insensitive():
    assert normalize("CROSSWORD PLEASE") == "crossword"


def test_normalize_collapses_whitespace():
    assert normalize("new   music") == "new music"


def test_normalize_please_mid_sentence_preserved():
    """'please' in the middle of a command is not stripped."""
    assert normalize("please find me new music please") == "find me new music"


def test_find_matches_normalizes_before_matching():
    plugin = FakePlugin("crossword", ["crossword"])
    result = find_matches("crossword, please!", [plugin])
    assert result == [plugin]


def test_find_matches_preserves_alphabetical_order():
    """Matches are returned in the same order plugins were provided."""
    alpha = FakePlugin("alpha", ["summarize"])
    beta = FakePlugin("beta", ["summarize"])
    charlie = FakePlugin("charlie", ["nope"])
    result = find_matches("summarize my day", [alpha, beta, charlie])
    assert result == [alpha, beta]


# `match_mode = "prefix"` — an opt-in stricter matcher for generic leaf-word
# commands (namely `help`), so that "itguy logs --help" doesn't drag the help
# plugin in alongside the itguy plugin (#139).


def test_prefix_mode_matches_exact_text():
    plugin = FakePlugin("help", ["help"], match_mode="prefix")
    assert find_matches("help", [plugin]) == [plugin]


def test_prefix_mode_matches_when_command_is_first_word():
    plugin = FakePlugin("help", ["help"], match_mode="prefix")
    assert find_matches("help me please", [plugin]) == [plugin]


def test_prefix_mode_does_not_match_when_command_appears_mid_sentence():
    """The key #139 case: `itguy logs --help` normalizes to `itguy logs help`
    and the help plugin must NOT match — otherwise Sandy dumps the default
    help alongside itguy's own logs output."""
    plugin = FakePlugin("help", ["help"], match_mode="prefix")
    assert find_matches("itguy logs help", [plugin]) == []


def test_prefix_mode_does_not_match_partial_word():
    """`help` at prefix must be a whole word, not a stem — `helpful` should
    not match."""
    plugin = FakePlugin("help", ["help"], match_mode="prefix")
    assert find_matches("helpful", [plugin]) == []


def test_prefix_mode_survives_polite_wrapping():
    """`normalize` strips leading `please` before matching, so `please help`
    still matches prefix."""
    plugin = FakePlugin("help", ["help"], match_mode="prefix")
    assert find_matches("please help", [plugin]) == [plugin]


def test_substring_mode_still_default_for_untagged_plugins():
    """Sanity: adding match_mode support must not change matching for the
    plugins that don't declare it — most Sandy plugins depend on substring
    matching to catch commands embedded in polite framing."""
    plugin = FakePlugin("music", ["new music"])
    assert find_matches("please play me some new music today", [plugin]) == [plugin]
