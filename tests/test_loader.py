import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sandy.plugins
from sandy.loader import load_plugins
from sandy.matcher import find_matches


@pytest.fixture(autouse=True)
def no_entry_points(monkeypatch):
    """Suppress real entry-point discovery in all loader tests by default.

    Tests that exercise entry-point loading call monkeypatch.setattr again
    to override this fixture with their own mock list.
    """
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points",
        lambda group=None, **kwargs: [],
    )


def _write_plugin(tmp_path, filename, content):
    """Helper to write a plugin file into a temp directory."""
    filepath = tmp_path / filename
    filepath.write_text(textwrap.dedent(content))
    return filepath


def test_load_valid_plugin(tmp_path):
    _write_plugin(
        tmp_path,
        "greet.py",
        """
        name = "greeter"
        commands = ["hello", "hi"]
        def handle(text, actor):
            return "hey there"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 1
    assert plugins[0].name == "greeter"
    assert plugins[0].commands == ["hello", "hi"]
    assert plugins[0].handle("hello", "tom") == "hey there"


def test_skip_malformed_plugin_missing_handle(tmp_path, capsys):
    _write_plugin(
        tmp_path,
        "bad.py",
        """
        name = "bad"
        commands = ["oops"]
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 0
    captured = capsys.readouterr()
    assert "bad.py" in captured.err


def test_skip_malformed_plugin_missing_name(tmp_path, capsys):
    _write_plugin(
        tmp_path,
        "noname.py",
        """
        commands = ["test"]
        def handle(text, actor):
            return "ok"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 0
    captured = capsys.readouterr()
    assert "noname.py" in captured.err


def test_skip_init_file(tmp_path):
    _write_plugin(tmp_path, "__init__.py", "")
    _write_plugin(
        tmp_path,
        "good.py",
        """
        name = "good"
        commands = ["test"]
        def handle(text, actor):
            return "ok"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 1
    assert plugins[0].name == "good"


def test_alphabetical_order_by_filename(tmp_path):
    _write_plugin(
        tmp_path,
        "beta.py",
        """
        name = "beta"
        commands = ["b"]
        def handle(text, actor):
            return "beta"
    """,
    )
    _write_plugin(
        tmp_path,
        "alpha.py",
        """
        name = "alpha"
        commands = ["a"]
        def handle(text, actor):
            return "alpha"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert [p.name for p in plugins] == ["alpha", "beta"]


def test_skip_non_callable_handle(tmp_path, capsys):
    _write_plugin(
        tmp_path,
        "notcallable.py",
        """
        name = "bad"
        commands = ["test"]
        handle = "not a function"
    """,
    )
    plugins = load_plugins(str(tmp_path))
    assert len(plugins) == 0
    captured = capsys.readouterr()
    assert "notcallable.py" in captured.err


def test_empty_directory(tmp_path):
    plugins = load_plugins(str(tmp_path))
    assert plugins == []


def test_inactive_plugin_skipped(tmp_path):
    _write_plugin(
        tmp_path,
        "myplugin.py",
        """
        name = "myplugin"
        commands = ["do thing"]
        def handle(text, actor):
            return "done"
    """,
    )
    config = {"myplugin": {"active": "no"}}
    plugins = load_plugins(str(tmp_path), config)
    assert len(plugins) == 0


def test_active_plugin_included(tmp_path):
    _write_plugin(
        tmp_path,
        "myplugin.py",
        """
        name = "myplugin"
        commands = ["do thing"]
        def handle(text, actor):
            return "done"
    """,
    )
    config = {"myplugin": {"active": "yes"}}
    plugins = load_plugins(str(tmp_path), config)
    assert len(plugins) == 1


# ---------------------------------------------------------------------------
# Entry-point plugin discovery
# ---------------------------------------------------------------------------


def _make_ep_module(name, commands=None):
    """Build a minimal module that satisfies Sandy's plugin contract."""
    mod = types.ModuleType(name)
    mod.name = name
    mod.commands = commands or [f"{name} go"]
    mod.handle = lambda text, actor: {"title": name, "text": "ok"}
    return mod


def _make_mock_ep(ep_name, module):
    ep = MagicMock()
    ep.name = ep_name
    ep.load.return_value = module
    return ep


def test_entry_point_plugin_loaded(tmp_path, monkeypatch):
    """A valid entry-point plugin is discovered and returned."""
    fake_mod = _make_ep_module("extplugin")
    mock_ep = _make_mock_ep("extplugin", fake_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert len(plugins) == 1
    assert plugins[0].name == "extplugin"


def test_entry_point_plugin_merged_with_file_plugins(tmp_path, monkeypatch):
    """File-based and entry-point plugins are both returned."""
    _write_plugin(
        tmp_path,
        "local.py",
        """
        name = "local"
        commands = ["local go"]
        def handle(text, actor):
            return "local"
    """,
    )
    fake_mod = _make_ep_module("extplugin")
    mock_ep = _make_mock_ep("extplugin", fake_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    names = [p.name for p in plugins]
    assert "local" in names
    assert "extplugin" in names


def test_file_plugin_wins_over_entry_point_with_same_name(tmp_path, monkeypatch):
    """When names collide, the file-based plugin takes precedence."""
    _write_plugin(
        tmp_path,
        "myplugin.py",
        """
        name = "myplugin"
        commands = ["myplugin go"]
        def handle(text, actor):
            return {"title": "file", "text": "from file"}
    """,
    )
    ep_mod = _make_ep_module("myplugin")
    ep_mod.handle = lambda text, actor: {"title": "ep", "text": "from entry-point"}
    mock_ep = _make_mock_ep("myplugin", ep_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert len(plugins) == 1
    result = plugins[0].handle("myplugin go", "tom")
    assert result["text"] == "from file"


def test_entry_point_plugin_load_error_skipped(tmp_path, monkeypatch, capsys):
    """An entry-point that raises on load is skipped with a warning."""
    broken_ep = MagicMock()
    broken_ep.name = "broken"
    broken_ep.load.side_effect = ImportError("missing dependency")
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [broken_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "broken" in capsys.readouterr().err


def test_entry_point_plugin_missing_attrs_skipped(tmp_path, monkeypatch, capsys):
    """An entry-point module missing required attributes is skipped."""
    bad_mod = types.ModuleType("badplugin")
    bad_mod.name = "badplugin"
    # missing commands and handle
    mock_ep = _make_mock_ep("badplugin", bad_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "badplugin" in capsys.readouterr().err


def test_entry_point_inactive_plugin_skipped(tmp_path, monkeypatch):
    """An entry-point plugin marked inactive in config is skipped."""
    fake_mod = _make_ep_module("myplugin")
    mock_ep = _make_mock_ep("myplugin", fake_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    config = {"myplugin": {"active": "no"}}
    plugins = load_plugins(str(tmp_path), config)

    assert plugins == []


def test_entry_point_plugins_sorted_by_name(tmp_path, monkeypatch):
    """Multiple entry-point plugins are returned in deterministic name order."""
    mod_b = _make_ep_module("beta")
    mod_a = _make_ep_module("alpha")
    eps = [_make_mock_ep("beta", mod_b), _make_mock_ep("alpha", mod_a)]
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: eps
    )

    plugins = load_plugins(str(tmp_path))

    assert [p.name for p in plugins] == ["alpha", "beta"]


def test_load_plugins_nonexistent_dir(tmp_path, monkeypatch):
    """load_plugins handles a nonexistent plugin_dir without error."""
    plugins = load_plugins(str(tmp_path / "does_not_exist"))
    assert plugins == []


# ---------------------------------------------------------------------------
# Matcher integration — representative plugin command shapes
# ---------------------------------------------------------------------------


def test_real_plugin_command_shapes_match_via_substring(tmp_path, monkeypatch):
    """Plugin commands representative of real packages round-trip through find_matches."""
    representative_commands = [
        # itguy-style commands
        "itguy list",
        "itguy deploy sandy",
        "itguy force recordclub",
        "itguy status",
        "itguy disk",
        # estimatedtaxes-style commands
        "tax summary",
        "tax list",
        "tax sync",
    ]

    class _FakePlugin:
        name = "integration-test"
        commands = representative_commands

        def handle(self, text, actor):
            return {"title": "test", "text": "ok"}

    plugins = [_FakePlugin()]

    for cmd in representative_commands:
        assert find_matches(cmd, plugins), f"Expected '{cmd}' to match"
    assert not find_matches("weather today", plugins)


def test_a_module_declaring_nothing_is_skipped_in_silence(tmp_path, capsys):
    """sandy#182: shared scaffolding is not a broken plugin.

    Every `sandy` invocation printed `Warning: skipping base.py: missing name,
    commands, handle` — a warning about correct behaviour, which is the kind
    that trains you to ignore warnings.
    """
    _write_plugin(
        tmp_path,
        "helpers.py",
        """
        def shared_thing():
            return 1
    """,
    )
    _write_plugin(
        tmp_path,
        "good.py",
        """
        name = "good"
        commands = ["test"]
        def handle(text, actor):
            return "ok"
    """,
    )

    plugins = load_plugins(str(tmp_path))

    assert [p.name for p in plugins] == ["good"]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("declared", "expect_warning"),
    [
        ("", False),
        ("name = None", True),
        ('name = "partial"', True),
        ('commands = ["partial"]', True),
        ("def handle(text, actor):\n    return 'ok'", True),
        ('name = "partial"\ncommands = ["partial"]', True),
    ],
)
def test_one_declared_attribute_is_the_line_between_silence_and_a_warning(
    tmp_path, capsys, declared, expect_warning
):
    """The decision this change turns on, at its boundary.

    Not "does base.py stay quiet" — that is one point on a line. Zero of
    `REQUIRED_ATTRS` means the file never claimed to be a plugin; *one* means it
    claimed and got it wrong, and that is the case the diagnostic exists for.
    A fix that silences the noise by widening the skip would pass a
    base.py-shaped test and quietly delete the diagnostic with it.

    `name = None` is presence, not truthiness: the author named the attribute
    and got the value wrong, which is a claim. Rewriting the check as
    `getattr(m, a, None) is not None` otherwise survives the whole suite.
    """
    _write_plugin(tmp_path, "candidate.py", declared)

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert ("candidate.py" in capsys.readouterr().err) is expect_warning


def test_the_real_plugin_directory_loads_without_a_warning(capsys):
    """sandy#182's reproduction, bound to the real tree rather than a fixture.

    `sandy/plugins/base.py` is the file that was noisy, but pinning it by name
    would go green if it were renamed and would say nothing about the next
    helper to land beside it. Loading the shipped directory and asserting an
    empty stderr covers both.

    The non-empty assertion is a reachability control: a `load_plugins` that
    returned nothing would produce an empty stderr too.
    """
    plugins = load_plugins(str(Path(sandy.plugins.__file__).parent))

    assert plugins, "no plugins loaded at all — the silence below proves nothing"
    assert capsys.readouterr().err == ""


def test_a_registered_entry_point_declaring_nothing_still_warns(tmp_path, monkeypatch, capsys):
    """The asymmetry between the two loader paths, stated as a test.

    Registering under `ENTRY_POINT_GROUP` is itself a declaration of intent, so
    a zero-surface entry point *is* broken and must say so. A file sitting in a
    directory has made no such claim. Without this, `_declares_plugin_attrs`
    could be moved into `_validate_plugin` — a tidier-looking one-line change
    that silences a real defect.
    """
    empty_mod = types.ModuleType("emptyplugin")
    mock_ep = _make_mock_ep("emptyplugin", empty_mod)
    monkeypatch.setattr(
        "sandy.loader.importlib.metadata.entry_points", lambda group=None, **kw: [mock_ep]
    )

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert "emptyplugin" in capsys.readouterr().err


def test_a_class_based_plugin_file_still_warns(tmp_path, capsys):
    """sandy#182's fix must not silence the shape `base.py` exists to enable.

    `base.py`'s own docstring says "Subclass this and override `handle()`". A
    file that does exactly that has no module-level `name`/`commands`/`handle`,
    and `_load_file_plugins` appends the *module* — so a class-based plugin
    dropped in the plugin directory has never worked, and this warning is the
    only feedback its author gets. Skipping it in silence would trade a wrong
    diagnostic for a missing one, which is the worse of the two.
    """
    _write_plugin(
        tmp_path,
        "weather.py",
        """
        from sandy.plugins.base import SandyPlugin

        class Weather(SandyPlugin):
            @property
            def name(self):
                return "weather"

            @property
            def commands(self):
                return ["weather"]

            def handle(self, text, actor):
                return "sunny"
    """,
    )

    plugins = load_plugins(str(tmp_path))

    err = capsys.readouterr().err
    assert plugins == []
    assert "weather.py" in err
    # The message has to be TRUE, not merely present. `_validate_plugin`'s
    # "missing name, commands, handle" is false here — the author defined all
    # three, as properties, exactly as `base.py` instructs. A diagnostic that
    # misnames the fault is this whole arm's justification spent and wasted.
    assert "missing name, commands, handle" not in err
    assert "Weather subclasses SandyPlugin" in err
    assert "plugin = Weather()" in err


def test_an_unfinished_subclass_is_scaffolding_and_stays_silent(tmp_path, capsys):
    """The other side of that line, and the reason `base.py` itself is quiet.

    An abstract subclass has not finished claiming to be a plugin — it is the
    next author's starting point. `SandyPlugin` is the first instance of this
    and the `inspect.isabstract` check is what keeps it, and any intermediate
    base someone adds beside it, out of the warning stream.
    """
    _write_plugin(
        tmp_path,
        "shared.py",
        """
        from sandy.plugins.base import SandyPlugin

        class HalfDone(SandyPlugin):
            @property
            def name(self):
                return "half"
    """,
    )

    plugins = load_plugins(str(tmp_path))

    assert plugins == []
    assert capsys.readouterr().err == ""


def test_a_helper_that_merely_imports_a_plugin_class_stays_silent(tmp_path, capsys):
    """`vars()` cannot tell "defined here" from "imported for reuse" — `__module__` can.

    A helper re-exporting a sibling's plugin class has made no claim of its
    own, so it is scaffolding and belongs in the silent arm. Without
    `_own_values`, the imported class is found in `vars()` and the helper is
    reported as an unbridged plugin — a warning naming a class it does not own.

    The sibling is written too, as a reachability control: if the import fails
    the module never loads, `_own_plugin_class` is never reached, and the
    silence below would prove nothing.
    """
    _write_plugin(
        tmp_path,
        "weather.py",
        """
        from sandy.plugins.base import SandyPlugin

        class Weather(SandyPlugin):
            @property
            def name(self):
                return "weather"

            @property
            def commands(self):
                return ["weather"]

            def handle(self, text, actor):
                return "sunny"
    """,
    )
    _write_plugin(
        tmp_path,
        "reuse.py",
        """
        import sys
        sys.path.insert(0, __file__.rsplit("/", 1)[0])
        from weather import Weather  # noqa: F401
    """,
    )

    plugins = load_plugins(str(tmp_path))

    err = capsys.readouterr().err
    assert plugins == []
    # Control: the sibling DID load and DID warn, so the loader reached both
    # files. `reuse.py` is silent because it owns nothing, not because the
    # directory went unread.
    assert "weather.py" in err
    assert "reuse.py" not in err


def test_a_module_exposing_only_a_plugin_instance_still_warns(tmp_path, capsys):
    """The instance arm of `_is_concrete_plugin`, which the class arm does not cover.

    A module that builds its plugin through a factory binds the *instance* and
    never the class, so `vars(module)` holds no `SandyPlugin` subclass to find.
    Only `SandyPlugin` itself is in scope there, and that is abstract — so
    without the `isinstance` arm this file is indistinguishable from a helper
    and goes silent. Found by mutation: dropping that arm survived every other
    test in this module.
    """
    _write_plugin(
        tmp_path,
        "factory_built.py",
        """
        from sandy.plugins.base import SandyPlugin

        def _build():
            class Weather(SandyPlugin):
                @property
                def name(self):
                    return "weather"

                @property
                def commands(self):
                    return ["weather"]

                def handle(self, text, actor):
                    return "sunny"

            return Weather()

        plugin = _build()
    """,
    )

    plugins = load_plugins(str(tmp_path))

    err = capsys.readouterr().err
    assert plugins == []
    assert "factory_built.py" in err
    assert "missing name, commands, handle" not in err
    assert "plugin = Weather()" in err
