"""Episode-number parsing primitives shared by RSS workflows.

This module deliberately has no database or network dependencies.  Keeping the
rules here makes the behaviour used by previews, RSS refreshes, and retries
easy to test without constructing a subscription or a SQLAlchemy session.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


# The order is part of the contract: explicit episode markers are less
# ambiguous than a hyphen or a bracketed number in a release title.
DEFAULT_PATTERNS = (
    re.compile(r"(?:\bE(?:P)?|Episode|第)\s*0*(\d{1,4}(?:\.5)?)(?:\s*[集话])?", re.IGNORECASE),
    re.compile(r"-\s*0*(\d{1,4}(?:\.5)?)(?:\s*(?:v\d+)?\s*(?:\[|\(|$))", re.IGNORECASE),
    re.compile(r"\[\s*0*(\d{1,4}(?:\.5)?)\s*\]"),
)


def normalize_episode(value: str) -> str:
    """Return a canonical decimal string while preserving non-numeric input.

    Examples: ``"003"`` becomes ``"3"`` and ``"13.50"`` becomes ``"13.5"``.
    """
    cleaned = value.strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return cleaned
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def episode_number(value: str) -> Decimal | None:
    """Parse an episode value for comparisons, returning ``None`` when invalid."""
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None


def parse_episode(title: str, custom_regex: str = "", group_index: int = 1) -> str:
    """Extract an episode number from a release title.

    A configured regular expression takes precedence. An invalid expression
    returns an empty result, preserving the existing safe failure behaviour.
    If its selected group does not exist, the first capture group (or the
    entire match) is used. The built-in patterns then cover common ``EP12``,
    ``- 12`` and ``[12]`` release-title forms.
    """
    if custom_regex:
        try:
            match = re.search(custom_regex, title, flags=re.IGNORECASE)
        except re.error:
            return ""
        if match:
            try:
                value = match.group(group_index)
            except IndexError:
                value = match.group(1) if match.groups() else match.group(0)
            if value is not None:
                return normalize_episode(str(value))

    for pattern in DEFAULT_PATTERNS:
        match = pattern.search(title)
        if match:
            return normalize_episode(match.group(1))
    return ""


def apply_episode_offset(value: str, offset: int) -> str:
    """Apply a configured offset without changing an unparseable value."""
    number = episode_number(value)
    if number is None:
        return value
    return normalize_episode(str(number + Decimal(offset)))
