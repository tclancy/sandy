"""Actor identity resolution and permission enforcement.

Maps raw actor strings (Slack display names, CLI defaults) to canonical
actor names, and checks whether actors can access plugins and system actions.

Backward compatible: if no [actors] or [permissions] sections exist in config,
all checks pass and behavior is identical to pre-actor Sandy.
"""

from __future__ import annotations


def get_owner(config: dict) -> str | None:
    sandy = config.get("sandy", {})
    if isinstance(sandy, dict):
        owner = sandy.get("owner")
        if owner and isinstance(owner, str):
            return owner.strip()
    return None


def resolve_actor(raw: str, config: dict) -> str | None:
    """Map a raw actor string to a canonical actor name.

    Returns None only when actors are configured and this string is unknown.
    With no [actors] section, returns the raw string (backward compat).
    """
    if not raw:
        return None

    actors = config.get("actors", {})
    if not isinstance(actors, dict) or not actors:
        return raw

    # Case-insensitive matching: Slack lowercases display names,
    # CLI may pass mixed case, config may use either.
    raw_lower = raw.lower()

    owner = get_owner(config)
    if owner and raw_lower == owner.lower():
        return owner

    for canonical, actor_config in actors.items():
        if not isinstance(actor_config, dict):
            continue
        if canonical.lower() == raw_lower:
            return canonical
        aliases = actor_config.get("aliases", [])
        if isinstance(aliases, list) and raw_lower in [a.lower() for a in aliases]:
            return canonical

    return None


def can_use_plugin(canonical_actor: str | None, plugin_name: str, config: dict) -> bool:
    """Check if a resolved actor can access a plugin.

    With no [permissions] section, everything is allowed (backward compat).
    Owner can always access everything. Unknown actors (None) are rejected
    only when permissions are configured.
    """
    if canonical_actor is None:
        return False

    permissions = config.get("permissions", {})
    if not isinstance(permissions, dict) or not permissions:
        return True

    owner = get_owner(config)
    if canonical_actor == owner:
        return True

    default_access = permissions.get("default_access", "private")
    plugins_perms = permissions.get("plugins", {})
    plugin_perms = plugins_perms.get(plugin_name, {}) if isinstance(plugins_perms, dict) else {}
    if not isinstance(plugin_perms, dict):
        plugin_perms = {}

    access = plugin_perms.get("access", default_access)
    if access == "public":
        return True

    allowed = plugin_perms.get("allowed_actors", [])
    if isinstance(allowed, list) and canonical_actor in allowed:
        return True

    return False


def resolve_caps(canonical_actor: str | None, config: dict) -> frozenset[str]:
    """Resolve system-level action capabilities for an actor.

    Owner gets all defined actions. Others get only explicitly granted ones.
    With no config, owner gets all standard caps; others get none.
    """
    if canonical_actor is None:
        return frozenset()

    owner = get_owner(config)
    permissions = config.get("permissions", {})

    if not isinstance(permissions, dict) or not permissions:
        return frozenset() if canonical_actor != owner else frozenset({"print", "cast"})

    actions = permissions.get("actions", {})
    if not isinstance(actions, dict) or not actions:
        return frozenset() if canonical_actor != owner else frozenset({"print", "cast"})

    if canonical_actor == owner:
        return frozenset(actions.keys())

    caps: set[str] = set()
    for action_name, action_config in actions.items():
        if not isinstance(action_config, dict):
            continue
        actors_list = action_config.get("actors", [])
        if isinstance(actors_list, list) and canonical_actor in actors_list:
            caps.add(action_name)

    return frozenset(caps)
