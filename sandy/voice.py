"""Sandy's voice — the tiny flourishes that make a tool feel like a person.

Sandy is named for *I Want Sandy* (2007). Eugene Wei's write-up of why it
worked is the design brief for this module — see CLAUDE.md → **Inspiration**.
The passage this file exists to implement:

    "Creating an illusion of personality is difficult, of course, but tiny
    flourishes go a long way. One time I recall sending IWantSandy an email
    at 3 in the morning asking 'her' to remind me of something the next
    morning. Her reply began with 'Wow! You're up late! Get some sleep soon'
    or something like that. Simple to code, powerfully effective."

Two rules keep that from decaying into noise, and both are enforced here
rather than left to the next plugin author's judgement:

**Remark only on what a person would remark on.** A greeting on every command
is a template, and a template reads as software. ``time_of_day_aside`` returns
``None`` for every ordinary hour — Sandy just does the job — and speaks up only
in the hours a friend would actually comment on. The silence is the feature.

**One aside per interaction, never per response.** Sandy fans out: *all*
matching plugins answer a single command. An aside emitted from inside a plugin
would repeat once per match. So asides attach at the delivery boundary
(``cli.main`` and ``daemon._handle_callback``), which is the only place that
knows an interaction is one interaction. Plugins must not call into this module.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The hours a person would remark on, and what Sandy says about them. Both
# windows are half-open on the right and expressed in the *requesting user's*
# timezone, not the server's — 3 a.m. is only remarkable where the user is.
LATE_NIGHT_HOURS = frozenset({23, 0, 1, 2, 3, 4})
EARLY_HOURS = frozenset({5, 6})

LATE_NIGHT: tuple[str, ...] = (
    "Wow, you're up late{comma_name}. Get some sleep soon.",
    "It's the middle of the night{comma_name} — I'm here, but I'd rather you were asleep.",
    "Burning the midnight oil{comma_name}. Right, let's have a look.",
)

EARLY: tuple[str, ...] = (
    "You're up early{comma_name}. I'll try to keep up.",
    "Early start{comma_name}. Give me a second.",
    "Up before the rest of the house{comma_name}? Here you go.",
)

# Enough of the command to make the reply feel heard, not enough to paste a
# runaway string back at the user.
_ECHO_LIMIT = 120


def _display_name(actor: str) -> str:
    """Return *actor* as you'd write it in a sentence, or '' if there isn't one.

    ``"tom"`` → ``"Tom"``; ``"McTavish"`` is already deliberate, so leave it.
    """
    actor = (actor or "").strip()
    if not actor:
        return ""
    return actor if actor[0].isupper() else actor[0].upper() + actor[1:]


def time_of_day_aside(
    now: datetime,
    actor: str,
    choice: Callable[[Sequence[str]], str] = random.choice,
) -> str | None:
    """Return an aside about the hour, or None if the hour is unremarkable.

    *now* is read in whatever timezone it already carries; resolving that is
    ``opening_aside``'s job. *choice* is injected so tests can pin the phrasing
    without seeding the global RNG.
    """
    if now.hour in LATE_NIGHT_HOURS:
        template = choice(LATE_NIGHT)
    elif now.hour in EARLY_HOURS:
        template = choice(EARLY)
    else:
        return None

    name = _display_name(actor)
    return template.format(comma_name=f", {name}" if name else "")


def flourishes_enabled(config: dict | None) -> bool:
    """Return True unless ``[sandy] flourishes`` is switched off.

    Wei's own caveat — "I know some folks would hate that type of false
    anthropomorphism, but perhaps you could choose whether to turn it on or
    off" — so the toggle ships with the flourish. Falsy spellings match
    ``config.is_active``: no / false / 0 / off.
    """
    if not isinstance(config, dict):
        return True
    section = config.get("sandy", {})
    if not isinstance(section, dict):
        return True
    raw = section.get("flourishes", "yes")
    return str(raw).strip().lower() not in ("no", "false", "0", "off")


def _resolve_now(tz: str | None, now: datetime | None) -> datetime:
    """Return *now* (or the current time) expressed in *tz*.

    An unparseable or unknown timezone falls back to the timestamp as given —
    a bad tz string costs you the right flourish, never the reply.

    The default clock is deliberately **aware**: a naive ``datetime.now()``
    cannot be converted, so *tz* would be silently ignored and every user would
    be greeted on the server's hour (sandy#183).
    """
    moment = now if now is not None else datetime.now(UTC)
    if not tz:
        return moment
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return moment
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(zone)


def opening_aside(
    actor: str,
    tz: str | None = None,
    config: dict | None = None,
    now: datetime | None = None,
    choice: Callable[[Sequence[str]], str] = random.choice,
) -> str | None:
    """Return the aside to open this interaction with, or None for silence.

    Resolves the effective timezone the same way ``run_pipeline`` does —
    caller-supplied, then ``[sandy] timezone``, then the local clock.
    """
    if not flourishes_enabled(config):
        return None

    effective_tz = tz
    if not effective_tz and isinstance(config, dict):
        section = config.get("sandy", {})
        if isinstance(section, dict):
            configured = section.get("timezone")
            if isinstance(configured, str) and configured.strip():
                effective_tz = configured.strip()

    return time_of_day_aside(_resolve_now(effective_tz, now), actor, choice=choice)


def prepend_aside(response: dict, aside: str | None) -> dict:
    """Return a copy of *response* with *aside* above its text.

    Returns *response* unchanged when there is no aside, and never mutates the
    caller's dict — plugin responses are shared with the transport layer.
    """
    if not aside:
        return response
    merged = dict(response)
    existing = merged.get("text")
    merged["text"] = f"{aside}\n\n{existing}" if existing else aside
    return merged


def did_not_understand(text: str) -> str:
    """Return Sandy's reply to a command she couldn't match.

    Wei: "sometimes if Sandy didn't understand my command she'd reply asking me
    to clarify." So this echoes what was heard and names the next move, rather
    than closing the conversation with a flat "unknown command".
    """
    said = (text or "").strip()
    if not said:
        return "I didn't catch that. Ask me for `help` and I'll show you what I know."
    if len(said) > _ECHO_LIMIT:
        said = said[:_ECHO_LIMIT].rstrip() + "…"
    return (
        f"I'm not sure what to do with “{said}”. Ask me for `help` and I'll show you what I know."
    )
