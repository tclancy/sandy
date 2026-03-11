from sandy.matcher import find_matches


class FakePlugin:
    def __init__(self, name, commands):
        self.name = name
        self.commands = commands

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


def test_find_matches_preserves_alphabetical_order():
    """Matches are returned in the same order plugins were provided."""
    alpha = FakePlugin("alpha", ["summarize"])
    beta = FakePlugin("beta", ["summarize"])
    charlie = FakePlugin("charlie", ["nope"])
    result = find_matches("summarize my day", [alpha, beta, charlie])
    assert result == [alpha, beta]
