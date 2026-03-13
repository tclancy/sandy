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


def find_matches(text: str, plugins: list) -> list:
    """Find all plugins with a command phrase matching the input text.

    Normalizes input before matching (strips punctuation and polite words).
    Iterates plugins in order, checks each command phrase as a
    case-insensitive substring match. All matching plugins are returned.
    A plugin appears at most once even if multiple commands match.
    """
    normalized = normalize(text)
    matches = []
    for plugin in plugins:
        for command in plugin.commands:
            if command.lower() in normalized:
                matches.append(plugin)
                break  # move to next plugin, don't duplicate
    return matches
