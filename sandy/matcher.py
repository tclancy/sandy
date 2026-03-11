def find_matches(text: str, plugins: list) -> list:
    """Find all plugins with a command phrase matching the input text.

    Iterates plugins in order, checks each command phrase as a
    case-insensitive substring match. All matching plugins are returned.
    A plugin appears at most once even if multiple commands match.
    """
    text_lower = text.lower()
    matches = []
    for plugin in plugins:
        for command in plugin.commands:
            if command.lower() in text_lower:
                matches.append(plugin)
                break  # move to next plugin, don't duplicate
    return matches
