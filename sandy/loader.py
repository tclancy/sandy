import importlib.metadata
import importlib.util
import inspect
import os
import sys

from sandy.config import is_active
from sandy.plugins.base import SandyPlugin


REQUIRED_ATTRS = ("name", "commands", "handle")

ENTRY_POINT_GROUP = "sandy.plugins"


def _is_concrete_plugin(value) -> bool:
    """True for a finished `SandyPlugin` subclass or an instance of one.

    Abstract subclasses are excluded on purpose, and `SandyPlugin` itself is the
    first of them: an ABC with unimplemented members is scaffolding for the next
    author, which is the thing this module is trying to stop warning about. A
    subclass that implements every abstract member has finished claiming to be a
    plugin.
    """
    if isinstance(value, SandyPlugin):
        return True
    return (
        isinstance(value, type) and issubclass(value, SandyPlugin) and not inspect.isabstract(value)
    )


def _own_values(module):
    """Values *defined in* `module`, not merely imported into it.

    A helper that does `from .weather import WeatherPlugin` to reuse a plugin
    class has made no claim of its own, and `vars()` cannot tell that apart
    from defining one. Classes carry `__module__`; instances carry it on their
    type.
    """
    for value in vars(module).values():
        owner = value if isinstance(value, type) else type(value)
        if getattr(owner, "__module__", None) == module.__name__:
            yield value


def _declares_plugin_attrs(module) -> bool:
    """True if *module* names any of `REQUIRED_ATTRS` at module scope.

    `REQUIRED_ATTRS` is reused here to answer a different question than
    `_validate_plugin` asks it — "does this file *claim* to be a plugin" rather
    than "is this plugin complete". The two are deliberately the same list: a
    file is claiming exactly as much as it names.

    A module carrying *none* of them is not a broken plugin, it is not a
    plugin. One that carries some but not all is claiming to be one and getting
    it wrong, which is exactly what the warning exists for (#182).
    """
    return any(hasattr(module, attr) for attr in REQUIRED_ATTRS)


def _own_plugin_class(module):
    """The first concrete `SandyPlugin` *module* defines, or None.

    A file following `base.py`'s own instruction — subclass `SandyPlugin`,
    override `handle` — has no module-level surface at all, and the file loader
    appends the *module*, so such a file has never worked. Silencing it would
    trade a wrong diagnostic for a missing one, on exactly the author who most
    needs telling.

    Abstract subclasses are excluded on purpose, and `SandyPlugin` itself is
    the first of them: an ABC with unimplemented members is scaffolding for the
    next author, which is the thing this module is trying to stop warning
    about.

    Deliberately not consulted on the entry-point path: registering under
    `ENTRY_POINT_GROUP` is itself a declaration of intent, so a zero-surface
    entry point *is* broken and should say so.
    """
    for value in _own_values(module):
        if _is_concrete_plugin(value):
            return value if isinstance(value, type) else type(value)
    return None


def _warn_missing_bridge(cls, label: str) -> None:
    """Report a class-based plugin that never reached module scope.

    `_validate_plugin`'s "missing name, commands, handle" is *false* here: the
    author defined all three, as properties, exactly as `base.py` instructs.
    The real defect is that the file loader reads module scope and nothing
    bridged the instance out to it. A diagnostic that misnames the fault is the
    justification for this arm spent and wasted.
    """
    print(
        f"Warning: skipping {label}: {cls.__name__} subclasses SandyPlugin but "
        f"{', '.join(REQUIRED_ATTRS)} are not at module scope — the file loader "
        f"reads the module, so add the bridge: "
        f"`plugin = {cls.__name__}()` then `name = plugin.name`, "
        f"`commands = plugin.commands`, `handle = plugin.handle`",
        file=sys.stderr,
    )


def _validate_plugin(module, label: str) -> bool:
    """Return True if the module has all required Sandy plugin attributes."""
    missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
    if missing:
        print(
            f"Warning: skipping {label}: missing {', '.join(missing)}",
            file=sys.stderr,
        )
        return False

    if not callable(module.handle):
        print(f"Warning: skipping {label}: handle is not callable", file=sys.stderr)
        return False

    return True


def _load_file_plugins(plugin_dir: str, config: dict) -> list:
    """Load plugins from .py files in plugin_dir."""
    plugins = []
    if not os.path.isdir(plugin_dir):
        return plugins

    filenames = sorted(
        f for f in os.listdir(plugin_dir) if f.endswith(".py") and f != "__init__.py"
    )

    for filename in filenames:
        filepath = os.path.join(plugin_dir, filename)
        # Use full filepath in module name to avoid sys.modules collisions
        # when loading plugins from different directories (e.g. in tests)
        module_name = f"sandy_plugin_{os.path.abspath(filepath).replace('/', '_')}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                print(f"Warning: could not create loader for {filename}", file=sys.stderr)
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Warning: failed to load {filename}: {e}", file=sys.stderr)
            continue

        # Three-way, not two. A file claiming nothing is a helper and is
        # skipped in silence; a file whose only claim is a class needs a
        # different diagnostic than `_validate_plugin` can give it.
        if not _declares_plugin_attrs(module):
            orphan = _own_plugin_class(module)
            if orphan is not None:
                _warn_missing_bridge(orphan, filename)
            continue

        if not _validate_plugin(module, filename):
            continue

        if not is_active(config, module.name):
            continue

        plugins.append(module)

    return plugins


def _load_entry_point_plugins(config: dict) -> list:
    """Discover plugins registered via the 'sandy.plugins' entry point group.

    Any installed package that declares::

        [project.entry-points."sandy.plugins"]
        my-plugin = "mypackage.sandy_plugin"

    will have its module loaded and validated here. This allows external
    packages (e.g. itguy, estimatedtaxes) to ship their own Sandy plugin
    without requiring Sandy itself to be updated.
    """
    plugins = []
    eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    for ep in eps:
        try:
            module = ep.load()
        except Exception as e:
            print(
                f"Warning: failed to load entry-point plugin {ep.name!r}: {e}",
                file=sys.stderr,
            )
            continue

        if not _validate_plugin(module, f"entry-point:{ep.name!r}"):
            continue

        if not is_active(config, module.name):  # _validate_plugin ensures module.name exists
            continue

        plugins.append(module)

    # Sort deterministically by plugin name (entry_points order is not spec-guaranteed)
    return sorted(plugins, key=lambda m: m.name)


def load_plugins(plugin_dir: str, config: dict | None = None) -> list:
    """Discover and load valid plugins from a directory and from entry points.

    Loads from two sources:

    1. **File-based**: .py files in *plugin_dir* (existing behaviour).
       Useful for local or project-specific plugins that aren't packaged.

    2. **Entry-point-based**: any installed package that registers the
       ``sandy.plugins`` entry point group.  This is the preferred mechanism
       for plugins that live in their own packages (e.g. itguy, estimatedtaxes).

    File-based plugins take precedence: if a plugin name appears in both
    sources, the file-based version wins.

    Plugins disabled in *config* (active = no) are skipped from both sources.
    """
    if config is None:
        config = {}

    file_plugins = _load_file_plugins(plugin_dir, config)
    ep_plugins = _load_entry_point_plugins(config)

    # Deduplicate: file plugins win over entry-point plugins with the same name
    known_names = {p.name for p in file_plugins}
    unique_ep_plugins = [p for p in ep_plugins if p.name not in known_names]

    return file_plugins + unique_ep_plugins
