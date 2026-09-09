"""Turning what people actually type into an IANA timezone name.

Python needs "America/Chicago", but the natural thing to type is "Central".
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FRIENDLY = {
    "eastern": "America/New_York", "et": "America/New_York",
    "est": "America/New_York", "edt": "America/New_York",
    "east": "America/New_York", "new york": "America/New_York",

    "central": "America/Chicago", "ct": "America/Chicago",
    "cst": "America/Chicago", "cdt": "America/Chicago",
    "chicago": "America/Chicago",

    "mountain": "America/Denver", "mt": "America/Denver",
    "mst": "America/Denver", "mdt": "America/Denver",
    "denver": "America/Denver",

    "arizona": "America/Phoenix", "phoenix": "America/Phoenix",

    "pacific": "America/Los_Angeles", "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "west": "America/Los_Angeles", "los angeles": "America/Los_Angeles",

    "alaska": "America/Anchorage", "hawaii": "Pacific/Honolulu",
}


def resolve(value):
    """Return a usable IANA timezone name, or None if it cannot be understood."""
    if not value:
        return None
    text = str(value).strip()

    # Already a valid IANA name?
    try:
        ZoneInfo(text)
        return text
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        pass

    mapped = FRIENDLY.get(text.lower().replace("_", " ").replace("-", " "))
    if mapped:
        try:
            ZoneInfo(mapped)
            return mapped
        except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
            return None
    return None


def zone(value, fallback="America/Chicago"):
    """Resolve to a ZoneInfo, raising a readable error if we cannot."""
    name = resolve(value) or resolve(fallback)
    if name is None:
        raise ValueError(
            "Could not understand the timezone %r.\n"
            "Use a name like: Central, Eastern, Mountain, Pacific,\n"
            "or a full name like America/Chicago." % value
        )
    return ZoneInfo(name)
