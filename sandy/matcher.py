import re
import string

# Words stripped from the start or end of input before matching.
_POLITE_WORDS = ("please", "thanks", "thank you")


def normalize(text: str) -> str:
    """Normalize input text before matching.

    1. Lowercase
    2. Strip punctuation
    3. Strip common polite words from either end
    4. Collapse and trim whitespace
    """
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    # Strip polite words from ends, repeatedly, until none remain.
    changed = True
    while changed:
        changed = False
        for word in _POLITE_WORDS:
            for pattern in (rf"^{word}\s+", rf"\s+{word}$"):
                stripped = re.sub(pattern, "", text)
                if stripped != text:
                    text = stripped
                    changed = True
    return " ".join(text.split())


def _matches(normalized: str, command: str, mode: str) -> bool:
    """Return True if the plugin's command matches the normalized text.

    ``mode`` is the plugin's ``match_mode`` attribute (default ``"substring"``):

    - ``"substring"`` — case-insensitive substring match; the historical default
      that lets polite framing like "please find me new music today" still
      route to the ``new music`` command.
    - ``"prefix"`` — the command must equal the whole text or appear as the
      first whitespace-delimited phrase. Opt-in for generic leaf words like
      ``help`` where a substring match drags the plugin into unrelated
      commands (e.g. ``itguy logs --help`` normalizes to ``itguy logs help``
      and would otherwise fire the help plugin alongside itguy — #139).
    """
    cmd_lower = command.lower()
    if mode == "prefix":
        return normalized == cmd_lower or normalized.startswith(cmd_lower + " ")
    return cmd_lower in normalized


def find_matches(text: str, plugins: list) -> list:
    """Find all plugins with a command phrase matching the input text.

    Normalizes input before matching (strips punctuation and polite words).
    Iterates plugins in order and asks each command phrase. Substring is the
    default; a plugin can opt into a stricter matcher with ``match_mode``
    (see ``_matches``). All matching plugins are returned; a plugin appears
    at most once even if multiple commands match.
    """
    normalized = normalize(text)
    matches = []
    for plugin in plugins:
        mode = getattr(plugin, "match_mode", "substring")
        for command in plugin.commands:
            if _matches(normalized, command, mode):
                matches.append(plugin)
                break  # move to next plugin, don't duplicate
    return matches
